# backend/ais_backend_unified.py
# Unified AIS backend orchestrating:
# - Real-time AIS streaming
# - Video processing & detection
# - LSTM predictions
# - CV-to-AIS matching
# - Real-time broadcasting to dashboards

import os
import asyncio
import websockets
import json
import time
import numpy as np
import ssl
import certifi
import uvicorn

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from math import radians, cos, sin, asin, sqrt
import threading

from data_models import (
    FrameOutput,
    ShipDetection,
    UnifiedMessage,
    CameraStatus,
    VideoProcessingConfig,
    SourceType,
    PredictionMethod
)

from video_orchestrator import (
    VideoOrchestrator,
    create_video_orchestrator
)

from cv_matcher import (
    CVMatcher,
    match_cv_to_ais,
    enrich_cv_detection_with_ais
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

AIS_API_KEY = os.getenv("AIS_API_KEY")

if not AIS_API_KEY:
    raise ValueError("AIS_API_KEY environment variable is not set")

MAX_HISTORY = 100
STALE_TIMEOUT = 300
WEBSOCKET_TIMEOUT = 300
WEBSOCKET_HEARTBEAT = 30

# Video processing config
ENABLE_VIDEO_PROCESSING = os.getenv(
    "ENABLE_VIDEO_PROCESSING",
    "true"
).lower() in ["true", "1", "yes"]

VIDEO_PATH = os.getenv(
    "VIDEO_PATH",
    "path/to/video.mp4"
)

CAMERA_LAT = float(os.getenv("CAMERA_LAT", "1.2800"))
CAMERA_LON = float(os.getenv("CAMERA_LON", "103.8500"))

FOV_KM = float(os.getenv("FOV_KM", "5.0"))

CV_MATCH_RADIUS_KM = float(
    os.getenv("CV_MATCH_RADIUS_KM", "8.0")
)

DEVICE = os.getenv("DEVICE", "cuda")

CONFIDENCE_THRESHOLD = float(
    os.getenv("CONFIDENCE_THRESHOLD", "0.5")
)

AIS_BOUNDING_BOX_DEG = float(
    os.getenv("AIS_BOUNDING_BOX_DEG", "0.2")
)

AIS_ALLOW_INSECURE_SSL = os.getenv(
    "AIS_ALLOW_INSECURE_SSL",
    "false"
).lower() in ["true", "1", "yes"]

# ─────────────────────────────────────────────
# GLOBAL STATE
# ─────────────────────────────────────────────

clients = set()
clients_lock = threading.Lock()

ships = {}
ships_lock = threading.Lock()

tracking_target = None
tracking_session_id = 0

last_terminal_print = 0
stale_cleanup_task = None

video_frame_queue: asyncio.Queue = None
video_orchestrator: VideoOrchestrator = None

current_mode = (
    "hybrid"
    if ENABLE_VIDEO_PROCESSING
    else "ais-only"
)

# ─────────────────────────────────────────────
# SSL CONTEXT
# ─────────────────────────────────────────────

def build_ais_ssl_context():
    """Create the TLS context used for the AIS websocket connection."""
    if AIS_ALLOW_INSECURE_SSL:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        print(
            "⚠️ AIS TLS verification disabled via "
            "AIS_ALLOW_INSECURE_SSL=true"
        )
        return context

    return ssl.create_default_context(
        cafile=certifi.where()
    )


SSL_CONTEXT = build_ais_ssl_context()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def calculate_distance(p1, p2):
    """
    Distance between two points in km
    using Haversine formula
    """

    lon1, lat1 = p1
    lon2, lat2 = p2

    lon1, lat1, lon2, lat2 = map(
        radians,
        [lon1, lat1, lon2, lat2]
    )

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    c = 2 * asin(sqrt(a))

    r = 6371

    return c * r


def get_track_stats(history):

    if len(history) < 2:
        return {
            "duration": 0,
            "distance": 0,
            "points": len(history)
        }

    start_time = history[0][0]
    end_time = history[-1][0]

    duration = end_time - start_time

    total_distance = 0

    for i in range(1, len(history)):
        p1 = (
            history[i - 1][1],
            history[i - 1][2]
        )

        p2 = (
            history[i][1],
            history[i][2]
        )

        total_distance += calculate_distance(p1, p2)

    return {
        "duration": duration,
        "distance": total_distance,
        "points": len(history)
    }


# ─────────────────────────────────────────────
# STALE SHIP CLEANUP
# ─────────────────────────────────────────────

async def stale_ship_cleanup():

    while True:

        try:

            await asyncio.sleep(30)

            with ships_lock:

                now = time.time()

                stale = [
                    mmsi
                    for mmsi, ship in ships.items()
                    if (now - ship["last_update"])
                    > STALE_TIMEOUT
                ]

                for mmsi in stale:
                    del ships[mmsi]

                if stale:
                    print(
                        f"🧹 Cleaned up "
                        f"{len(stale)} stale ships"
                    )

        except Exception as e:

            print(f"Cleanup error: {e}")

            await asyncio.sleep(5)


# ─────────────────────────────────────────────
# AIS STREAM
# ─────────────────────────────────────────────

async def persistent_ais_stream():

    global ships
    global tracking_target
    global tracking_session_id

    AIS_URL = "wss://stream.aisstream.io/v0/stream"

    subscription = {
        "BaseStations": [],
        "BoundingBoxes": [
            {
                "NorthEast": {
                    "latitude":
                        CAMERA_LAT + AIS_BOUNDING_BOX_DEG,
                    "longitude":
                        CAMERA_LON + AIS_BOUNDING_BOX_DEG
                },
                "SouthWest": {
                    "latitude":
                        CAMERA_LAT - AIS_BOUNDING_BOX_DEG,
                    "longitude":
                        CAMERA_LON - AIS_BOUNDING_BOX_DEG
                }
            }
        ]
    }

    print("🌍 AIS Bounding Box:")
    print(subscription["BoundingBoxes"][0])

    while True:

        try:

            async with websockets.connect(
                AIS_URL,
                ssl=SSL_CONTEXT,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
                max_size=10_000_000
            ) as ws:

                await ws.send(
                    json.dumps({
                        "APIKey": AIS_API_KEY,
                        "Subscribe": subscription
                    })
                )

                print("✅ Connected to AIS stream")

                while True:

                    msg = await ws.recv()

                    data = json.loads(msg)

                    if data.get("MessageType") != "PositionReport":
                        continue

                    message = data.get("Message", {})

                    mmsi = message.get("MMSI")

                    if not mmsi:
                        continue

                    lon = message.get("Longitude")
                    lat = message.get("Latitude")

                    if lon is None or lat is None:
                        continue

                    with ships_lock:

                        if mmsi not in ships:

                            ships[mmsi] = {
                                "history": [],
                                "name": message.get(
                                    "ShipName",
                                    f"Vessel {mmsi}"
                                ),
                                "sog": 0,
                                "cog": 0,
                                "last_update": time.time(),
                                "session":
                                    tracking_session_id,
                                "predicted": []
                            }

                        history = ships[mmsi]["history"]

                        history.append([
                            time.time(),
                            lon,
                            lat
                        ])

                        if len(history) > MAX_HISTORY:
                            history.pop(0)

                        ships[mmsi]["sog"] = (
                            message.get("SOG", 0)
                        )

                        ships[mmsi]["cog"] = (
                            message.get("COG", 0)
                        )

                        ships[mmsi]["last_update"] = (
                            time.time()
                        )

        except ssl.SSLError as e:

            print(f"❌ AIS TLS error: {e}")
            if not AIS_ALLOW_INSECURE_SSL:
                print(
                    "   Temporary workaround: set "
                    "AIS_ALLOW_INSECURE_SSL=true if the "
                    "provider certificate is currently broken."
                )

        except websockets.ConnectionClosed as e:

            print(
                f"⚠️ AIS websocket closed: {e}"
            )

        except asyncio.TimeoutError:

            print(
                "⚠️ AIS websocket timeout"
            )

        except Exception as e:

            print(f"AIS stream error: {e}")

        print("🔄 Reconnecting in 5 seconds...")
        await asyncio.sleep(5)


# ─────────────────────────────────────────────
# UNIFIED BROADCASTER
# ─────────────────────────────────────────────

async def unified_broadcaster():

    global clients
    global ships
    global current_mode

    cv_matcher = CVMatcher(
        match_radius_km=CV_MATCH_RADIUS_KM,
        verbose=True
    )

    broadcast_interval = 0.5

    print("🎙️ Unified broadcaster started")

    if not ENABLE_VIDEO_PROCESSING:
        print("   Mode: AIS-ONLY")
    else:
        print("   Mode: HYBRID")

    while True:

        try:

            with ships_lock:
                ais_ships_snapshot = dict(
                    ships.items()
                )

            print(
                f"[AIS] Active ships: "
                f"{len(ais_ships_snapshot)}"
            )

            ais_payload = []

            for mmsi, ship in (
                ais_ships_snapshot.items()
            ):

                if len(ship["history"]) < 1:
                    continue

                coords = [
                    [p[1], p[2]]
                    for p in ship["history"]
                ]

                stats = get_track_stats(
                    ship["history"]
                )

                ais_payload.append({
                    "id": f"ais_{mmsi}",
                    "mmsi": mmsi,
                    "name": ship["name"],
                    "source": "AIS",
                    "gps": coords[-1],
                    "track": coords,
                    "sog": ship["sog"],
                    "cog": ship["cog"],
                    "heading": ship["cog"],
                    "confidence": 1.0,
                    "predicted_path_gps":
                        ship.get("predicted", []),
                    "timestamp":
                        ship["last_update"],
                    "trackStats": stats
                })

            cv_payload = []

            if (
                ENABLE_VIDEO_PROCESSING
                and current_mode == "hybrid"
                and video_frame_queue is not None
            ):

                try:

                    frame_output: FrameOutput = (
                        video_frame_queue.get_nowait()
                    )

                    matched_detections = (
                        cv_matcher.match_detections(
                            frame_output.ships,
                            ais_ships_snapshot
                        )
                    )

                    matched_count = 0

                    for det in matched_detections:

                        if isinstance(
                            det,
                            ShipDetection
                        ):

                            if (
                                hasattr(det, "matched_mmsi")
                                and det.matched_mmsi
                            ):
                                matched_count += 1

                            cv_payload.append(
                                det.dict()
                            )

                    print(
                        f"[CVMatcher] "
                        f"{matched_count}/"
                        f"{len(matched_detections)} "
                        f"matched"
                    )

                except asyncio.QueueEmpty:
                    pass

                except Exception as e:
                    print(
                        f"CV processing error: {e}"
                    )

            all_ships = cv_payload + ais_payload

            unified_msg = {
                "type": "frame",
                "frame_number": 0,
                "timestamp": time.time(),
                "ships": all_ships,
                "camera_status": {
                    "available": (
                        ENABLE_VIDEO_PROCESSING
                        and current_mode == "hybrid"
                        and video_orchestrator
                        and video_orchestrator
                        .camera_status.available
                    ),

                    "lat":
                        CAMERA_LAT
                        if current_mode == "hybrid"
                        else 0,

                    "lon":
                        CAMERA_LON
                        if current_mode == "hybrid"
                        else 0,

                    "fov_km":
                        FOV_KM
                        if current_mode == "hybrid"
                        else 0,

                    "confidence":
                        (
                            video_orchestrator
                            .camera_status.confidence
                            if (
                                current_mode == "hybrid"
                                and video_orchestrator
                            )
                            else 0
                        ),

                    "timestamp": time.time()
                },

                "collision_alerts": []
            }

            if clients:

                disconnected = []

                with clients_lock:
                    clients_snapshot = list(
                        clients
                    )

                for client in clients_snapshot:

                    try:

                        await client.send_json(
                            unified_msg
                        )

                    except Exception:
                        disconnected.append(
                            client
                        )

                with clients_lock:

                    for d in disconnected:
                        clients.discard(d)

            await asyncio.sleep(
                broadcast_interval
            )

        except Exception as e:

            print(
                f"Broadcaster error: {e}"
            )

            await asyncio.sleep(1)


# ─────────────────────────────────────────────
# LIFESPAN
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):

    global stale_cleanup_task
    global video_frame_queue
    global video_orchestrator

    print("🚀 AIS Backend starting...")

    print(
        f"Video Processing: "
        f"{'ENABLED' if ENABLE_VIDEO_PROCESSING else 'DISABLED'}"
    )

    video_frame_queue = asyncio.Queue(
        maxsize=100
    )

    if ENABLE_VIDEO_PROCESSING:

        try:

            config = VideoProcessingConfig(
                video_path=VIDEO_PATH,
                camera_lat=CAMERA_LAT,
                camera_lon=CAMERA_LON,
                fov_km=FOV_KM,
                device=DEVICE,
                confidence_threshold=
                    CONFIDENCE_THRESHOLD,
                cv_match_radius_deg=
                    CV_MATCH_RADIUS_KM / 111.0
            )

            video_orchestrator = (
                await create_video_orchestrator(
                    config
                )
            )

            await video_orchestrator.initialize(
                video_frame_queue
            )

            print(
                "✅ Video orchestrator initialized"
            )

        except Exception as e:

            print(
                f"⚠️ Video init failed: {e}"
            )

            video_orchestrator = None

    stale_cleanup_task = asyncio.create_task(
        stale_ship_cleanup()
    )

    asyncio.create_task(
        unified_broadcaster()
    )

    asyncio.create_task(
        persistent_ais_stream()
    )

    if (
        video_orchestrator
        and ENABLE_VIDEO_PROCESSING
    ):

        asyncio.create_task(
            video_orchestrator.process_video(
                VIDEO_PATH
            )
        )

    print("✅ System ready")

    yield

    print("🛑 Shutting down...")

    stale_cleanup_task.cancel()

    if video_orchestrator:
        video_orchestrator.stop()


