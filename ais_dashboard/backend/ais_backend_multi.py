# backend/ais_backend_multi.py

import os
import asyncio
import websockets
import json
import time
import numpy as np
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pathlib import Path
from math import radians, cos, sin, asin, sqrt
import threading

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

# CV Integration config
CV_OUTPUT_PATH = Path("../outputs/results.json")
CAMERA_LAT = 1.2800
CAMERA_LON = 103.8500
FOV_KM = 2.0
CV_MATCH_RADIUS_DEG = 0.05

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

# CV state
cv_ships = []
cv_lock = threading.Lock()
camera_status = {
    "available": False,
    "lat": CAMERA_LAT,
    "lon": CAMERA_LON,
    "fov_km": FOV_KM,
    "confidence": 0.0,
    "timestamp": 0
}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def calculate_distance(p1, p2):
    """Distance between two points in km (rough approximation)"""
    from math import radians, cos, sin, asin, sqrt
    lon1, lat1 = p1
    lon2, lat2 = p2
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
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
        p1 = (history[i-1][1], history[i-1][2])
        p2 = (history[i][1], history[i][2])
        total_distance += calculate_distance(p1, p2)

    return {
        "duration": duration,
        "distance": total_distance,
        "points": len(history)
    }

def pixels_to_gps(px, py, camera_lat, camera_lon, fov_km, video_width=1920, video_height=1080):
    """Convert pixel coordinates to GPS (simplified for camera FOV)"""
    cx, cy = video_width / 2, video_height / 2
    norm_x = (px - cx) / cx
    norm_y = (cy - py) / cy
    lat_offset = norm_y * (fov_km / 111.0)
    lon_offset = norm_x * (fov_km / (111.0 * cos(radians(camera_lat))))
    return camera_lat + lat_offset, camera_lon + lon_offset

def load_cv_detections():
    """Load latest CV detections from app.py output"""
    global camera_status
    try:
        if not CV_OUTPUT_PATH.exists():
            camera_status["available"] = False
            return []
        with open(CV_OUTPUT_PATH, 'r') as f:
            data = json.load(f)
        if "ships" not in data or not data["ships"]:
            camera_status["available"] = False
            return []
        camera_status["available"] = True
        camera_status["timestamp"] = time.time()
        camera_status["confidence"] = 0.85
        cv_ships_list = []
        for ship_data in data["ships"]:
            center = ship_data.get("center", [0, 0])
            gps_lat, gps_lon = pixels_to_gps(center[0], center[1], camera_status["lat"], camera_status["lon"], camera_status["fov_km"])
            pred_path = ship_data.get("predicted_path", [])
            gps_pred = [pixels_to_gps(p[0], p[1], camera_status["lat"], camera_status["lon"], camera_status["fov_km"]) for p in pred_path]
            cv_ships_list.append({
                "id": ship_data.get("id", 0),
                "gps_lat": gps_lat,
                "gps_lon": gps_lon,
                "confidence": ship_data.get("confidence", 0.7),
                "heading": ship_data.get("heading", 0),
                "predicted_path": gps_pred,
                "timestamp": time.time()
            })
        return cv_ships_list
    except Exception as e:
        print(f"CV loading error: {e}")
        camera_status["available"] = False
        return []

def match_cv_to_ais(cv_ship, ais_ships):
    """Find matching AIS ship for CV detection"""
    for mmsi, ship in ais_ships.items():
        if len(ship["history"]) < 1:
            continue
        ais_lon, ais_lat = ship["history"][-1][1], ship["history"][-1][2]
        dlat = abs(cv_ship["gps_lat"] - ais_lat)
        dlon = abs(cv_ship["gps_lon"] - ais_lon)
        if dlat < CV_MATCH_RADIUS_DEG and dlon < CV_MATCH_RADIUS_DEG:
            return mmsi
    return None

def predict_path(points, steps=10):

    if len(points) < 5:
        return []

    pts = points[-10:]

    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])

    t = np.arange(len(pts))

    try:

        px = np.polyfit(t, xs, 1)
        py = np.polyfit(t, ys, 1)

    except (ValueError, np.linalg.LinAlgError):
        return []

    n = len(pts)

    predicted = []

    for i in range(1, steps + 1):

        pred_x = float(np.polyval(px, n + i))
        pred_y = float(np.polyval(py, n + i))

        predicted.append([pred_x, pred_y])

    return predicted


async def stale_ship_cleanup():
    """Background task to clean up stale ships every 30 seconds"""
    global ships
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
                    print(f"Cleaned up {len(stale)} stale ships")
        except Exception as e:
            print(f"Stale cleanup error: {e}")
            await asyncio.sleep(5)


# ─────────────────────────────────────────────
# REPLAY
# ─────────────────────────────────────────────
def get_state_at_time(ship, target_time):

    pts = ship["history"]

    past = [
        p for p in pts
        if p[0] <= target_time
    ]

    if len(past) < 2:
        return None

    coords = [

        [p[1], p[2]]

        for p in past[-30:]
    ]

    predicted = predict_path(coords)

    return {

        "pos": coords[-1],

        "track": coords,

        "predicted": predicted
    }


# ─────────────────────────────────────────────
# AIS STREAM
# ─────────────────────────────────────────────
async def persistent_ais_stream():

    global tracking_target
    global tracking_session_id
    global last_terminal_print

    uri = "wss://stream.aisstream.io/v0/stream"

    while True:

        subscription_task = None

        try:

            print(
                "Connecting to AISStream..."
            )

            async with websockets.connect(

                uri,

                ping_interval=30,

                ping_timeout=30,

                close_timeout=10

            ) as ws:

                print(
                    "Connected to AISStream"
                )

                current_bbox = None

                last_sub_time = 0

                # ───────────────────────
                # SUBSCRIPTION LOOP
                # ───────────────────────
                async def subscription_loop():

                    nonlocal current_bbox
                    nonlocal last_sub_time

                    while True:

                        try:

                            if tracking_target:

                                lat = tracking_target["lat"]
                                lon = tracking_target["lon"]

                                session = \
                                    tracking_target["session"]

                                bbox_key = (

                                    round(lat,4),

                                    round(lon,4),

                                    session
                                )

                                bbox = [

                                    [
                                        lat - 0.5,
                                        lon - 0.5
                                    ],

                                    [
                                        lat + 0.5,
                                        lon + 0.5
                                    ]
                                ]

                                # ONLY RESUBSCRIBE
                                # IF AREA CHANGED
                                if bbox_key != current_bbox:

                                    now = time.time()

                                    if now - last_sub_time > 1:

                                        sub_message = {

                                            "APIKey":
                                                AIS_API_KEY,

                                            "BoundingBoxes": [
                                                bbox
                                            ]
                                        }

                                        await ws.send(

                                            json.dumps(
                                                sub_message
                                            )
                                        )

                                        current_bbox = \
                                            bbox_key

                                        last_sub_time = now

                                        print(
                                            "Subscribed:",
                                            bbox
                                        )
                            else:
                                now = time.time()
                                if now - last_sub_time > 5:
                                    sub_message = {
                                        "APIKey": AIS_API_KEY,
                                        "BoundingBoxes": [
                                            [[1.0, 103.5], [1.5, 104.0]]
                                        ]
                                    }
                                    await ws.send(
                                        json.dumps(sub_message)
                                    )
                                    last_sub_time = now
                                    print("Default subscription sent (waiting for tracking target)")

                            await asyncio.sleep(1)

                        except asyncio.CancelledError:

                            break

                        except Exception as e:

                            print(
                                "Subscription error:",
                                e
                            )

                            await asyncio.sleep(2)

                subscription_task = \
                    asyncio.create_task(
                        subscription_loop()
                    )

                # ───────────────────────
                # RECEIVE LOOP
                # ───────────────────────
                async for raw in ws:

                    try:

                        data = json.loads(raw)

                        if "Message" not in data:
                            continue

                        msg = data["Message"]

                        if "PositionReport" not in msg:
                            continue

                        pos = msg["PositionReport"]

                        meta = data.get(
                            "MetaData",
                            {}
                        )

                        mmsi = meta.get("MMSI")

                        if not mmsi:
                            continue

                        ship_lat = pos["Latitude"]
                        ship_lon = pos["Longitude"]

                        current_session = \
                            tracking_session_id

                        with ships_lock:

                            if mmsi not in ships:

                                ships[mmsi] = {

                                    "history": [],

                                    "name": meta.get(
                                        "ShipName",
                                        "Unknown"
                                    ),

                                    "sog": 0,

                                    "cog": 0,

                                    "last_update": 0,

                                    "session":
                                        current_session
                                }

                            ship = ships[mmsi]

                            ship["session"] = \
                                current_session

                            now = time.time()

                            ship["last_update"] = now

                            ship["history"].append(

                                (
                                    now,
                                    ship_lon,
                                    ship_lat
                                )
                            )

                            ship["history"] = \
                                ship["history"][-MAX_HISTORY:]

                            ship["sog"] = \
                                pos.get("Sog", 0)

                            ship["cog"] = \
                                pos.get("Cog", 0)

                            coords = [

                                [p[1], p[2]]

                                for p in ship["history"]
                            ]

                            ship["predicted"] = \
                                predict_path(coords)

                        # TERMINAL STATS
                        if now - last_terminal_print > 5:

                            with ships_lock:
                                ship_count = len(ships)

                            print(
                                f"Ships tracked: {ship_count}"
                            )

                            last_terminal_print = now

                    except Exception as e:

                        print(
                            "Parse error:",
                            e
                        )

                    # CLEANUP
                    stale = []

                    now = time.time()

                    for mmsi, ship in ships.items():

                        if (
                            now -
                            ship["last_update"]
                        ) > STALE_TIMEOUT:

                            stale.append(mmsi)

                    for s in stale:

                        del ships[s]

        except Exception as e:

            print(
                "Reconnect:",
                e
            )

            await asyncio.sleep(2)

        finally:

            if subscription_task:

                subscription_task.cancel()


