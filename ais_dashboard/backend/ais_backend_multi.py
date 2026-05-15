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

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
AIS_API_KEY = os.getenv("AIS_API_KEY")

if not AIS_API_KEY:
    raise ValueError("AIS_API_KEY environment variable is not set")

MAX_HISTORY = 100

STALE_TIMEOUT = 300

BROADCAST_FPS = 2


# ─────────────────────────────────────────────
# GLOBAL STATE
# ─────────────────────────────────────────────
clients = set()

ships = {}

tracking_target = None

tracking_session_id = 0

last_terminal_print = 0


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

                            print(
                                f"Ships tracked: {len(ships)}"
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

    while True:

        if clients:

            payload = []

            for mmsi, ship in ships.items():

                if (
                    ship["session"]
                    !=
                    tracking_session_id
                ):
                    continue

                if len(ship["history"]) < 1:
                    continue

                coords = [

                    [p[1], p[2]]

                    for p in ship["history"]
                ]

                stats = get_track_stats(
                    ship["history"]
                )

                payload.append({

                    "mmsi": mmsi,

                    "name": ship["name"],

                    "pos": coords[-1],

                    "track": coords,

                    "predicted":
                        ship["predicted"],

                    "sog": ship["sog"],

                    "cog": ship["cog"],

                    "time": time.time(),

                    "lastUpdate":
                        ship["last_update"],

                    "trackStats": stats
                })

            disconnected = []

            for client in clients:

                try:

                    await client.send_json(
                        payload
                    )

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

    asyncio.create_task(
        broadcaster()
    )

    asyncio.create_task(
        persistent_ais_stream()
    )

    yield


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

    clients.add(ws)

    print(
        "Frontend connected"
    )

    try:

        while True:

            data = await ws.receive_json()

            print(
                "WS MESSAGE:",
                data
            )

            # START TRACKING
            if data["type"] == "start":

                tracking_session_id += 1

                tracking_target = {

                    "lat": data["lat"],

                    "lon": data["lon"],

                    "session":
                        tracking_session_id
                }

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

                for mmsi, ship in ships.items():

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

                await ws.send_json(
                    replay_payload
                )

    except Exception as e:

        print(
            "Frontend disconnected:",
            e
        )

        if ws in clients:

            clients.remove(ws)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )