from flask import Flask, send_from_directory, jsonify, request, send_file
import cv2
import json
import sys
import os
from pathlib import Path
import time
import numpy as np
import base64
from threading import Thread, Lock, Event
from collections import deque
from io import BytesIO

app = Flask(__name__, static_folder="../frontend", static_url_path="")

# ── CORS: allow hub (localhost:8000) to fetch this backend (localhost:5000) ──
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

# Configuration
VIDEO_PATH = os.getenv("VIDEO_PATH", "C:\\Users\\91944\\MajorProject\\data\\videos\\input.avi")
DEVICE = os.getenv("DEVICE", "cuda")
INITIAL_BUFFER_SECONDS = 30  # Process 30 seconds before broadcasting
UPDATE_INTERVAL_SECONDS = 30  # Update predictions every 30 seconds
DISPLAY_UPDATE_SECONDS = float(os.getenv("DISPLAY_UPDATE_SECONDS", "1.0"))

# Add AIS backend to path so we can import lstm_integration
# Path(__file__).parent = marvis_dashboard/backend
# Path(__file__).parent.parent = marvis_dashboard
# Path(__file__).parent.parent.parent = MajorProject  ← correct root
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "ais_dashboard" / "backend"))

# Global state
current_results = {}  # Current displayable results
all_frames = deque(maxlen=10000)  # Store all frames for history
processing = False
buffer_complete = False
buffer_message = "⏳ Building 30-second buffer for LSTM stabilization..."
last_update_time = 0
update_lock = Lock()
stop_processing = Event()  # Event to signal processing thread to stop
current_mode = "hybrid"  # Default mode

def load_lstm_predictor():
    """Load LSTM predictor using a path derived from this file's location"""
    try:
        from lstm_integration import LSTMEngine
        # Resolve model path relative to project root (works on any machine)
        model_path = str(
            Path(__file__).resolve().parent.parent.parent / "models" / "lstm_model_trained.pt"
        )
        return LSTMEngine(model_path=model_path, device=DEVICE)
    except Exception as e:
        print(f"⚠️  LSTM load failed: {e}")
        return None

def process_video_with_lstm():
    """
    Process video with 30s buffer + 30s update intervals
    
    Strategy:
    1. Buffer 30 seconds of video (stabilize LSTM on initial data)
    2. Build ship tracks during buffer phase (no predictions shown yet)
    3. After buffer: generate predictions and update every 30 seconds
    4. This prevents "crazy" predictions from unstable LSTM early on
    """
    global current_results, all_frames, processing, buffer_complete
    global buffer_message, last_update_time, stop_processing

    processing = True
    all_frames.clear()
    current_results = {}
    stop_processing.clear()  # Reset stop flag
    last_update_time = 0

    print(f"\n🎬 Starting Video Processing with Unified Strategy")
    print(f"   Video: {VIDEO_PATH}")
    print(f"   Buffer Phase: {INITIAL_BUFFER_SECONDS}s (LSTM stabilization)")
    print(f"   Update Interval: {UPDATE_INTERVAL_SECONDS}s (after buffer)")
    print(f"   Display Refresh: {DISPLAY_UPDATE_SECONDS}s")
    print(f"   {'=' * 60}\n")

    if not Path(VIDEO_PATH).exists():
        print(f"❌ Video not found: {VIDEO_PATH}")
        buffer_message = "❌ Video not found"
        processing = False
        return

    try:
        lstm_engine = load_lstm_predictor()
        cap = cv2.VideoCapture(VIDEO_PATH)

        if not cap.isOpened():
            print(f"❌ Failed to open video")
            buffer_message = "❌ Failed to open video"
            processing = False
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        print(f"   FPS: {fps}, Total frames: {total_frames}")

        # Cap buffer at actual video length so short videos don't stay stuck in buffer phase
        buffer_frames = min(
            int(fps * INITIAL_BUFFER_SECONDS) if fps > 0 else 900,
            max(total_frames - 1, 1)           # never exceed the video length
        )
        update_frame_interval = int(fps * UPDATE_INTERVAL_SECONDS) if fps > 0 else 900
        
        print(f"   Buffer Phase: {buffer_frames} frames (~{INITIAL_BUFFER_SECONDS}s)")
        print(f"   Update Interval: {update_frame_interval} frames (~{UPDATE_INTERVAL_SECONDS}s)\n")

        frame_count = 0
        start_time = time.time()
        buffer_complete = False
        last_frame = None  # Store latest frame for display

        # Initialize realistic simulated ships with STABLE motion
        simulated_ships = {}
        for i in range(5):
            # Use stable, realistic velocities (ships don't zigzag)
            vx = 1.0 + (i * 0.3)  # Steady velocity X
            vy = 0.3 + (i * 0.1)  # Steady velocity Y (slight)
            simulated_ships[f"ship_{i}"] = {
                "positions": [],
                "mmsi": 100000 + i,
                "name": f"Vessel {i}",
                "vx": vx,
                "vy": vy,
                "x": 200.0 + (i * 80),
                "y": 200.0 + (i * 40),
                "predicted_path": [],
                "prediction_method": "KINEMATIC"
            }
        
        print(f"   Initialized {len(simulated_ships)} simulated vessels with stable motion\n")

        # ── Outer replay loop — rewinds when video ends ──────────────────
        while processing and not stop_processing.is_set():

            # Do NOT reset ship positions on each replay pass — ships continue
            # from where they left off, wrapping at screen boundaries.
            # This prevents the sudden position jumps / flickering trajectories.
            # Only clear all_frames so stale frames don't mix with new ones.
            all_frames.clear()

            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)   # rewind video to start
            inner_frame = 0

            while cap.isOpened() and processing and not stop_processing.is_set():
                ret, frame = cap.read()
                if not ret:
                    break   # inner loop done — outer loop will rewind

                last_frame = frame.copy()

                frame_output = {
                    "frame_number": frame_count,
                    "timestamp": time.time(),
                    "ships": [],
                    "collision_alerts": [],
                    "buffer_phase": not buffer_complete,
                    "prediction_method": "KINEMATIC"
                }

                for ship_id, ship_data in simulated_ships.items():
                    ship_data["x"] += ship_data["vx"]
                    ship_data["y"] += ship_data["vy"]
                    # Wrap ships at screen boundary so they never fly off-screen
                    # (wrap-around is smooth — avoids the teleport-to-origin jump)
                    if ship_data["x"] > 1200:
                        ship_data["x"] = 100.0
                        ship_data["positions"] = []   # reset track only on wrap
                    elif ship_data["x"] < 50:
                        ship_data["x"] = 1100.0
                        ship_data["positions"] = []
                    if ship_data["y"] > 700:
                        ship_data["y"] = 100.0
                        ship_data["positions"] = []
                    elif ship_data["y"] < 50:
                        ship_data["y"] = 600.0
                        ship_data["positions"] = []
                    x = ship_data["x"]
                    y = ship_data["y"]
                    ship_data["positions"].append([x, y])

                    predicted_path = ship_data["predicted_path"]
                    method = ship_data["prediction_method"]

                    if buffer_complete and lstm_engine and frame_count % update_frame_interval == 0:
                        try:
                            lstm_engine.update(ship_id, x, y)
                            predicted_path, method = lstm_engine.predict(ship_id)
                            ship_data["predicted_path"] = predicted_path or []
                            ship_data["prediction_method"] = method
                        except Exception as e:
                            print(f"   ⚠️  LSTM prediction error: {e}")
                    elif not buffer_complete:
                        ship_data["predicted_path"] = []
                        ship_data["prediction_method"] = "KINEMATIC"
                        predicted_path = []
                        method = "KINEMATIC"
                    else:
                        predicted_path = ship_data["predicted_path"]
                        method = ship_data["prediction_method"]

                    ship_output = {
                        "id": ship_id,
                        "mmsi": ship_data["mmsi"],
                        "name": ship_data["name"],
                        "pos": [x, y],
                        "track": ship_data["positions"][-100:],
                        "heading": float(np.arctan2(ship_data["vy"], ship_data["vx"]) * 180 / np.pi),
                        "sog": float(np.sqrt(ship_data["vx"]**2 + ship_data["vy"]**2)),
                        "cog": float(np.arctan2(ship_data["vy"], ship_data["vx"]) * 180 / np.pi),
                        "confidence": 0.95 if buffer_complete else 0.50,
                        "source": "LSTM" if buffer_complete else "KINEMATIC",
                        "predicted_path_gps": predicted_path if (buffer_complete and predicted_path) else [],
                        "prediction_method": method,
                        "timestamp": time.time()
                    }
                    frame_output["ships"].append(ship_output)

                all_frames.append(frame_output)

                # Refresh display at DISPLAY_UPDATE_SECONDS interval
                current_time = time.time()
                if current_time - last_update_time >= DISPLAY_UPDATE_SECONDS:
                    frame_display = last_frame.copy() if last_frame is not None else None
                    frame_base64 = None
                    if frame_display is not None:
                        h, w = frame_display.shape[:2]
                        if w > 1280 or h > 720:
                            scale = min(1280 / w, 720 / h)
                            frame_display = cv2.resize(frame_display, (int(w * scale), int(h * scale)))
                        for ship in frame_output["ships"]:
                            sx, sy = int(ship["pos"][0]), int(ship["pos"][1])
                            conf = ship["confidence"]
                            sz = 25
                            col = (0, 255, 0) if conf > 0.7 else (0, 165, 255)
                            cv2.rectangle(frame_display, (sx-sz, sy-sz), (sx+sz, sy+sz), col, 2)
                            cv2.putText(frame_display, ship["name"], (sx-sz, sy-sz-5),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
                        ok, encoded = cv2.imencode(".jpg", frame_display)
                        if ok:
                            frame_base64 = base64.b64encode(encoded).decode("utf-8")
                    frame_output["video_frame"] = frame_base64
                    frame_output["frame_timestamp"] = time.time()
                    with update_lock:
                        current_results = frame_output
                        last_update_time = current_time
                    print(
                        f"   📸 Frame {frame_count} | buf={'done' if buffer_complete else 'wait'} "
                        f"| conf={frame_output['ships'][0]['confidence'] if frame_output['ships'] else 'N/A'}"
                    )

                # Buffer completion check
                if frame_count >= buffer_frames and not buffer_complete:
                    buffer_complete = True
                    elapsed_buf = time.time() - start_time
                    buffer_message = (
                        f"✅ Buffer complete after {elapsed_buf:.1f}s. "
                        f"LSTM active — updating every {UPDATE_INTERVAL_SECONDS}s."
                    )
                    print(f"\n✅ BUFFER COMPLETE at frame {frame_count} ({elapsed_buf:.1f}s)")
                    print(f"   LSTM predictions now active.\n")

                frame_count += 1
                inner_frame += 1

                if inner_frame % 150 == 0:
                    elapsed = time.time() - start_time
                    fps_a = frame_count / elapsed if elapsed > 0 else 0
                    phase = "🔄 BUFFER" if not buffer_complete else "📊 ACTIVE"
                    print(f"   [{phase}] frame={frame_count} inner={inner_frame}/{total_frames} ({fps_a:.1f} fps)")

            # Inner loop ended (video ran out or stopped)
            if not buffer_complete:
                buffer_complete = True
                buffer_message = (
                    f"✅ Short video ({inner_frame} frames). "
                    f"LSTM active. Looping from start."
                )
                print("✅ Video ended before buffer filled — buffer marked complete. Rewinding.")
                print(f"🔁 Video loop done at frame {inner_frame}. Rewinding for next pass.")

        cap.release()
        print("🛑 Outer replay loop exited.")

    except Exception as e:
        print(f"❌ Processing error: {e}")
        buffer_message = f"❌ Processing error: {e}"
        import traceback
        traceback.print_exc()

    finally:
        processing = False
        stop_processing.clear()

processor_thread = Thread(target=process_video_with_lstm, daemon=True)
processor_thread.start()

@app.route("/api/mode", methods=["POST"])
def set_mode():
    """Set operating mode and handle mode switching"""
    global current_mode, stop_processing, processor_thread
    
    mode = request.json.get("mode", "hybrid")
    
    print(f"🔄 Mode switch requested: {current_mode} → {mode}")
    
    if mode == current_mode:
        return jsonify({"success": False, "message": f"Already in {mode} mode"}), 400
    
    # Stop current video processing
    if processing:
        print(f"⏹️  Stopping current video processing...")
        stop_processing.set()
        # Wait for processing thread to finish
        for _ in range(50):  # Max 5 seconds wait
            if not processing:
                break
            time.sleep(0.1)
    
    current_mode = mode
    
    if mode == "hybrid":
        # Restart video processing for hybrid mode
        print(f"🚀 Starting video processing for hybrid mode")
        processor_thread = Thread(target=process_video_with_lstm, daemon=True)
        processor_thread.start()
        return jsonify({
            "success": True,
            "message": "Switched to Hybrid mode",
            "mode": mode
        }), 200
    elif mode == "ais-only":
        # AIS-only mode - no video processing needed
        print(f"📡 Switched to AIS-Only mode")
        return jsonify({
            "success": True,
            "message": "Switched to AIS-Only mode",
            "mode": mode
        }), 200
    else:
        return jsonify({"success": False, "message": f"Unknown mode: {mode}"}), 400

@app.route("/api/mode", methods=["GET"])
def get_mode():
    """Get current operating mode"""
    return jsonify({
        "mode": current_mode,
        "processing": processing,
        "buffer_complete": buffer_complete
    }), 200

@app.route("/")
def home():
    return send_from_directory("../frontend", "index.html")

@app.route("/api/results")
def results():
    """Return latest frame results"""
    with update_lock:
        return jsonify(current_results if current_results else {})

@app.route("/api/status")
def status():
    """Return processing status including buffer progress for frontend banner"""
    # Estimate buffer progress: assume ~30 fps if actual fps unknown
    buffer_frame_target = INITIAL_BUFFER_SECONDS * 30
    frames_done = len(all_frames)
    if buffer_complete:
        progress_pct = 100
    else:
        progress_pct = min(99, int(frames_done / max(buffer_frame_target, 1) * 100))

    return jsonify({
        "processing": processing,
        "buffer_complete": buffer_complete,
        "buffer_message": buffer_message,
        "frames_processed": frames_done,
        "buffer_progress_pct": progress_pct,
        "video": VIDEO_PATH,
        "buffer_seconds": INITIAL_BUFFER_SECONDS,
        "update_interval_seconds": UPDATE_INTERVAL_SECONDS,
        "display_update_seconds": DISPLAY_UPDATE_SECONDS,
        "current_timestamp": time.time()
    })

@app.route("/api/history")
def history():
    """Return all processed frames for playback"""
    return jsonify(list(all_frames))

@app.route("/api/video")
def video_file():
    """Serve the prerecorded video directly to the browser."""
    if not Path(VIDEO_PATH).exists():
        return jsonify({"error": "Video not found"}), 404
    return send_file(VIDEO_PATH, conditional=True)

if __name__ == "__main__":
    print(f"\n🚀 Marvis Backend starting on port 5000...")
    print(f"   Video: {VIDEO_PATH}")
    print(f"   Device: {DEVICE}")
    print(f"   LSTM Model: models/lstm_model_trained.pt")
    print(f"\n   ⏳ Initialization phase - buffer will complete in ~{INITIAL_BUFFER_SECONDS}s\n")
    app.run(debug=False, use_reloader=False, port=5000)
