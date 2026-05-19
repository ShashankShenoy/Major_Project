# app.py
import os
import json
import sys
import base64
import threading
import asyncio

try:
    import torch
except Exception as exc:
    torch = None
    torch_import_error = exc
else:
    torch_import_error = None

selected_device = "cuda" if torch is not None and torch.cuda.is_available() else "cpu"
if selected_device == "cpu":
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
else:
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"

from utils.video_processor import VideoProcessor
from map_view import MapView
from output_handler import save_output
from config import CONFIG
CONFIG["device"] = selected_device

if torch is None:
    print("ERROR: PyTorch failed to import.")
    print(f"Reason: {torch_import_error}")
    print("Install a compatible PyTorch build for Windows.")
    print("For CPU-only use:")
    print("  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu")
    sys.exit(1)

print(f"Using device: {'GPU - ' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")

# ══════════════════════════════════════════════════════════════════
# WEBSOCKET SERVER — streams annotated frames to dashboard
# ══════════════════════════════════════════════════════════════════
try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    print("⚠ websockets not installed — live feed disabled.")
    print("  Run: pip install websockets")

WS_PORT       = 8765
_ws_clients   = set()
_ws_loop      = None
_latest_frame = None
_frame_lock   = threading.Lock()


async def _ws_handler(websocket):
    _ws_clients.add(websocket)
    print(f"📡 Dashboard connected ({len(_ws_clients)} clients)")
    try:
        await websocket.wait_closed()
    finally:
        _ws_clients.discard(websocket)
        print(f"📡 Dashboard disconnected ({len(_ws_clients)} clients)")


async def _ws_broadcaster():
    global _ws_clients

    while True:
        await asyncio.sleep(0.05)

        with _frame_lock:
            frame_b64 = _latest_frame

        if frame_b64 and len(_ws_clients) > 0:
            msg = json.dumps({
                "type": "frame",
                "data": frame_b64
            })

            dead = set()

            for ws in list(_ws_clients):
                try:
                    await ws.send(msg)
                except Exception:
                    dead.add(ws)

            for ws in dead:
                _ws_clients.discard(ws)


async def _ws_main():
    try:
        from websockets.asyncio.server import serve
    except ImportError:
        serve = websockets.serve
    async with serve(_ws_handler, "0.0.0.0", WS_PORT):
        print(f"📡 WebSocket live stream on ws://127.0.0.1:{WS_PORT}")
        await _ws_broadcaster()


def _start_ws_server():
    global _ws_loop
    _ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_ws_loop)
    _ws_loop.run_until_complete(_ws_main())


def push_frame(frame):
    """Encode frame as JPEG base64 and store for broadcast."""
    global _latest_frame
    try:
        import cv2
        small = cv2.resize(frame, (960, 540))
        _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])
        b64 = base64.b64encode(buf).decode("utf-8")
        with _frame_lock:
            _latest_frame = b64
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════
def main():
    input_path  = sys.argv[1] if len(sys.argv) > 1 else CONFIG["input_video"]
    output_path = sys.argv[2] if len(sys.argv) > 2 else CONFIG["output_video"]
    json_path   = sys.argv[3] if len(sys.argv) > 3 else CONFIG["output_json"]

    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print(f"JSON:   {json_path}")
    print("-" * 40)

    # ── Start WebSocket server in background thread ───────────────
    if WS_AVAILABLE:
        ws_thread = threading.Thread(target=_start_ws_server, daemon=True)
        ws_thread.start()
    else:
        print("⚠ Live feed disabled — install websockets first")

    # ── Init pipeline ─────────────────────────────────────────────
    processor = VideoProcessor()

    map_view = MapView(
        camera_lat=CONFIG["camera_lat"],
        camera_lon=CONFIG["camera_lon"],
        map_path=CONFIG["map_path"],
        fov_km=CONFIG["fov_km"]
    )

    # ── Patch map_view.update to push frames to WebSocket ─────────
    _original_update = map_view.update

    def _update_with_ws(ships, frame, frame_num):
        result = _original_update(ships, frame, frame_num)

        if WS_AVAILABLE:
            push_frame(frame)

        return result

    map_view.update = _update_with_ws

    # ── Run pipeline ──────────────────────────────────────────────
    results = processor.process_video_with_map(
        input_path, output_path, map_view, json_path=json_path
    )

    if hasattr(map_view, 'stop'):
        map_view.stop()

    # ── Summary ───────────────────────────────────────────────────
    total_ships = sum(f["ship_count"] for f in results)
    print(f"\nSummary:")
    print(f"  Frames processed : {len(results)}")
    print(f"  Total detections : {total_ships}")
    print(f"  Avg per frame    : {total_ships / max(len(results), 1):.1f}")


if __name__ == "__main__":
    main()