# ─────────────────────────────────────────────
# BROADCASTER
# ─────────────────────────────────────────────
async def broadcaster():

    global tracking_session_id
    global cv_ships

    while True:

        if clients:

            # Load CV detections
            cv_ships = load_cv_detections()

            ais_payload = []

            with ships_lock:
                ships_snapshot = dict(ships.items())

            for mmsi, ship in ships_snapshot.items():

                if (ship["session"] != tracking_session_id):
                    continue

                if len(ship["history"]) < 1:
                    continue

                coords = [[p[1], p[2]] for p in ship["history"]]
                stats = get_track_stats(ship["history"])

                ais_payload.append({
                    "mmsi": mmsi,
                    "name": ship["name"],
                    "pos": coords[-1],
                    "track": coords,
                    "predicted": ship["predicted"],
                    "sog": ship["sog"],
                    "cog": ship["cog"],
                    "time": time.time(),
                    "lastUpdate": ship["last_update"],
                    "trackStats": stats
                })

            # Build CV payload with matching
            cv_payload = []
            for cv in cv_ships:
                matched_mmsi = match_cv_to_ais(cv, ships)
                cv_payload.append({
                    "id": cv["id"],
                    "gps_lat": cv["gps_lat"],
                    "gps_lon": cv["gps_lon"],
                    "confidence": cv["confidence"],
                    "heading": cv["heading"],
                    "predicted_path": cv["predicted_path"],
                    "matched_mmsi": matched_mmsi,
                    "timestamp": cv["timestamp"]
                })

            # Build unified message
            message = {
                "type": "unified",
                "ais_ships": ais_payload,
                "cv_ships": cv_payload,
                "camera_status": camera_status
            }

            disconnected = []

            with clients_lock:
                clients_snapshot = list(clients)

            for client in clients_snapshot:

                try:

                    await client.send_json(message)

                except Exception:

                    disconnected.append(
                        client
                    )

            for d in disconnected:

                if d in clients:

                    clients.remove(d)

        await asyncio.sleep(
            1 / BROADCAST_FPS
        )


# ─────────────────────────────────────────────
# LIFESPAN
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):

    global stale_cleanup_task

    stale_cleanup_task = asyncio.create_task(
        stale_ship_cleanup()
    )

    asyncio.create_task(
        broadcaster()
    )

    asyncio.create_task(
        persistent_ais_stream()
    )

    yield

    stale_cleanup_task.cancel()


# ─────────────────────────────────────────────
# FASTAPI
# ─────────────────────────────────────────────
app = FastAPI(
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# ─────────────────────────────────────────────
# WS ENDPOINT
# ─────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):

    global tracking_target
    global tracking_session_id

    await ws.accept()

    with clients_lock:
        clients.add(ws)

    print(
        "Frontend connected"
    )

    connection_timeout_task = None

    try:

        async def connection_timeout_monitor():
            try:
                while True:
                    await asyncio.sleep(WEBSOCKET_TIMEOUT)
                    if ws.application_state.value == 1:
                        await ws.close(code=1000, reason="Timeout")
                        break
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        connection_timeout_task = asyncio.create_task(
            connection_timeout_monitor()
        )

        while True:

            try:
                data = await asyncio.wait_for(
                    ws.receive_json(),
                    timeout=WEBSOCKET_TIMEOUT
                )
            except asyncio.TimeoutError:
                break
            except Exception:
                break

            print(
                "WS MESSAGE:",
                data
            )

            # START TRACKING
            if data["type"] == "start":

                lat = data.get("lat")
                lon = data.get("lon")

                if lat is None or lon is None:
                    print("Invalid tracking: missing lat/lon")
                    continue

                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    print(f"Invalid tracking: out of bounds ({lat}, {lon})")
                    continue

                tracking_session_id += 1

                tracking_target = {

                    "lat": lat,

                    "lon": lon,

                    "session":
                        tracking_session_id
                }

                with ships_lock:
                    ships.clear()

                print(
                    "Tracking:",
                    tracking_target
                )

            # REPLAY
            elif data["type"] == "replay":

                replay_idx = data.get(
                    "index",
                    0
                )

                replay_payload = []

                with ships_lock:
                    ships_snapshot = dict(ships.items())

                for mmsi, ship in ships_snapshot.items():

                    if len(ship["history"]) <= replay_idx:
                        continue

                    target_point = \
                        ship["history"][replay_idx]

                    coords = [

                        [p[1], p[2]]

                        for p in ship["history"]
                        [:replay_idx + 1]
                    ]

                    predicted = predict_path(
                        coords
                    )

                    stats = get_track_stats(
                        ship["history"]
                        [:replay_idx + 1]
                    )

                    replay_payload.append({

                        "mmsi": mmsi,

                        "name": ship["name"],

                        "pos": [
                            target_point[1],
                            target_point[2]
                        ],

                        "track": coords,

                        "predicted":
                            predicted,

                        "sog": ship["sog"],

                        "cog": ship["cog"],

                        "lastUpdate":
                            target_point[0],

                        "trackStats": stats
                    })

                try:
                    await ws.send_json(
                        replay_payload
                    )
                except Exception:
                    break

    except Exception as e:

        print(
            "Frontend disconnected:",
            e
        )

    finally:

        if connection_timeout_task:
            connection_timeout_task.cancel()

        with clients_lock:
            clients.discard(ws)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )