import numpy as np
import torch
from pathlib import Path
from scipy import io
from lstm.lstm_predictor import LSTMPredictor
from utils.config import CONFIG


# -------------------------------
# LOAD SMD GROUND TRUTH (FIXED)
# -------------------------------
def load_smd_ground_truth(smd_root, video_name):
    smd_path = Path(smd_root)

    # Find TrackGT file
    # Step 1: get all TrackGT files
    track_files = list(smd_path.rglob("*TrackGT*.mat"))

    print("Found TrackGT files:", len(track_files))

    # Step 2: filter if video_name is given
    if video_name:
        track_files = [f for f in track_files if video_name in f.name]

    if not track_files:
        track_files = list(smd_path.rglob("*TrackGT*.mat"))

    if not track_files:
        print(f"No TrackGT file found in {smd_path}")
        return {}

    track_file = track_files[0]
    print(f"Loading ground truth from: {track_file}")

    try:
        data = io.loadmat(str(track_file))
        tracks = data.get('Track', [])

        print("Track type:", type(tracks))

        trajectories = {}

        # Flatten Track if needed
        if isinstance(tracks, np.ndarray):
            tracks = tracks.flatten()

        print("Total tracks:", len(tracks))

        for i, track in enumerate(tracks):
            try:
                # -------- CASE 1: MATLAB STRUCT --------
                if hasattr(track, 'dtype') and track.dtype.names:
                    # Try to extract trajectory from BB using Motion as mask
                    trajectory = None
                    if 'Motion' in track.dtype.names and 'BB' in track.dtype.names:
                        motion = track['Motion']
                        bb = track['BB']
                        
                        if hasattr(motion, 'shape') and hasattr(bb, 'shape'):
                            # Motion is (1, num_frames), BB is (num_frames, 4)
                            if motion.shape[0] == 1 and bb.shape[1] == 4:
                                motion_flat = motion.flatten()
                                centers = []
                                for i in range(len(motion_flat)):
                                    if motion_flat[i] > 0:  # Object present in this frame
                                        bbox = bb[i]  # [x1, y1, x2, y2]
                                        if len(bbox) >= 4:
                                            x_center = (bbox[0] + bbox[2]) / 2
                                            y_center = (bbox[1] + bbox[3]) / 2
                                            centers.append([x_center, y_center])
                                
                                if centers:
                                    trajectory = centers
                    
                    if trajectory and len(trajectory) > 5:
                        trajectories[i] = trajectory

                # -------- CASE 2: NUMERIC ARRAY --------
                else:
                    track_arr = np.array(track)
                    if track_arr.ndim == 2 and track_arr.shape[1] >= 4:
                        coords = track_arr[:, 2:4]
                        trajectories[i] = coords.tolist()

            except Exception as e:
                continue

        print(f"Loaded {len(trajectories)} ship trajectories")
        return trajectories

    except Exception as e:
        print(f"Error loading {track_file}: {e}")
        return {}


# -------------------------------
# METRICS
# -------------------------------
def compute_ade_fde(predicted, ground_truth):
    if len(predicted) == 0 or len(ground_truth) == 0:
        return float('inf'), float('inf')

    min_len = min(len(predicted), len(ground_truth))
    predicted = predicted[:min_len]
    ground_truth = ground_truth[:min_len]

    displacements = []
    for pred, gt in zip(predicted, ground_truth):
        dist = np.sqrt((pred[0] - gt[0])**2 + (pred[1] - gt[1])**2)
        displacements.append(dist)

    ade = np.mean(displacements)
    fde = displacements[-1]

    return ade, fde


# -------------------------------
# BASELINE
# -------------------------------
def kinematic_predict(history, steps=20):
    if len(history) < 3:
        return []

    recent = history[-10:]
    xs = [h[0] for h in recent]
    ys = [h[1] for h in recent]
    t = list(range(len(recent)))

    try:
        px = np.polyfit(t, xs, 1)
        py = np.polyfit(t, ys, 1)
    except:
        return []

    n = len(recent)
    predicted = []

    for i in range(1, steps + 1):
        predicted.append((
            float(np.polyval(px, n + i)),
            float(np.polyval(py, n + i))
        ))

    return predicted


# -------------------------------
# EVALUATION
# -------------------------------
def evaluate_predictions(smd_root, video_name, model_path="models\\lstm_model_trained.pt"):
    print("=" * 60)
    print("LSTM Prediction Evaluation (ADE/FDE)")
    print("=" * 60)

    gt_trajectories = load_smd_ground_truth(smd_root, video_name)

    if not gt_trajectories:
        print("No ground truth data found. Exiting.")
        return

    predictor = LSTMPredictor(
        predict_steps=CONFIG["predict_steps"],
        device=CONFIG["device"]
    )
    predictor.load_model(model_path)

    lstm_ades = []
    lstm_fdes = []
    kin_ades = []
    kin_fdes = []

    print("\nEvaluating trajectories...\n")

    for ship_id, positions in gt_trajectories.items():

        predictor.gps_history = {}  # 🔥 reset per ship

        if len(positions) < 40:
            continue

        history_len = 30
        history = positions[:history_len]
        future_gt = positions[history_len:history_len + CONFIG["predict_steps"]]

        if len(future_gt) < 5:
            continue

        # -------- LSTM INPUT --------
        for i in range(len(history)):
            x, y = history[i]

            if i >= 1:
                x_prev, y_prev = history[i-1]
                vx = x - x_prev
                vy = y - y_prev
            else:
                vx, vy = 0, 0

            predictor.update(ship_id, x, y)

                # -------- PREDICTIONS --------
        lstm_pred, lstm_method = predictor.predict(ship_id)
        kin_pred = kinematic_predict(history, CONFIG["predict_steps"])

        # -------- DECISION --------
       
        if lstm_pred and kin_pred:
            lstm_ade, _ = compute_ade_fde(lstm_pred, future_gt)
            kin_ade, _ = compute_ade_fde(kin_pred, future_gt)

            if lstm_ade <= kin_ade:
                final_pred = lstm_pred
                model_used = "LSTM"
            else:
                final_pred = kin_pred
                model_used = "FALLBACK (Better Kinematic)"
        else:
            final_pred = kin_pred
            model_used = "FALLBACK (LSTM Failed)"

         # -------- DEBUG INFO --------
        print(f"\n--- DEBUG INFO ---")
        print(f"Ship ID: {ship_id}")
        print(f"History length: {len(history)}")

        print(f"LSTM method: {lstm_method}")
        print(f"LSTM predicted steps: {len(lstm_pred) if lstm_pred else 0}")
        print(f"Kinematic predicted steps: {len(kin_pred) if kin_pred else 0}")

        print(f"Model used: {model_used}")

        # trajectory preview
        print(f"LSTM first future point: {lstm_pred[0] if lstm_pred else None}")
        print(f"KIN first future point: {kin_pred[0] if kin_pred else None}")   

        # -------- METRICS --------
        final_ade, final_fde = compute_ade_fde(final_pred, future_gt)

        # store separately if you still want comparison
        if lstm_pred:
            lstm_ade, lstm_fde = compute_ade_fde(lstm_pred, future_gt)
            lstm_ades.append(lstm_ade)
            lstm_fdes.append(lstm_fde)

        if kin_pred:
            kin_ade, kin_fde = compute_ade_fde(kin_pred, future_gt)
            kin_ades.append(kin_ade)
            kin_fdes.append(kin_fde)

        # -------- PRINT --------
        print(f"Ship {ship_id}: USED -> {model_used} | ADE={final_ade:.2f}, FDE={final_fde:.2f}")
   
    # -------- SUMMARY --------
    if lstm_ades:
        print("\nLSTM Results:")
        print(f"Mean ADE: {np.mean(lstm_ades):.3f} ± {np.std(lstm_ades):.3f}")
        print(f"Mean FDE: {np.mean(lstm_fdes):.3f} ± {np.std(lstm_fdes):.3f}")

    if kin_ades:
        print("\nKinematic Baseline:")
        print(f"Mean ADE: {np.mean(kin_ades):.3f} ± {np.std(kin_ades):.3f}")
        print(f"Mean FDE: {np.mean(kin_fdes):.3f} ± {np.std(kin_fdes):.3f}")

    if lstm_ades and kin_ades:
        ade_imp = (np.mean(kin_ades) - np.mean(lstm_ades)) / np.mean(kin_ades) * 100
        fde_imp = (np.mean(kin_fdes) - np.mean(lstm_fdes)) / np.mean(kin_fdes) * 100

        print("\nImprovement over baseline:")
        print(f"ADE improvement: {ade_imp:+.2f}%")
        print(f"FDE improvement: {fde_imp:+.2f}%")


# -------------------------------
# MAIN
# -------------------------------
if __name__ == "__main__":
    smd_root = r"C:\Desktop\Major_Project-main\SMD_ROOT"
    video_name = ""

    evaluate_predictions(smd_root, video_name)