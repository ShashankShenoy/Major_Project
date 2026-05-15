# phase1.py
# Phase 1 — Ship detection, tracking, ID assignment and path prediction
# Run: python phase1.py data/videos/input.mp4

import os
os.environ['CUDA_VISIBLE_DEVICES'] = '0'

import sys
import cv2
import time
import torch
import numpy as np
from pathlib import Path
from collections import defaultdict, deque
from ultralytics import YOLO
from boxmot import DeepOcSort

# ── Config ────────────────────────────────────────────────────────────────────
MODEL_PATH   = "yolov8m.pt"
CONFIDENCE   = 0.4
DEVICE       = "cuda" if torch.cuda.is_available() else "cpu"
TRACK_LEN    = 90
REID_WEIGHTS = Path("osnet_x0_25_msmt17.pt")
PREDICT_STEPS = 20

COLORS = [
    (  0, 220, 170), (255, 140,   0), (160,  80, 255),
    ( 80, 200, 255), (255,  70, 120), (180, 255,  60),
    (255, 210,  40), ( 40, 160, 255), (255, 120, 180),
    ( 60, 220, 120),
]

def get_color(sid):
    return COLORS[int(sid) % len(COLORS)]

# ── Load model + tracker ──────────────────────────────────────────────────────
print(f"Device : {torch.cuda.get_device_name(0) if DEVICE=='cuda' else 'CPU'}")
print("Loading model...")
model = YOLO(MODEL_PATH)
model.to(DEVICE)

print("Loading tracker...")
tracker = DeepOcSort(
    reid_weights  = REID_WEIGHTS,
    device        = "0" if DEVICE == "cuda" else "cpu",
    half          = DEVICE == "cuda",
    det_thresh    = 0.3,
    max_age       = 30,
    min_hits      = 3,
    iou_threshold = 0.3,
)

# Track history per ship ID
history = defaultdict(lambda: deque(maxlen=TRACK_LEN))

# ── Motion helpers ────────────────────────────────────────────────────────────
def smooth_history(hist, window=6):
    """
    Moving average over track positions to remove camera/detection jitter.
    """
    pts = list(hist)
    if len(pts) < 3:
        return pts
    smoothed = []
    for i in range(len(pts)):
        chunk = pts[max(0, i-window):i+1]
        smoothed.append((
            int(np.mean([p[0] for p in chunk])),
            int(np.mean([p[1] for p in chunk]))
        ))
    return smoothed


def compute_heading(pts):
    """
    Stable heading from exponentially weighted displacement vectors.
    Returns 0.0 if ship is stationary.
    """
    if len(pts) < 5:
        return 0.0

    recent = list(pts)[-12:]
    disps  = [
        (recent[i][0] - recent[i-1][0],
         recent[i][1] - recent[i-1][1])
        for i in range(1, len(recent))
    ]

    if not disps:
        return 0.0

    weights  = np.exp(np.linspace(0, 1, len(disps)))
    weights /= weights.sum()

    avg_dx = sum(d[0]*w for d, w in zip(disps, weights))
    avg_dy = sum(d[1]*w for d, w in zip(disps, weights))

    speed = np.sqrt(avg_dx**2 + avg_dy**2)
    if speed < 0.4:
        return 0.0

    return round(np.degrees(np.arctan2(avg_dy, avg_dx)) % 360, 1)


def heading_to_dir(h):
    if h == 0.0:
        return "---"
    return ['E','NE','N','NW','W','SW','S','SE'][round(h/45) % 8]


def predict_path(pts, steps=PREDICT_STEPS):
    """
    Stable kinematic path prediction:
    - Requires minimum movement before drawing anything
    - Linear weighted fit (less overfitting than quadratic)
    - Scales prediction length to ship speed
    """
    if len(pts) < 10:
        return []

    recent = list(pts)[-20:]
    xs = np.array([p[0] for p in recent], dtype=float)
    ys = np.array([p[1] for p in recent], dtype=float)
    t  = np.arange(len(recent), dtype=float)

    # Stationary check — no prediction if barely moving
    total_dist = np.sqrt((xs[-1]-xs[0])**2 + (ys[-1]-ys[0])**2)
    if total_dist < 5:
        return []

    # Exponential weights — recent positions matter more
    w = np.exp(np.linspace(0, 2, len(t)))

    try:
        px = np.polyfit(t, xs, 1, w=w)
        py = np.polyfit(t, ys, 1, w=w)
    except Exception:
        return []

    # Scale step count to speed
    speed        = total_dist / len(recent)
    actual_steps = max(5, min(steps, int(speed * 4)))

    n = len(recent)
    return [
        (int(np.polyval(px, n+i)),
         int(np.polyval(py, n+i)))
        for i in range(1, actual_steps+1)
    ]


