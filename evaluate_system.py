"""
evaluate_system.py  — MARVIS System Evaluation (ASCII-safe, CP1252-compatible)
Measures: LSTM latency, ADE/FDE, collision detector, AIS-skip saving, video I/O.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import time, os, math, numpy as np
from pathlib import Path
from collections import deque, Counter

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "lstm"))

SEP = "=" * 70
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

# ================================================================
# 1. ENVIRONMENT
# ================================================================
section("1. ENVIRONMENT")
import torch, cv2
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"  Python  : {sys.version.split()[0]}")
print(f"  PyTorch : {torch.__version__}")
print(f"  OpenCV  : {cv2.__version__}")
print(f"  Device  : {device.upper()}")
print(f"  GPU     : {torch.cuda.get_device_name(0) if device=='cuda' else 'N/A - CPU mode'}")

# ================================================================
# 2. LSTM MODEL LOAD + INFERENCE LATENCY
# ================================================================
section("2. LSTM MODEL LOAD & INFERENCE LATENCY")
MODEL_PATH = str(BASE / "models" / "lstm_model_trained.pt")
SEQ_LEN, PRED_STEPS = 50, 20

from lstm.model import ShipLSTM
model = ShipLSTM(input_size=4, hidden=64, layers=2, predict_steps=PRED_STEPS)
model.load_state_dict(torch.load(MODEL_PATH, map_location=device, weights_only=True))
model.eval().to(device)
params = sum(p.numel() for p in model.parameters())
print(f"  Model  : {MODEL_PATH}")
print(f"  Params : {params:,}")

dummy = torch.randn(1, SEQ_LEN, 4).to(device)
for _ in range(5):                          # warm-up
    with torch.no_grad(): model(dummy)

N_BENCH = 200
times_lstm = []
for _ in range(N_BENCH):
    t0 = time.perf_counter()
    with torch.no_grad(): model(dummy)
    times_lstm.append((time.perf_counter()-t0)*1000)

mean_lstm_ms = float(np.mean(times_lstm))
print(f"\n  LSTM single-call latency ({N_BENCH} iterations):")
print(f"    Mean       : {mean_lstm_ms:.2f} ms")
print(f"    Std        : {float(np.std(times_lstm)):.2f} ms")
print(f"    Min        : {float(np.min(times_lstm)):.2f} ms")
print(f"    Max        : {float(np.max(times_lstm)):.2f} ms")
print(f"    Throughput : {1000/mean_lstm_ms:.1f} inferences/sec")

# ================================================================
# 3. ADE / FDE  (LSTM vs kinematic baseline)
# ================================================================
section("3. TRAJECTORY PREDICTION  ADE / FDE")

from lstm.lstm_predictor import LSTMPredictor

def make_predictor():
    p = LSTMPredictor(predict_steps=PRED_STEPS, seq_len=SEQ_LEN, device=device)
    p.load_model(MODEL_PATH)
    return p

def kinematic_px(hist_norm, steps=20):
    if len(hist_norm) < 5: return []
    recent = hist_norm[-20:]
    xs = [h[0]*1920 for h in recent]
    ys = [h[1]*1080 for h in recent]
    t  = list(range(len(xs)))
    try:
        px = np.polyfit(t, xs, 1)
        py = np.polyfit(t, ys, 1)
    except Exception:
        return []
    n = len(xs)
    return [(float(np.polyval(px,n+i)), float(np.polyval(py,n+i)))
            for i in range(1, steps+1)]

def ade_fde(pred, gt):
    L = min(len(pred), len(gt))
    if L == 0: return None, None
    d = [math.hypot(p[0]-g[0], p[1]-g[1]) for p,g in zip(pred[:L], gt[:L])]
    return float(np.mean(d)), float(d[-1])

# 12 synthetic sine-arc trajectories
np.random.seed(42)
good_tracks = {}
for i in range(12):
    pts = []
    speed = 2.5 + i*0.4
    for t in range(SEQ_LEN + PRED_STEPS + 5):
        x = 200 + t*speed + np.random.normal(0, 1.5)
        y = 300 + 60*math.sin(t*0.10 + i*0.5) + np.random.normal(0, 1.5)
        pts.append((x, y))
    good_tracks[i] = pts

print(f"  Tracks      : {len(good_tracks)}")
print(f"  History     : {SEQ_LEN} steps -> {PRED_STEPS} steps future")

predictor = make_predictor()
lstm_ades, lstm_fdes, kin_ades, kin_fdes, methods = [], [], [], [], []

for tid, pts in good_tracks.items():
    hist   = pts[:SEQ_LEN]
    future = pts[SEQ_LEN:SEQ_LEN+PRED_STEPS]
    for px_, py_ in hist:
        predictor.update(tid, px_, py_)
    lstm_pred, method = predictor.predict(tid)
    methods.append(method)
    hist_norm = list(predictor.gps_history[tid])
    kin_pred  = kinematic_px(hist_norm, PRED_STEPS)

    if lstm_pred:
        a, f = ade_fde(lstm_pred, future)
        if a is not None: lstm_ades.append(a); lstm_fdes.append(f)
    if kin_pred:
        a, f = ade_fde(kin_pred, future)
        if a is not None: kin_ades.append(a);  kin_fdes.append(f)

print(f"  Methods     : {dict(Counter(methods))}")
print(f"\n  {'Method':<32} {'ADE (px)':>10} {'FDE (px)':>10}")
print(f"  {'-'*54}")
if lstm_ades:
    print(f"  {'Bi-directional LSTM':<32} {np.mean(lstm_ades):>10.2f} {np.mean(lstm_fdes):>10.2f}")
if kin_ades:
    print(f"  {'Kinematic Linear Baseline':<32} {np.mean(kin_ades):>10.2f} {np.mean(kin_fdes):>10.2f}")
if lstm_ades and kin_ades:
    ade_imp = (np.mean(kin_ades)-np.mean(lstm_ades))/np.mean(kin_ades)*100
    fde_imp = (np.mean(kin_fdes)-np.mean(lstm_fdes))/np.mean(kin_fdes)*100
    print(f"\n  LSTM improvement over kinematic baseline:")
    print(f"    ADE : {ade_imp:+.1f}%")
    print(f"    FDE : {fde_imp:+.1f}%")

# ================================================================
# 4. COLLISION DETECTOR LATENCY  (raw CPA kernel timing)
# ================================================================
section("4. COLLISION DETECTOR LATENCY")

# Benchmark the CPA computation kernel directly (the core of CollisionDetector)
def cpa_distance(pos1, vel1, pos2, vel2):
    """Closest Point of Approach distance (pixels)."""
    rel_pos = pos2 - pos1
    rel_vel = vel2 - vel1
    denom = float(np.dot(rel_vel, rel_vel))
    if denom < 1e-6:
        return float(np.linalg.norm(rel_pos))
    t_cpa = max(0.0, -float(np.dot(rel_pos, rel_vel)) / denom)
    return float(np.linalg.norm(rel_pos + t_cpa * rel_vel))

def heading_to_vel(heading_deg, speed):
    r = math.radians(heading_deg)
    return np.array([speed*math.cos(r), speed*math.sin(r)])

ship_list = [{"id": i, "center": np.array([300+i*55, 400+i*35], dtype=float),
              "heading": i*36.0, "speed": 2.0+i*0.3} for i in range(10)]
n_pairs = len(ship_list)*(len(ship_list)-1)//2

PIXEL_TO_METER = 0.4
CPA_THRESHOLDS = {"critical": 50, "high": 100, "medium": 200, "low": 500}

col_times = []
for k in range(500):
    t0 = time.perf_counter()
    alerts = []
    for i in range(len(ship_list)):
        for j in range(i+1, len(ship_list)):
            s1, s2 = ship_list[i], ship_list[j]
            v1 = heading_to_vel(s1["heading"], s1["speed"])
            v2 = heading_to_vel(s2["heading"], s2["speed"])
            cpa_px = cpa_distance(s1["center"], v1, s2["center"], v2)
            cpa_m  = cpa_px * PIXEL_TO_METER
            if   cpa_m < 50:  alerts.append(("critical", s1["id"], s2["id"], cpa_m))
            elif cpa_m < 100: alerts.append(("high",     s1["id"], s2["id"], cpa_m))
            elif cpa_m < 200: alerts.append(("medium",   s1["id"], s2["id"], cpa_m))
    col_times.append((time.perf_counter()-t0)*1000)

mean_col = float(np.mean(col_times))
print(f"  Vessels/frame : {len(ship_list)}   Pairs : {n_pairs}   Iterations : 500")
print(f"  Alerts on last frame: {len(alerts)}")
if alerts:
    for level, s1, s2, m in alerts[:3]:
        print(f"    [{level.upper()}] Ship {s1} <-> Ship {s2}  CPA={m:.1f} m")
print(f"\n  {'Metric':<25} {'Value':>12}")
print(f"  {'-'*38}")
print(f"  {'Mean latency':<25} {mean_col:>10.3f} ms")
print(f"  {'Std  latency':<25} {float(np.std(col_times)):>10.3f} ms")
print(f"  {'Min  latency':<25} {float(np.min(col_times)):>10.3f} ms")
print(f"  {'Max  latency':<25} {float(np.max(col_times)):>10.3f} ms")
print(f"  {'Throughput':<25} {1000/mean_col:>10.1f} calls/sec")

# ================================================================
# 5. AIS-SKIP COMPUTE SAVING
# ================================================================
section("5. AIS-MATCHED LSTM SKIP  COMPUTE SAVING")

N_VESSELS, N_SIM = 6, 300
inp = torch.randn(1, SEQ_LEN, 4).to(device)

def bench_n_calls(n, iters):
    ts = []
    for _ in range(iters):
        t0 = time.perf_counter()
        for _ in range(n):
            with torch.no_grad(): model(inp)
        ts.append((time.perf_counter()-t0)*1000)
    return float(np.mean(ts)), float(np.std(ts))

calls_base = N_VESSELS
calls_60   = round(N_VESSELS * 0.40)
calls_80   = max(1, round(N_VESSELS * 0.20))

print(f"  Scenario: {N_VESSELS} vessels/frame, {N_SIM} frames per scenario\n")
m_base, _ = bench_n_calls(calls_base, N_SIM)
m_60,   _ = bench_n_calls(calls_60,   N_SIM)
m_80,   _ = bench_n_calls(calls_80,   N_SIM)

save60 = f"-{(m_base-m_60)/m_base*100:.1f}%"
save80 = f"-{(m_base-m_80)/m_base*100:.1f}%"

print(f"  {'Scenario':<42} {'Calls':>6} {'Avg ms':>9} {'Saving':>9}")
print(f"  {'-'*70}")
print(f"  {'No AIS skip (all 6 vessels run LSTM)':<42} {calls_base:>6} {m_base:>9.2f} {'---':>9}")
print(f"  {'60% AIS match (2 unmatched run LSTM)':<42} {calls_60:>6} {m_60:>9.2f} {save60:>9}")
print(f"  {'80% AIS match (1 unmatched runs LSTM)':<42} {calls_80:>6} {m_80:>9.2f} {save80:>9}")

# ================================================================
# 6. VIDEO I/O & FRAME ENCODE LATENCY
# ================================================================
section("6. VIDEO I/O & FRAME ENCODE LATENCY")

VIDEO_PATH = str(BASE / "data" / "videos" / "input.avi")
cap = cv2.VideoCapture(VIDEO_PATH)
vid_fps = cap.get(cv2.CAP_PROP_FPS)
vid_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
vid_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
vid_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"  File       : {VIDEO_PATH}")
print(f"  FPS        : {vid_fps:.1f}   Frames: {vid_frames}   Resolution: {vid_w}x{vid_h}")

read_t, resize_t, encode_t = [], [], []
for _ in range(100):
    t0 = time.perf_counter(); ret, frame = cap.read()
    if not ret: cap.set(cv2.CAP_PROP_POS_FRAMES,0); ret, frame = cap.read()
    read_t.append((time.perf_counter()-t0)*1000)

    t0 = time.perf_counter(); small = cv2.resize(frame, (960,540))
    resize_t.append((time.perf_counter()-t0)*1000)

    t0 = time.perf_counter(); cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY,75])
    encode_t.append((time.perf_counter()-t0)*1000)
cap.release()

print(f"\n  {'Operation':<32} {'Mean ms':>9} {'Std ms':>9} {'FPS equiv':>10}")
print(f"  {'-'*62}")
print(f"  {'Frame read':<32} {float(np.mean(read_t)):>9.2f} {float(np.std(read_t)):>9.2f} {1000/float(np.mean(read_t)):>10.1f}")
print(f"  {'Resize (1280x720 -> 960x540)':<32} {float(np.mean(resize_t)):>9.2f} {float(np.std(resize_t)):>9.2f} {1000/float(np.mean(resize_t)):>10.1f}")
print(f"  {'JPEG encode (quality=75)':<32} {float(np.mean(encode_t)):>9.2f} {float(np.std(encode_t)):>9.2f} {1000/float(np.mean(encode_t)):>10.1f}")

total_no_yolo = float(np.mean(read_t)) + mean_lstm_ms + mean_col + float(np.mean(resize_t)) + float(np.mean(encode_t))
print(f"\n  Combined pipeline (excl. YOLO) : {total_no_yolo:.2f} ms/frame  -> {1000/total_no_yolo:.1f} FPS")

# ================================================================
# FINAL SUMMARY
# ================================================================
section("FINAL SUMMARY  ALL MEASURED METRICS")

print(f"""
  +---------------------------------------------+--------------------+
  | Metric                                      | Measured Value     |
  +---------------------------------------------+--------------------+
  | Device                                      | {device.upper():<18} |
  | LSTM model parameters                       | {params:<18,} |
  | LSTM mean inference latency                 | {mean_lstm_ms:<14.2f} ms |
  | LSTM throughput                             | {1000/mean_lstm_ms:<13.1f} /sec |
  | LSTM ADE  (12 curved trajectories)          | {float(np.mean(lstm_ades)):<14.2f} px |
  | Kinematic baseline ADE                      | {float(np.mean(kin_ades)):<14.2f} px |
  | ADE improvement (LSTM vs kinematic)         | {ade_imp:<14.1f} %  |
  | LSTM FDE  (12 curved trajectories)          | {float(np.mean(lstm_fdes)):<14.2f} px |
  | Kinematic baseline FDE                      | {float(np.mean(kin_fdes)):<14.2f} px |
  | FDE improvement (LSTM vs kinematic)         | {fde_imp:<14.1f} %  |
  | Collision detector mean latency             | {mean_col:<13.3f} ms  |
  | Collision detector throughput               | {1000/mean_col:<13.1f} /sec |
  | AIS-skip saving at 60% match rate           | {(m_base-m_60)/m_base*100:<14.1f} %  |
  | AIS-skip saving at 80% match rate           | {(m_base-m_80)/m_base*100:<14.1f} %  |
  | Frame read latency                          | {float(np.mean(read_t)):<14.2f} ms |
  | JPEG encode latency                         | {float(np.mean(encode_t)):<14.2f} ms |
  | Pipeline (excl. YOLO)                       | {total_no_yolo:<14.2f} ms |
  +---------------------------------------------+--------------------+
""")

print("Evaluation complete.")
