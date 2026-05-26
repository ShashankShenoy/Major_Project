# backend/ais_backend_unified.py
# Unified AIS backend orchestrating:
# - Real-time AIS streaming
# - Video processing & detection
# - LSTM predictions
# - CV-to-AIS matching
# - Real-time broadcasting to dashboards

import os
import asyncio
import uvicorn
import websockets
import json
import time
import numpy as np
import ssl
import certifi
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from math import radians, cos, sin, asin, sqrt
import threading
from data_models import (
    FrameOutput, ShipDetection, UnifiedMessage, CameraStatus,
    VideoProcessingConfig, SourceType, PredictionMethod
)
from video_orchestrator import VideoOrchestrator, create_video_orchestrator
from cv_matcher import CVMatcher, match_cv_to_ais, enrich_cv_detection_with_ais

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
AIS_API_KEY = os.getenv("AIS_API_KEY")

if not AIS_API_KEY:
    raise ValueError("AIS_API_KEY environment variable is not set")

MAX_HISTORY = 100
STALE_TIMEOUT = 300
BROADCAST_FPS = 2
WEBSOCKET_TIMEOUT = 300
WEBSOCKET_HEARTBEAT = 30

# Video processing config
ENABLE_VIDEO_PROCESSING = True
_DEFAULT_VIDEO = os.getenv("VIDEO_PATH", "")
CAMERA_LAT = float(os.getenv("CAMERA_LAT", "1.2800"))
CAMERA_LON = float(os.getenv("CAMERA_LON", "103.8500"))
FOV_KM = float(os.getenv("FOV_KM", "2.0"))
CV_MATCH_RADIUS_KM = float(os.getenv("CV_MATCH_RADIUS_KM", "5.5"))
DEVICE = os.getenv("DEVICE", "cuda")
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.5"))
AIS_ALLOW_INSECURE_SSL = os.getenv("AIS_ALLOW_INSECURE_SSL", "false").lower() in ["true", "1", "yes"]

# Path to the data/videos folder (relative to project root)
VIDEOS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "videos"
VIDEO_EXTENSIONS = {".avi", ".mp4", ".mov", ".mkv", ".m4v"}

# Mutable runtime VIDEO_PATH — starts from env var or auto-picks first available video
def _resolve_default_video() -> str:
    if _DEFAULT_VIDEO and Path(_DEFAULT_VIDEO).exists():
        return _DEFAULT_VIDEO
    if VIDEOS_DIR.exists():
        for f in sorted(VIDEOS_DIR.iterdir()):
            if f.suffix.lower() in VIDEO_EXTENSIONS:
                return str(f)
    return ""

VIDEO_PATH = _resolve_default_video()

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

# Video processing queue and orchestrator
video_frame_queue: asyncio.Queue = None
video_orchestrator: VideoOrchestrator = None
video_processing_task: asyncio.Task = None  # Track the video processing task

# Current operating mode
current_mode = "ais-only"


# ─────────────────────────────────────────────
# SSL CONTEXT
# ─────────────────────────────────────────────
def build_ais_ssl_context():
    """Create the TLS context used for the AIS websocket connection."""
    if AIS_ALLOW_INSECURE_SSL:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        print("⚠️ AIS TLS verification disabled via AIS_ALLOW_INSECURE_SSL=true")
        return context

    return ssl.create_default_context(cafile=certifi.where())


SSL_CONTEXT = build_ais_ssl_context()


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def extract_ais_position(data):
    """Handle both flat and nested AISStream PositionReport payload shapes."""
    if data.get("MessageType") != "PositionReport":
        return None

    metadata = data.get("MetaData", {}) or {}
    message = data.get("Message", {}) or {}
    report = message.get("PositionReport", message)

    mmsi = report.get("MMSI") or metadata.get("MMSI")
    lon = (
        report.get("Longitude")
        or report.get("longitude")
        or report.get("Lon")
        or report.get("lon")
    )
    lat = (
        report.get("Latitude")
        or report.get("latitude")
        or report.get("Lat")
        or report.get("lat")
    )

    if mmsi is None or lon is None or lat is None:
        return None

    return {
        "mmsi": int(mmsi),
        "lon": float(lon),
        "lat": float(lat),
        "sog": report.get("SOG", report.get("sog", 0)) or 0,
        "cog": report.get("COG", report.get("cog", 0)) or 0,
        "name": (
            metadata.get("ShipName")
            or report.get("ShipName")
            or f"Vessel {mmsi}"
        )
    }


def calculate_distance(p1, p2):
    """Distance between two points in km (Haversine formula)"""
    lon1, lat1 = p1
    lon2, lat2 = p2
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    r = 6371
    return c * r


def get_track_stats(history):
    """Calculate track statistics"""
    if len(history) < 2:
        return {"duration": 0, "distance": 0, "points": len(history)}

    start_time = history[0][0]
    end_time = history[-1][0]
    duration = end_time - start_time

    total_distance = 0
    for i in range(1, len(history)):
        p1 = (history[i - 1][1], history[i - 1][2])
        p2 = (history[i][1], history[i][2])
        total_distance += calculate_distance(p1, p2)

    return {
        "duration": duration,
        "distance": total_distance,
        "points": len(history)
    }


# ─────────────────────────────────────────────
# VIDEO TASK MANAGEMENT
# ─────────────────────────────────────────────
async def cancel_video_processing_task():
    """Safely cancel the video processing task if it's running"""
    global video_processing_task
    
    if video_processing_task is not None and not video_processing_task.done():
        print("⏹️  Cancelling previous video processing task...")
        video_processing_task.cancel()
        try:
            await video_processing_task
        except asyncio.CancelledError:
            print("✅ Previous video processing task cancelled")
    video_processing_task = None


async def start_video_processing():
    """Start the video processing task and track it"""
    global video_processing_task, video_orchestrator, VIDEO_PATH
    
    if video_orchestrator is None:
        return
    
    # Cancel any existing task first
    await cancel_video_processing_task()
    
    # Create and track the new task
    print(f"🎬 Starting video processing task for {Path(VIDEO_PATH).name}")
    video_processing_task = asyncio.create_task(video_orchestrator.process_video(VIDEO_PATH))


# ─────────────────────────────────────────────
# STALE SHIP CLEANUP
# ─────────────────────────────────────────────
async def stale_ship_cleanup():
    """Background task to clean up stale ships every 30 seconds"""
    while True:
        try:
            await asyncio.sleep(30)
            with ships_lock:
                now = time.time()
                stale = [mmsi for mmsi, ship in ships.items()
                         if (now - ship["last_update"]) > STALE_TIMEOUT]
                for mmsi in stale:
                    del ships[mmsi]
                if stale:
                    print(f"🧹 Cleaned up {len(stale)} stale ships")
        except Exception as e:
            print(f"Cleanup error: {e}")
            await asyncio.sleep(5)


