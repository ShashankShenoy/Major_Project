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
from collections import deque, defaultdict
from io import BytesIO
import torch

app = Flask(__name__, static_folder="../frontend", static_url_path="")

# â”€â”€ CORS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

# â”€â”€ Configuration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
VIDEO_PATH  = os.getenv("VIDEO_PATH", r"C:\Users\91944\MajorProject\data\videos\input.avi")
DEVICE      = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

# Paths mirror phase1.py exactly
UNUSED_DIR   = Path(__file__).resolve().parent.parent.parent / "unused"
MODEL_PATH   = str(UNUSED_DIR / "yolov8m.pt")          # same as phase1.py
REID_WEIGHTS = UNUSED_DIR / "osnet_x0_25_msmt17.pt"    # same as phase1.py
CONFIDENCE   = 0.4                                      # same as phase1.py
CLASSES      = [8]                                      # COCO class 8 = boat

INITIAL_BUFFER_SECONDS = 30
UPDATE_INTERVAL_SECONDS = 30
DISPLAY_UPDATE_SECONDS  = float(os.getenv("DISPLAY_UPDATE_SECONDS", "1.0"))

# LSTM path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "ais_dashboard" / "backend"))

# â”€â”€ Global state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
current_results = {}
all_frames      = deque(maxlen=10000)
processing      = False
buffer_complete = False
buffer_message  = "â³ Building 30-second buffer for LSTM stabilization..."
last_update_time = 0
update_lock     = Lock()
stop_processing = Event()
current_mode    = "hybrid"

# â”€â”€ Motion helpers (from phase1.py) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def smooth_history(hist, window=6):
    pts = list(hist)
    if len(pts) < 3:
        return pts
    smoothed = []
    for i in range(len(pts)):
        chunk = pts[max(0, i - window):i + 1]
        smoothed.append((
            int(np.mean([p[0] for p in chunk])),
            int(np.mean([p[1] for p in chunk]))
        ))
    return smoothed


def compute_heading(pts):
    if len(pts) < 5:
        return 0.0
    recent = list(pts)[-12:]
    disps  = [(recent[i][0] - recent[i-1][0], recent[i][1] - recent[i-1][1])
              for i in range(1, len(recent))]
    if not disps:
        return 0.0
    weights  = np.exp(np.linspace(0, 1, len(disps)))
    weights /= weights.sum()
    avg_dx = sum(d[0] * w for d, w in zip(disps, weights))
    avg_dy = sum(d[1] * w for d, w in zip(disps, weights))
    speed  = np.sqrt(avg_dx**2 + avg_dy**2)
    if speed < 0.4:
        return 0.0
    return round(np.degrees(np.arctan2(avg_dy, avg_dx)) % 360, 1)


def heading_to_dir(h):
    if h == 0.0:
        return "---"
    dirs = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]
    return dirs[round(h / 45) % 8]


def predict_kinematic(pts, steps=20):
    if len(pts) < 10:
        return []
    recent = list(pts)[-20:]
    xs = np.array([p[0] for p in recent], dtype=float)
    ys = np.array([p[1] for p in recent], dtype=float)
    t  = np.arange(len(recent), dtype=float)
    total_dist = np.sqrt((xs[-1] - xs[0])**2 + (ys[-1] - ys[0])**2)
    if total_dist < 5:
        return []
    w = np.exp(np.linspace(0, 2, len(t)))
    try:
        px = np.polyfit(t, xs, 1, w=w)
        py = np.polyfit(t, ys, 1, w=w)
    except Exception:
        return []
    speed        = total_dist / len(recent)
    actual_steps = max(5, min(steps, int(speed * 4)))
    n = len(recent)
    return [[int(np.polyval(px, n + i)), int(np.polyval(py, n + i))]
            for i in range(1, actual_steps + 1)]


# â”€â”€ Load LSTM â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def load_lstm_predictor():
    try:
        from lstm_integration import LSTMEngine
        model_path = str(
            Path(__file__).resolve().parent.parent.parent / "models" / "lstm_model_trained.pt"
        )
        return LSTMEngine(model_path=model_path, device=DEVICE)
    except Exception as e:
        print(f"âš ï¸  LSTM load failed: {e}")
        return None


# â”€â”€ Load YOLO + DeepOcSort (exactly as in phase1.py) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def load_detector_and_tracker():
    try:
        from ultralytics import YOLO
        print(f"   Loading YOLOv8m from: {MODEL_PATH}")
        model = YOLO(MODEL_PATH)
        model.to(DEVICE)
        print(f"   âœ… YOLOv8m loaded on {DEVICE}")
    except Exception as e:
        print(f"   âŒ YOLO load failed: {e}")
        model = None

    try:
        from boxmot import DeepOcSort
        print(f"   Loading DeepOcSort with ReID: {REID_WEIGHTS}")
        tracker = DeepOcSort(
            reid_weights  = REID_WEIGHTS,
            device        = "0" if DEVICE == "cuda" else "cpu",
            half          = (DEVICE == "cuda"),
            det_thresh    = 0.3,
            max_age       = 30,
            min_hits      = 3,
            iou_threshold = 0.3,
        )
        print("   âœ… DeepOcSort tracker loaded")
    except Exception as e:
        print(f"   âŒ DeepOcSort load failed: {e}")
        tracker = None

    return model, tracker


# â”€â”€ Main processing loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def process_video_with_detection():
    """
    Real ship detection using YOLOv8m + DeepOcSort, identical to phase1.py.
    Draws actual bounding boxes from tracker output onto the real video frames.
    """
    global current_results, all_frames, processing, buffer_complete
    global buffer_message, last_update_time, stop_processing

    processing = True
    all_frames.clear()
    current_results = {}
    stop_processing.clear()
    last_update_time = 0

    print(f"\nðŸŽ¬ Starting Real Detection Pipeline (YOLOv8m + DeepOcSort)")
    print(f"   Video  : {VIDEO_PATH}")
    print(f"   Model  : {MODEL_PATH}")
    print(f"   ReID   : {REID_WEIGHTS}")
    print(f"   Device : {DEVICE}")
    print(f"   Conf   : {CONFIDENCE}   Classes: {CLASSES} (boat)")
    print(f"   {'=' * 60}\n")

    if not Path(VIDEO_PATH).exists():
        print(f"âŒ Video not found: {VIDEO_PATH}")
        buffer_message = "âŒ Video not found"
        processing = False
        return

    yolo_model, tracker = load_detector_and_tracker()
    lstm_engine = load_lstm_predictor()

    if yolo_model is None:
        print("âŒ Cannot run without YOLO model.")
        buffer_message = "âŒ YOLO model failed to load"
        processing = False
        return

    # Per-ship track history (same as phase1.py history dict)
    history = defaultdict(lambda: deque(maxlen=90))
    # Persistent predicted paths (updated every UPDATE_INTERVAL_SECONDS)
    persistent_predictions = {}  # sid -> predicted_path list

    try:
        cap = cv2.VideoCapture(VIDEO_PATH)
        if not cap.isOpened():
            print("âŒ Failed to open video")
            buffer_message = "âŒ Failed to open video"
            processing = False
            return

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"   FPS: {fps:.1f}, Total frames: {total_frames}")

        buffer_frames       = min(int(fps * INITIAL_BUFFER_SECONDS), max(total_frames - 1, 1))
        update_frame_interval = int(fps * UPDATE_INTERVAL_SECONDS)

        print(f"   Buffer phase : {buffer_frames} frames (~{INITIAL_BUFFER_SECONDS}s)")
        print(f"   Update every : {update_frame_interval} frames (~{UPDATE_INTERVAL_SECONDS}s)\n")

        frame_count  = 0
        start_time   = time.time()
        buffer_complete = False

        # â”€â”€ Outer replay loop (video loops when it ends) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        while processing and not stop_processing.is_set():

            # Clear history + stale predictions on rewind so tracks don't
            # accumulate stale data across loops
            all_frames.clear()
            history.clear()
            persistent_predictions.clear()
            if tracker is not None:
                try:
                    tracker.reset()
                except Exception:
                    pass  # not all boxmot versions have reset()

            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            inner_frame = 0

            # â”€â”€ Inner per-frame loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            while cap.isOpened() and processing and not stop_processing.is_set():
                ret, frame = cap.read()
                if not ret:
                    break

                # â”€â”€ YOLO detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                try:
                    det_results = yolo_model(
                        frame,
                        conf    = CONFIDENCE,
                        classes = CLASSES,
                        verbose = False
                    )[0]
                    dets = det_results.boxes.data.cpu().numpy()
                except Exception as e:
                    print(f"   âš ï¸  YOLO error frame {frame_count}: {e}")
                    dets = np.empty((0, 6))

                # â”€â”€ DeepOcSort tracking â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                try:
                    if len(dets) > 0:
                        tracks = tracker.update(dets, frame)
                    else:
                        tracks = tracker.update(np.empty((0, 6)), frame)
                except Exception as e:
                    print(f"   âš ï¸  Tracker error frame {frame_count}: {e}")
                    tracks = []

                # â”€â”€ Build ship list from tracker output â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                ships_this_frame = []
                frame_display    = frame.copy()

                for t in (tracks if tracks is not None and len(tracks) > 0 else []):
                    try:
                        x1, y1, x2, y2 = int(t[0]), int(t[1]), int(t[2]), int(t[3])
                        sid             = int(t[4])
                        conf_val        = float(t[5]) if len(t) > 5 else 0.9

                        cx = (x1 + x2) // 2
                        cy = (y1 + y2) // 2
                        history[sid].append((cx, cy))

                        smoothed = smooth_history(history[sid])
                        heading  = compute_heading(smoothed)
                        dirn     = heading_to_dir(heading)

                        # â”€â”€ LSTM / kinematic prediction â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                        if buffer_complete and frame_count % update_frame_interval == 0:
                            if lstm_engine:
                                try:
                                    lstm_engine.update(str(sid), cx, cy)
                                    pred, method = lstm_engine.predict(str(sid))
                                    persistent_predictions[sid] = pred or predict_kinematic(smoothed)
                                except Exception:
                                    persistent_predictions[sid] = predict_kinematic(smoothed)
                            else:
                                persistent_predictions[sid] = predict_kinematic(smoothed)
                        elif not buffer_complete:
                            persistent_predictions[sid] = []

                        predicted_path = persistent_predictions.get(sid, [])

                        # â”€â”€ Draw real bounding box on frame (phase1.py style) â”€â”€
                        color_idx = sid % 10
                        COLORS = [
                            (0, 220, 170), (255, 140, 0), (160, 80, 255),
                            (80, 200, 255), (255, 70, 120), (180, 255, 60),
                            (255, 210, 40), (40, 160, 255), (255, 120, 180),
                            (60, 220, 120),
                        ]
                        color = COLORS[color_idx]

                        # Bounding box
                        cv2.rectangle(frame_display, (x1, y1), (x2, y2), color, 2)

                        # Label
                        label = f"ID:{sid}  {heading:.0f}deg  {dirn}"
                        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                        lx, ly = x1, y1 - 8
                        cv2.rectangle(frame_display, (lx, ly - th - 4), (lx + tw + 6, ly + 2), color, -1)
                        cv2.putText(frame_display, label, (lx + 3, ly - 1),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

                        # Track tail
                        for i in range(1, len(smoothed)):
                            a    = i / len(smoothed)
                            fade = tuple(int(c * a) for c in color)
                            cv2.line(frame_display, smoothed[i - 1], smoothed[i],
                                     fade, max(1, int(2 * a)), cv2.LINE_AA)

                        # Center dot
                        cv2.circle(frame_display, (cx, cy), 4, color, -1)
                        cv2.circle(frame_display, (cx, cy), 4, (255, 255, 255), 1)

                        # Predicted path dots
                        prev = (cx, cy)
                        for pi, pp in enumerate(predicted_path[:20]):
                            px_p, py_p = int(pp[0]), int(pp[1])
                            h_f, w_f   = frame_display.shape[:2]
                            if not (0 <= px_p < w_f and 0 <= py_p < h_f):
                                break
                            alpha  = 1 - (pi / max(len(predicted_path), 1)) * 0.8
                            fade   = tuple(int(c * alpha) for c in color)
                            radius = max(2, int(5 * alpha))
                            if pi % 2 == 0:
                                cv2.line(frame_display, prev, (px_p, py_p), fade, 1, cv2.LINE_AA)
                            cv2.circle(frame_display, (px_p, py_p), radius, fade, -1, cv2.LINE_AA)
                            prev = (px_p, py_p)

                        ships_this_frame.append({
                            "id":               sid,
                            "name":             f"Vessel {sid}",
                            "pos":              [cx, cy],
                            "bbox":             [x1, y1, x2, y2],
                            "track":            [[p[0], p[1]] for p in smoothed[-100:]],
                            "heading":          heading,
                            "direction":        dirn,
                            "sog":              float(np.sqrt(
                                                    (smoothed[-1][0] - smoothed[-2][0])**2 +
                                                    (smoothed[-1][1] - smoothed[-2][1])**2
                                                ) if len(smoothed) >= 2 else 0.0),
                            "confidence":       conf_val,
                            "source":           "LSTM" if buffer_complete else "KINEMATIC",
                            "prediction_method": "LSTM" if buffer_complete else "KINEMATIC",
                            "predicted_path_gps": predicted_path,
                            "center":           [cx, cy],
                            "speed":            float(np.sqrt(
                                                    (smoothed[-1][0] - smoothed[-2][0])**2 +
                                                    (smoothed[-1][1] - smoothed[-2][1])**2
                                                ) if len(smoothed) >= 2 else 0.0),
                            "timestamp":        time.time()
                        })

                    except Exception as e:
                        print(f"   âš ï¸  Track parse error: {e}")
                        continue

                # â”€â”€ HUD bar (same as phase1.py) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                h_f, w_f = frame_display.shape[:2]
                cv2.rectangle(frame_display, (0, 0), (w_f, 32), (15, 18, 22), -1)
                status_txt = (
                    f"Frame: {frame_count:05d}   "
                    f"Vessels: {len(ships_this_frame)}   "
                    f"Model: YOLOv8m   "
                    f"{'LSTM ACTIVE' if buffer_complete else 'BUFFERING...'}"
                )
                cv2.putText(frame_display, status_txt, (8, 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (180, 195, 205), 1, cv2.LINE_AA)

                # â”€â”€ Assemble frame output â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                frame_output = {
                    "frame_number":   frame_count,
                    "timestamp":      time.time(),
                    "ships":          ships_this_frame,
                    "ship_count":     len(ships_this_frame),
                    "collision_alerts": [],
                    "buffer_phase":   not buffer_complete,
                    "prediction_method": "LSTM" if buffer_complete else "KINEMATIC"
                }
                all_frames.append(frame_output)

                # â”€â”€ Encode + broadcast at DISPLAY_UPDATE_SECONDS interval â”€â”€
                current_time = time.time()
                if current_time - last_update_time >= DISPLAY_UPDATE_SECONDS:
                    # Resize for bandwidth
                    disp = frame_display.copy()
                    h_d, w_d = disp.shape[:2]
                    if w_d > 1280 or h_d > 720:
                        scale = min(1280 / w_d, 720 / h_d)
                        disp  = cv2.resize(disp, (int(w_d * scale), int(h_d * scale)))

                    ok, encoded = cv2.imencode(".jpg", disp, [cv2.IMWRITE_JPEG_QUALITY, 82])
                    frame_b64 = base64.b64encode(encoded).decode("utf-8") if ok else None

                    frame_output["video_frame"]      = frame_b64
                    frame_output["frame_timestamp"]  = current_time
                    with update_lock:
                        current_results  = frame_output
                        last_update_time = current_time

                    print(
                        f"   ðŸ“¸ Frame {frame_count} | ships={len(ships_this_frame)} "
                        f"| buf={'done' if buffer_complete else 'wait'}"
                    )

                # â”€â”€ Buffer completion â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                if frame_count >= buffer_frames and not buffer_complete:
                    buffer_complete = True
                    elapsed_buf     = time.time() - start_time
                    buffer_message  = (
                        f"âœ… Buffer complete after {elapsed_buf:.1f}s. "
                        f"LSTM active â€” updating every {UPDATE_INTERVAL_SECONDS}s."
                    )
                    print(f"\nâœ… BUFFER COMPLETE at frame {frame_count} ({elapsed_buf:.1f}s)")
                    print(f"   LSTM predictions now active.\n")

                frame_count  += 1
                inner_frame  += 1

                if inner_frame % 150 == 0:
                    elapsed  = time.time() - start_time
                    fps_a    = frame_count / elapsed if elapsed > 0 else 0
                    phase    = "ðŸ”„ BUFFER" if not buffer_complete else "ðŸ“Š ACTIVE"
                    print(f"   [{phase}] frame={frame_count} inner={inner_frame}/{total_frames} ({fps_a:.1f} fps)")

            # Inner loop ended
            if not buffer_complete:
                buffer_complete = True
                buffer_message  = (
                    f"âœ… Short video ({inner_frame} frames). LSTM active. Looping."
                )
                print("âœ… Video ended before buffer filled â€” marking complete. Rewinding.")
            else:
                print(f"ðŸ” Loop done at frame {inner_frame}. Rewinding.")

        cap.release()
        print("ðŸ›‘ Outer replay loop exited.")

    except Exception as e:
        print(f"âŒ Processing error: {e}")
        buffer_message = f"âŒ Processing error: {e}"
        import traceback
        traceback.print_exc()
    finally:
        processing = False
        stop_processing.clear()


# â”€â”€ Start background thread â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
processor_thread = Thread(target=process_video_with_detection, daemon=True)
processor_thread.start()

# â”€â”€ Routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/mode", methods=["POST"])
def set_mode():
    global current_mode, stop_processing, processor_thread
    mode = request.json.get("mode", "hybrid")
    if mode == current_mode:
        return jsonify({"success": False, "message": f"Already in {mode} mode"}), 400
    if processing:
        stop_processing.set()
        for _ in range(50):
            if not processing:
                break
            time.sleep(0.1)
    current_mode = mode
    if mode == "hybrid":
        processor_thread = Thread(target=process_video_with_detection, daemon=True)
        processor_thread.start()
        return jsonify({"success": True, "message": "Switched to Hybrid mode", "mode": mode}), 200
    elif mode == "ais-only":
        return jsonify({"success": True, "message": "Switched to AIS-Only mode", "mode": mode}), 200
    return jsonify({"success": False, "message": f"Unknown mode: {mode}"}), 400


@app.route("/api/mode", methods=["GET"])
def get_mode():
    return jsonify({"mode": current_mode, "processing": processing, "buffer_complete": buffer_complete}), 200


@app.route("/")
def home():
    return send_from_directory("../frontend", "index.html")


@app.route("/api/results")
def results():
    with update_lock:
        return jsonify(current_results if current_results else {})


@app.route("/api/status")
def status():
    buffer_frame_target = INITIAL_BUFFER_SECONDS * 30
    frames_done = len(all_frames)
    if buffer_complete:
        progress_pct = 100
    else:
        progress_pct = min(99, int(frames_done / max(buffer_frame_target, 1) * 100))
    return jsonify({
        "processing":             processing,
        "buffer_complete":        buffer_complete,
        "buffer_message":         buffer_message,
        "frames_processed":       frames_done,
        "buffer_progress_pct":    progress_pct,
        "video":                  VIDEO_PATH,
        "buffer_seconds":         INITIAL_BUFFER_SECONDS,
        "update_interval_seconds": UPDATE_INTERVAL_SECONDS,
        "display_update_seconds": DISPLAY_UPDATE_SECONDS,
        "current_timestamp":      time.time()
    })


@app.route("/api/history")
def history():
    return jsonify(list(all_frames))


@app.route("/api/video")
def video_file():
    if not Path(VIDEO_PATH).exists():
        return jsonify({"error": "Video not found"}), 404
    return send_file(VIDEO_PATH, conditional=True)


if __name__ == "__main__":
    print(f"\n[START] Marvis Backend starting on port 5000...")
    print(f"   Video  : {VIDEO_PATH}")
    print(f"   YOLO   : {MODEL_PATH}")
    print(f"   ReID   : {REID_WEIGHTS}")
    print(f"   Device : {DEVICE}")
    print(f"\n   [WAIT] Initializing - buffer completes in ~{INITIAL_BUFFER_SECONDS}s\n")
    app.run(debug=False, use_reloader=False, port=5000)