# ── Annotation ────────────────────────────────────────────────────────────────
def annotate(frame, tracks, frame_num, fps):
    fh, fw = frame.shape[:2]

    for t in tracks:
        x1, y1, x2, y2 = int(t[0]), int(t[1]), int(t[2]), int(t[3])
        sid             = int(t[4])
        cls             = int(t[6])
        color           = get_color(sid)

        cx = (x1+x2)//2
        cy = (y1+y2)//2
        history[sid].append((cx, cy))

        # Smooth positions before any computation
        smoothed = smooth_history(history[sid])
        heading  = compute_heading(smoothed)
        dirn     = heading_to_dir(heading)
        cls_name = model.names.get(cls, "vessel").upper()

        # ── Bounding box ──────────────────────────────────────────────────
        cv2.rectangle(frame, (x1,y1), (x2,y2), color, 2)

        # ── Label ─────────────────────────────────────────────────────────
        label     = f"ID:{sid}  {cls_name}  {heading:.0f}deg  {dirn}"
        (tw, th), _ = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 1)
        lx, ly = x1, y1 - 8
        # pill background
        cv2.rectangle(frame,
                      (lx, ly-th-6), (lx+tw+8, ly+2),
                      color, -1)
        cv2.putText(frame, label, (lx+4, ly-2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50,
                    (0, 0, 0), 1, cv2.LINE_AA)

        # ── Track tail ────────────────────────────────────────────────────
        for i in range(1, len(smoothed)):
            a    = i / len(smoothed)
            fade = tuple(int(c*a) for c in color)
            cv2.line(frame,
                     smoothed[i-1], smoothed[i],
                     fade, max(1, int(2*a)), cv2.LINE_AA)

        # ── Center dot ────────────────────────────────────────────────────
        cv2.circle(frame, (cx,cy), 4, color,        -1)
        cv2.circle(frame, (cx,cy), 4, (255,255,255),  1)

        # ── Direction arrow ───────────────────────────────────────────────
        if heading > 0:
            ex = int(cx + 45 * np.cos(np.radians(heading)))
            ey = int(cy + 45 * np.sin(np.radians(heading)))
            if 0<=ex<fw and 0<=ey<fh:
                cv2.arrowedLine(frame, (cx,cy), (ex,ey),
                                color, 2, cv2.LINE_AA,
                                tipLength=0.35)

        # ── Predicted path ────────────────────────────────────────────────
        predicted = predict_path(smoothed)
        prev      = (cx, cy)

        for i, (px, py) in enumerate(predicted):
            # Bounds check
            if not (0<=px<fw and 0<=py<fh):
                break

            alpha  = 1 - (i / len(predicted)) * 0.8
            fade   = tuple(int(c*alpha) for c in color)
            radius = max(2, int(5*alpha))

            # Dashed line every other segment
            if i % 2 == 0:
                cv2.line(frame, prev, (px,py),
                         fade, 1, cv2.LINE_AA)

            # Dot with subtle white outline
            cv2.circle(frame, (px,py), radius, fade,        -1, cv2.LINE_AA)
            cv2.circle(frame, (px,py), radius, (200,210,218), 1, cv2.LINE_AA)
            prev = (px, py)

        # Arrow at end of predicted path
        if len(predicted) >= 2:
            cv2.arrowedLine(frame,
                            predicted[-2], predicted[-1],
                            color, 2, cv2.LINE_AA,
                            tipLength=0.5)

    # ── HUD bar ───────────────────────────────────────────────────────────────
    cv2.rectangle(frame, (0,0), (fw, 36), (15,18,22), -1)
    cv2.putText(frame,
                f"Frame: {frame_num:05d}   "
                f"Vessels: {len(tracks)}   "
                f"FPS: {fps:.1f}   "
                f"[Q] quit   [SPACE] pause",
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52,
                (180, 195, 205), 1, cv2.LINE_AA)
    return frame


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "data/videos/input.mp4"
    cap = cv2.VideoCapture(src)

    if not cap.isOpened():
        print(f"Cannot open: {src}")
        return

    W     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps_v = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video : {W}x{H}  {fps_v:.1f}fps  {total} frames")
    print("Controls: Q = quit   SPACE = pause")
    print("-" * 40)

    cv2.namedWindow("Phase 1 — Ship Detection & Tracking",
                    cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Phase 1 — Ship Detection & Tracking",
                     min(W, 1280), min(H, 720))

    frame_num = 0
    fps_disp  = 0.0
    fps_t     = time.time()
    fps_f     = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame_num += 1
        fps_f     += 1
        now = time.time()
        if now - fps_t >= 1.0:
            fps_disp = fps_f / (now - fps_t)
            fps_f    = 0
            fps_t    = now

        print(f"  Frame {frame_num}/{total}  |  "
              f"Vessels: {len(history)}  |  "
              f"FPS: {fps_disp:.1f}",
              end="\r")

        # Detect — class 8 = boat in COCO
        results = model(
            frame,
            conf    = CONFIDENCE,
            classes = [8],
            verbose = False
        )[0]
        dets = results.boxes.data.cpu().numpy()

        # Track
        if len(dets) > 0:
            tracks = tracker.update(dets, frame)
        else:
            tracks = tracker.update(
                np.empty((0, 6)), frame)

        # Annotate + display
        frame = annotate(frame, tracks, frame_num, fps_disp)
        cv2.imshow("Phase 1 — Ship Detection & Tracking", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            print("\nStopped by user.")
            break
        elif key == ord(' '):
            print("\nPaused — press SPACE to continue")
            while cv2.waitKey(0) & 0xFF != ord(' '):
                pass

    cap.release()
    cv2.destroyAllWindows()
    print(f"\nDone — {frame_num} frames processed.")


if __name__ == "__main__":
    main()