# ─────────────────────────────────────────────
# AIS STREAM
# ─────────────────────────────────────────────
async def persistent_ais_stream():
    """Connect to AISStream and handle real-time AIS data"""
    global ships, tracking_target, tracking_session_id, last_terminal_print

    AIS_URL = "wss://stream.aisstream.io/v0/stream"

    while True:
        subscription_task = None

        try:
            async with websockets.connect(
                AIS_URL,
                ssl=SSL_CONTEXT,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
                max_size=10_000_000
            ) as ws:
                print("✅ Connected to AIS stream")

                current_bbox = None
                last_sub_time = 0

                async def subscription_loop():
                    nonlocal current_bbox, last_sub_time

                    while True:
                        try:
                            if tracking_target:
                                lat = tracking_target["lat"]
                                lon = tracking_target["lon"]
                                session = tracking_target["session"]

                                bbox_key = (
                                    round(lat, 4),
                                    round(lon, 4),
                                    session
                                )

                                bbox = [
                                    [lat - 0.5, lon - 0.5],
                                    [lat + 0.5, lon + 0.5]
                                ]

                                if bbox_key != current_bbox:
                                    now = time.time()
                                    if now - last_sub_time > 1:
                                        await ws.send(json.dumps({
                                            "APIKey": AIS_API_KEY,
                                            "BoundingBoxes": [bbox]
                                        }))
                                        current_bbox = bbox_key
                                        last_sub_time = now
                                        print(f"Subscribed: {bbox}")
                            else:
                                now = time.time()
                                if now - last_sub_time > 5:
                                    await ws.send(json.dumps({
                                        "APIKey": AIS_API_KEY,
                                        "BoundingBoxes": [
                                            [[1.0, 103.5], [1.5, 104.0]]
                                        ]
                                    }))
                                    last_sub_time = now
                                    print("Default subscription sent (waiting for tracking target)")

                            await asyncio.sleep(1)

                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            print(f"Subscription error: {e}")
                            await asyncio.sleep(2)

                subscription_task = asyncio.create_task(subscription_loop())

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    position = extract_ais_position(data)
                    if not position:
                        continue

                    mmsi = position["mmsi"]

                    with ships_lock:
                        if mmsi not in ships:
                            ships[mmsi] = {
                                "history": [],
                                "name": position["name"],
                                "sog": 0,
                                "cog": 0,
                                "last_update": time.time(),
                                "session": tracking_session_id,
                                "predicted": []
                            }

                        history = ships[mmsi]["history"]
                        history.append([
                            time.time(),
                            position["lon"],
                            position["lat"]
                        ])

                        if len(history) > MAX_HISTORY:
                            history.pop(0)

                        ships[mmsi]["name"] = position["name"]
                        ships[mmsi]["sog"] = position["sog"]
                        ships[mmsi]["cog"] = position["cog"]
                        ships[mmsi]["last_update"] = time.time()

                    now = time.time()
                    if now - last_terminal_print > 5:
                        with ships_lock:
                            ship_count = len(ships)
                        print(f"Ships tracked: {ship_count}")
                        last_terminal_print = now

        except ssl.SSLError as e:
            print(f"❌ AIS TLS error: {e}")
            if not AIS_ALLOW_INSECURE_SSL:
                print("   Temporary workaround: set AIS_ALLOW_INSECURE_SSL=true if the provider certificate is currently broken.")
        except websockets.ConnectionClosed as e:
            print(f"⚠️ AIS websocket closed: {e}")
        except asyncio.TimeoutError:
            print("⚠️ AIS websocket timeout")
        except Exception as e:
            print(f"AIS stream error: {e}")
        finally:
            if subscription_task:
                subscription_task.cancel()
        await asyncio.sleep(5)


# ─────────────────────────────────────────────
# UNIFIED BROADCASTER
# ─────────────────────────────────────────────
async def unified_broadcaster():
    """
    Unified broadcaster that:
    1. If VIDEO_PROCESSING enabled: Receives frames from video_orchestrator
    2. Matches CV detections to AIS ships
    3. Broadcasts unified message to dashboards
    4. If VIDEO_PROCESSING disabled: Broadcasts AIS-only data
    """
    global clients, ships, current_mode

    cv_matcher = CVMatcher(match_radius_km=CV_MATCH_RADIUS_KM, verbose=True)
    broadcast_interval = 1 / BROADCAST_FPS

    print("🎙️  Unified broadcaster started")
    if not ENABLE_VIDEO_PROCESSING:
        print("   Mode: AIS-ONLY (video processing disabled)")
    else:
        print("   Mode: VIDEO + AIS (hybrid)")

    while True:
        try:
            # Build AIS payload
            with ships_lock:
                ais_ships_snapshot = dict(ships.items())

            ais_payload = []
            for mmsi, ship in ais_ships_snapshot.items():
                if len(ship["history"]) < 1:
                    continue

                coords = [[p[1], p[2]] for p in ship["history"]]
                stats = get_track_stats(ship["history"])

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
                    "predicted_path_gps": ship.get("predicted", []),
                    "timestamp": ship["last_update"],
                    "trackStats": stats
                })

            # Get CV detections only if:
            # 1. Video processing is enabled at startup (orchestrator initialized)
            # 2. Current mode is set to hybrid
            cv_payload = []
            video_frame_b64 = None
            video_frame_timestamp = None

            if ENABLE_VIDEO_PROCESSING and current_mode == "hybrid" and video_frame_queue is not None:
                try:
                    frame_output = None
                    while not video_frame_queue.empty():
                        f = video_frame_queue.get_nowait()
                        frame_output = f
                        if getattr(f, 'video_frame', None):
                            video_frame_b64 = f.video_frame
                            video_frame_timestamp = f.frame_timestamp

                    if frame_output:
                        # Match CV detections to AIS
                        matched_detections = cv_matcher.match_detections(
                            frame_output.ships,
                            ais_ships_snapshot
                        )

                        # Convert to payload format
                        for det in matched_detections:
                            if isinstance(det, ShipDetection):
                                cv_payload.append(det.dict())

                except asyncio.QueueEmpty:
                    pass  # No frame available

            # Combine all ships
            all_ships = cv_payload + ais_payload

            unified_msg = {
                "type": "frame",
                "frame_number": 0,
                "timestamp": time.time(),
                "ships": all_ships,
                "video_frame": video_frame_b64,
                "frame_timestamp": video_frame_timestamp,
                "camera_status": {
                    "available": ENABLE_VIDEO_PROCESSING and current_mode == "hybrid" and video_orchestrator and video_orchestrator.camera_status.available,
                    "lat": CAMERA_LAT if (ENABLE_VIDEO_PROCESSING and current_mode == "hybrid") else 0,
                    "lon": CAMERA_LON if (ENABLE_VIDEO_PROCESSING and current_mode == "hybrid") else 0,
                    "fov_km": FOV_KM if (ENABLE_VIDEO_PROCESSING and current_mode == "hybrid") else 0,
                    "confidence": video_orchestrator.camera_status.confidence if (ENABLE_VIDEO_PROCESSING and current_mode == "hybrid" and video_orchestrator) else 0,
                    "timestamp": time.time()
                },
                "collision_alerts": []
            }

            # Broadcast to all connected clients
            if clients:
                disconnected = []
                with clients_lock:
                    clients_snapshot = list(clients)

                for client in clients_snapshot:
                    try:
                        await client.send_json(unified_msg)
                    except Exception:
                        disconnected.append(client)

                for d in disconnected:
                    if d in clients:
                        clients.discard(d)

            await asyncio.sleep(broadcast_interval)

        except Exception as e:
            print(f"Broadcaster error: {e}")
            await asyncio.sleep(0.1)


# ─────────────────────────────────────────────
# LIFESPAN
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global stale_cleanup_task, video_frame_queue, video_orchestrator, video_processing_task

    print("🚀 AIS Backend starting up...")
    print(f"   Video Processing: {'ENABLED' if ENABLE_VIDEO_PROCESSING else 'DISABLED (AIS-only mode)'}")

    # Create queue for video frames
    video_frame_queue = asyncio.Queue(maxsize=100)
    
    # Do NOT initialize the heavy models on startup. Wait until 'hybrid' mode is selected.
    video_orchestrator = None

    # Start background tasks
    stale_cleanup_task = asyncio.create_task(stale_ship_cleanup())

    asyncio.create_task(unified_broadcaster())

    asyncio.create_task(persistent_ais_stream())

    # Do not start video processing loop here; it will be started in set_mode
    
    print("✅ All tasks started")
    print("   Ready: Live AIS only (Hybrid mode will load ML models when selected)")

    yield

    print("🛑 AIS Backend shutting down...")
    stale_cleanup_task.cancel()
    if video_orchestrator:
        video_orchestrator.stop()
    if video_processing_task is not None and not video_processing_task.done():
        video_processing_task.cancel()
        try:
            await video_processing_task
        except asyncio.CancelledError:
            pass


# ─────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────
app = FastAPI(
    title="Unified Maritime Intelligence Backend",
    description="Real-time AIS + Video + LSTM integration",
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
    global tracking_session_id, tracking_target   # required: we mutate these module-level vars below
    await ws.accept()

    with clients_lock:
        clients.add(ws)

    print(f"✅ Client connected ({len(clients)} total)")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
            elif msg.get("type") == "start":
                lat = msg.get("lat")
                lon = msg.get("lon")

                if lat is None or lon is None:
                    continue

                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue

                tracking_session_id += 1
                tracking_target = {
                    "lat": lat,
                    "lon": lon,
                    "session": tracking_session_id
                }

                with ships_lock:
                    ships.clear()

                print(f"Tracking: {tracking_target}")
            elif msg.get("type") == "replay":
                replay_idx = msg.get("index", 0)
                replay_payload = []

                with ships_lock:
                    ships_snapshot = dict(ships.items())

                for mmsi, ship in ships_snapshot.items():
                    if len(ship["history"]) <= replay_idx:
                        continue

                    target_point = ship["history"][replay_idx]
                    coords = [
                        [p[1], p[2]]
                        for p in ship["history"][:replay_idx + 1]
                    ]

                    replay_payload.append({
                        "mmsi": mmsi,
                        "name": ship["name"],
                        "pos": [target_point[1], target_point[2]],
                        "track": coords,
                        "predicted": ship.get("predicted", []),
                        "sog": ship["sog"],
                        "cog": ship["cog"],
                        "lastUpdate": target_point[0],
                        "trackStats": get_track_stats(ship["history"][:replay_idx + 1])
                    })

                await ws.send_json(replay_payload)

    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        with clients_lock:
            clients.discard(ws)
        print(f"❌ Client disconnected ({len(clients)} remaining)")


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "video_processing": video_orchestrator is not None and video_orchestrator.is_processing,
        "ais_ships": len(ships),
        "connected_clients": len(clients)
    }


# ─────────────────────────────────────────────
# MODE SWITCHING
# ─────────────────────────────────────────────
@app.post("/api/mode/{mode}")
async def set_mode(mode: str):
    """Switch between 'ais-only' and 'hybrid' modes"""
    global current_mode, video_orchestrator, video_frame_queue

    if mode not in ["ais-only", "hybrid"]:
        return {"success": False, "error": f"Invalid mode: {mode}. Must be 'ais-only' or 'hybrid'"}

    if not ENABLE_VIDEO_PROCESSING and mode == "hybrid":
        return {"success": False, "error": "Hybrid mode not available. Video processing is disabled."}

    previous_mode = current_mode
    current_mode = mode
    
    if current_mode == "hybrid" and video_orchestrator is None:
        print("⏳ Initializing Hybrid Mode (Loading YOLO & DeepOcSort)...")
        try:
            config = VideoProcessingConfig(
                video_path=VIDEO_PATH,
                camera_lat=CAMERA_LAT,
                camera_lon=CAMERA_LON,
                fov_km=FOV_KM,
                device=DEVICE,
                confidence_threshold=CONFIDENCE_THRESHOLD,
                cv_match_radius_deg=CV_MATCH_RADIUS_KM / 111.0
            )
            video_orchestrator = await create_video_orchestrator(config)
            await video_orchestrator.initialize(video_frame_queue)
            await start_video_processing()
            print("✅ Hybrid Mode Initialized")
        except Exception as e:
            print(f"⚠️  Video orchestrator init failed: {e}")
            video_orchestrator = None
            current_mode = "ais-only"
            return {"success": False, "error": "Failed to load ML models"}
            
    elif current_mode == "ais-only" and video_orchestrator is not None:
        print("🛑 Stopping Video Processing (Freeing ML models)...")
        video_orchestrator.stop()
        await cancel_video_processing_task()
        video_orchestrator = None
        
        # Flush queue to free memory
        while not video_frame_queue.empty():
            try:
                video_frame_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
                
        # Try to clear CUDA memory if torch is imported
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except:
            pass

    print(f"🔄 Mode switched: {previous_mode} → {current_mode}")

    return {
        "success": True,
        "mode": current_mode,
        "previous_mode": previous_mode,
        "video_enabled": ENABLE_VIDEO_PROCESSING
    }


@app.post("/api/mode")
async def set_mode_from_body(request: Request):
    """Compatibility endpoint for clients that POST JSON {"mode": "..."}."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    mode = payload.get("mode")
    if not mode:
        return {"success": False, "error": "Request body must include a mode field"}

    return await set_mode(mode)


@app.get("/api/mode")
async def get_mode():
    """Get current mode"""
    return {
        "mode": current_mode,
        "video_enabled": ENABLE_VIDEO_PROCESSING,
        "available_modes": ["ais-only", "hybrid"] if ENABLE_VIDEO_PROCESSING else ["ais-only"]
    }


# ─────────────────────────────────────────────
# VIDEO LIBRARY ENDPOINTS
# ─────────────────────────────────────────────
@app.get("/api/videos")
async def list_videos():
    """Return all available video files in the data/videos directory."""
    videos = []
    if VIDEOS_DIR.exists():
        for f in sorted(VIDEOS_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                videos.append({
                    "name": f.name,
                    "path": str(f),
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                    "active": str(f) == VIDEO_PATH
                })
    return {
        "videos": videos,
        "current": VIDEO_PATH,
        "videos_dir": str(VIDEOS_DIR)
    }


@app.post("/api/video/select")
async def select_video(request: Request):
    """
    Switch the active video at runtime.
    Body: { "path": "/absolute/path/to/video.avi" }
    If hybrid mode is running the orchestrator is restarted on the new file.
    """
    global VIDEO_PATH, video_orchestrator, current_mode

    try:
        payload = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid JSON body"}

    new_path = payload.get("path", "").strip()
    if not new_path:
        return {"success": False, "error": "'path' field is required"}

    # Security: must be inside VIDEOS_DIR
    try:
        target = Path(new_path).resolve()
        VIDEOS_DIR.resolve()  # ensure VIDEOS_DIR is resolved too
        target.relative_to(VIDEOS_DIR.resolve())  # raises ValueError if outside
    except ValueError:
        return {"success": False, "error": "Path must be inside the videos directory"}

    if not target.exists():
        return {"success": False, "error": f"File not found: {new_path}"}

    if target.suffix.lower() not in VIDEO_EXTENSIONS:
        return {"success": False, "error": f"Unsupported extension: {target.suffix}"}

    old_path = VIDEO_PATH
    VIDEO_PATH = str(target)
    print(f"🎬 Video selected: {target.name}")

    # If hybrid mode is active, restart the orchestrator on the new file
    if current_mode == "hybrid" and video_orchestrator is not None:
        print("♻️  Restarting video orchestrator on new file...")
        video_orchestrator.stop()
        await cancel_video_processing_task()
        video_orchestrator = None

        # Flush stale frames
        while not video_frame_queue.empty():
            try:
                video_frame_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        try:
            config = VideoProcessingConfig(
                video_path=VIDEO_PATH,
                camera_lat=CAMERA_LAT,
                camera_lon=CAMERA_LON,
                fov_km=FOV_KM,
                device=DEVICE,
                confidence_threshold=CONFIDENCE_THRESHOLD,
                cv_match_radius_deg=CV_MATCH_RADIUS_KM / 111.0
            )
            video_orchestrator = await create_video_orchestrator(config)
            await video_orchestrator.initialize(video_frame_queue)
            await start_video_processing()
            print(f"✅ Orchestrator restarted on {target.name}")
        except Exception as e:
            print(f"⚠️  Failed to restart orchestrator: {e}")
            video_orchestrator = None
            current_mode = "ais-only"
            return {"success": False, "error": f"Orchestrator restart failed: {e}"}

    return {
        "success": True,
        "selected": target.name,
        "path": VIDEO_PATH,
        "previous": old_path,
        "restarted": current_mode == "hybrid"
    }


# Serve hub at root
@app.get("/")
async def serve_root():
    """Serve the unified dashboard hub"""
    hub_path = Path(__file__).parent.parent / "frontend" / "hub.html"
    if hub_path.exists():
        return FileResponse(hub_path, media_type="text/html")
    return {"message": "Maritime Intelligence System"}


@app.get("/dashboard")
async def serve_dashboard():
    """Serve the main AIS dashboard"""
    dashboard_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if dashboard_path.exists():
        return FileResponse(dashboard_path, media_type="text/html")
    return {"error": "Dashboard not found"}


@app.get("/mode-selector")
async def serve_mode_selector():
    """Serve the legacy mode selector"""
    mode_path = Path(__file__).parent.parent / "frontend" / "mode-selector.html"
    if mode_path.exists():
        return FileResponse(mode_path, media_type="text/html")
    return {"error": "Mode selector not found"}


@app.get("/marvis")
async def serve_marvis():
    """Redirect to Marvis dashboard on port 5000"""
    return RedirectResponse(url="http://localhost:5000")


# Mount static files at the end (after all routes) to serve CSS, JS, etc.
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