# ─────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────

app = FastAPI(
    title="Unified Maritime Intelligence Backend",
    description="Real-time AIS + Video + LSTM",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ─────────────────────────────────────────────
# WEBSOCKET ENDPOINT
# ─────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):

    await ws.accept()

    with clients_lock:
        clients.add(ws)

    print(
        f"✅ Client connected "
        f"({len(clients)} total)"
    )

    try:

        while True:

            data = await ws.receive_text()

            msg = json.loads(data)

            if msg.get("type") == "ping":

                await ws.send_json({
                    "type": "pong"
                })

    except Exception as e:

        print(f"WebSocket error: {e}")

    finally:

        with clients_lock:
            clients.discard(ws)

        print(
            f"❌ Client disconnected "
            f"({len(clients)} remaining)"
        )


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

@app.get("/health")
async def health_check():

    return {
        "status": "ok",

        "video_processing":
            (
                video_orchestrator is not None
                and video_orchestrator.is_processing
            ),

        "ais_ships": len(ships),

        "connected_clients":
            len(clients),

        "mode":
            current_mode
    }


# ─────────────────────────────────────────────
# MODE SWITCHING
# ─────────────────────────────────────────────

@app.post("/api/mode/{mode}")
async def set_mode(mode: str):

    global current_mode

    if mode not in ["ais-only", "hybrid"]:

        return {
            "success": False,
            "error":
                "Mode must be "
                "'ais-only' or 'hybrid'"
        }

    if (
        not ENABLE_VIDEO_PROCESSING
        and mode == "hybrid"
    ):

        return {
            "success": False,
            "error":
                "Hybrid unavailable"
        }

    previous_mode = current_mode

    current_mode = mode

    print(
        f"🔄 Mode switched: "
        f"{previous_mode} → {current_mode}"
    )

    return {
        "success": True,
        "mode": current_mode,
        "previous_mode": previous_mode
    }


@app.get("/api/mode")
async def get_mode():

    return {
        "mode": current_mode,
        "video_enabled":
            ENABLE_VIDEO_PROCESSING,

        "available_modes":
            (
                ["ais-only", "hybrid"]
                if ENABLE_VIDEO_PROCESSING
                else ["ais-only"]
            )
    }


# ─────────────────────────────────────────────
# FRONTEND ROUTES
# ─────────────────────────────────────────────

@app.get("/")
async def serve_root():

    hub_path = (
        Path(__file__).parent.parent
        / "frontend"
        / "hub.html"
    )

    if hub_path.exists():

        return FileResponse(
            hub_path,
            media_type="text/html"
        )

    return {
        "message":
            "Maritime Intelligence System"
    }


@app.get("/dashboard")
async def serve_dashboard():

    dashboard_path = (
        Path(__file__).parent.parent
        / "frontend"
        / "index.html"
    )

    if dashboard_path.exists():

        return FileResponse(
            dashboard_path,
            media_type="text/html"
        )

    return {
        "error":
            "Dashboard not found"
    }


@app.get("/mode-selector")
async def serve_mode_selector():

    mode_path = (
        Path(__file__).parent.parent
        / "frontend"
        / "mode-selector.html"
    )

    if mode_path.exists():

        return FileResponse(
            mode_path,
            media_type="text/html"
        )

    return {
        "error":
            "Mode selector not found"
    }


@app.get("/marvis")
async def serve_marvis():

    return RedirectResponse(
        url="http://localhost:5000"
    )


# ─────────────────────────────────────────────
# STATIC FILES
# ─────────────────────────────────────────────

frontend_path = (
    Path(__file__).parent.parent
    / "frontend"
)

if frontend_path.exists():

    app.mount(
        "/",
        StaticFiles(
            directory=str(frontend_path),
            html=True
        ),
        name="frontend"
    )

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )
