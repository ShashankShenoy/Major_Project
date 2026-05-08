print("Starting LSTM training script...")

import torch
from torch.utils.data import DataLoader
from lstm.model import ShipLSTM
from lstm.dataset import TrajectoryDataset
import numpy as np
from pathlib import Path
from scipy import io


# -----------------------
# PATH SETUP (VERY IMPORTANT)
# -----------------------
BASE_DIR = Path(__file__).resolve().parent.parent
SMD_PATH = BASE_DIR / "SMD_ROOT"

MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)

MODEL_PATH = MODEL_DIR / "lstm_model_trained.pt"


# -----------------------
# CONFIG (FIXED)
# -----------------------
SEQ_LEN = 50
PRED_LEN = 20
BATCH_SIZE = 32
EPOCHS = 20
LR = 0.0005

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# -----------------------
# LOAD SMD TRAJECTORIES
# -----------------------
def load_smd_trajectories(smd_root):
    trajectories = []

    files = list(Path(smd_root).rglob("*TrackGT*.mat"))
    print("Found TrackGT files:", len(files))

    for file in files:
        try:
            data = io.loadmat(file)
            tracks = np.array(data.get('Track', [])).squeeze()

            for track in tracks:
                try:
                    trajectory = None

                    # -------- MATLAB STRUCT --------
                    if hasattr(track, 'dtype') and track.dtype.names:
                        if 'Motion' in track.dtype.names and 'BB' in track.dtype.names:
                            motion = track['Motion']
                            bb = track['BB']

                            if hasattr(motion, 'shape') and hasattr(bb, 'shape'):
                                if motion.shape[0] == 1 and bb.shape[1] == 4:
                                    motion_flat = motion.flatten()
                                    centers = []

                                    for i in range(len(motion_flat)):
                                        if motion_flat[i] > 0:
                                            bbox = bb[i]
                                            if len(bbox) >= 4:
                                                x_center = (bbox[0] + bbox[2]) / 2
                                                y_center = (bbox[1] + bbox[3]) / 2
                                                centers.append([x_center, y_center])

                                    if centers:
                                        trajectory = centers

                    # -------- SAVE VALID --------
                    if trajectory is not None and len(trajectory) > 50:
                        trajectories.append(trajectory)

                except:
                    continue

        except Exception as e:
            print("Error reading:", file, e)

    print("Total trajectories loaded:", len(trajectories))
    return trajectories


# -----------------------
# MAIN TRAINING
# -----------------------
if __name__ == "__main__":

    print("Using SMD path:", SMD_PATH)

    trajectories = load_smd_trajectories(str(SMD_PATH))

    dataset = TrajectoryDataset(trajectories, SEQ_LEN, PRED_LEN)
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

    print("Dataset size:", len(dataset))

    # -----------------------
    # MODEL
    # -----------------------
    model = ShipLSTM(predict_steps=PRED_LEN).to(DEVICE)

    criterion = torch.nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    # -----------------------
    # TRAIN LOOP
    # -----------------------
    try:
        for epoch in range(EPOCHS):
            model.train()
            total_loss = 0
            batch_count = 0

            for X, Y in loader:
                X, Y = X.to(DEVICE), Y.to(DEVICE)

                pred = model(X)
                # -----------------------
                # POSITION LOSS (L2)
                # -----------------------
                pos_loss = criterion(pred, Y)

                # -----------------------
                # VELOCITY LOSS (smoothness)
                # Penalizes jerky predictions
                # -----------------------
                pred_vel = pred[:, 1:, :] - pred[:, :-1, :]
                gt_vel   = Y[:, 1:, :] - Y[:, :-1, :]
                vel_loss = criterion(pred_vel, gt_vel)
                
                # -----------------------
                # ACCELERATION LOSS (smoothness)
                # Penalizes sudden changes in velocity
                # -----------------------
                pred_accel = pred_vel[:, 1:, :] - pred_vel[:, :-1, :]
                gt_accel   = gt_vel[:, 1:, :] - gt_vel[:, :-1, :]
                accel_loss = criterion(pred_accel, gt_accel)

                # -----------------------
                # TOTAL LOSS (weighted)
                # -----------------------
                loss = pos_loss + 0.3 * vel_loss + 0.1 * accel_loss

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                total_loss += loss.item()
                batch_count += 1

                if batch_count % 100 == 0:
                    print(f"Epoch {epoch+1}, Batch {batch_count}/{len(loader)}, Loss: {loss.item():.6f} (pos={pos_loss.item():.6f}, vel={vel_loss.item():.6f}, accel={accel_loss.item():.6f})")

            avg_loss = total_loss / len(loader)
            print(f"Epoch {epoch+1}/{EPOCHS}, Avg Loss: {avg_loss:.6f}")

            # 🔥 SAVE MODEL (FIXED)
            torch.save(model.state_dict(), str(MODEL_PATH))
            print(f"✅ Model saved at {MODEL_PATH}")

    except KeyboardInterrupt:
        print("\n⚠️ Training interrupted! Saving current model...")
        torch.save(model.state_dict(), str(MODEL_PATH))

    except Exception as e:
        print(f"\n❌ Training error: {e}")
        torch.save(model.state_dict(), str(MODEL_PATH))

    print("🎉 Training completed!")