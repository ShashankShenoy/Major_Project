print("Starting LSTM training script...")

import torch
from torch.utils.data import DataLoader
from lstm.model import ShipLSTM
from lstm.dataset import TrajectoryDataset
import numpy as np
from pathlib import Path
from scipy import io
import ctypes
import sys


# -----------------------
# PREVENT WINDOWS SLEEP
# -----------------------
def prevent_sleep():
    """Prevent Windows system from sleeping during training."""
    try:
        if sys.platform == "win32":
            # ES_CONTINUOUS = 0x80000000
            # ES_SYSTEM_REQUIRED = 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(
                0x80000001  # Continuous + System Required
            )
            print("✅ Windows sleep prevented")
    except Exception as e:
        print(f"⚠️ Could not prevent sleep: {e}")


def allow_sleep():
    """Allow Windows system to sleep again."""
    try:
        if sys.platform == "win32":
            # ES_CONTINUOUS = 0x80000000
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            print("✅ Windows sleep re-enabled")
    except Exception as e:
        print(f"⚠️ Could not re-enable sleep: {e}")


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
EPOCHS = 100
LR = 0.001


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

    prevent_sleep()  # 🔥 Prevent system sleep during training

    print("Using SMD path:", SMD_PATH)

    trajectories = load_smd_trajectories(str(SMD_PATH))

    dataset = TrajectoryDataset(trajectories, SEQ_LEN, PRED_LEN)
    
    # -----------------------
    # TRAIN/VAL SPLIT (80/20)
    # -----------------------
    train_size = int(0.8 * len(dataset))
    val_size = len(dataset) - train_size
    train_dataset, val_dataset = torch.utils.data.random_split(
        dataset, 
        [train_size, val_size],
        generator=torch.Generator().manual_seed(42)  # reproducible split
    )
    
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False)

    print(f"Dataset size: {len(dataset)} → Train: {len(train_dataset)}, Val: {len(val_dataset)}")

    # -----------------------
    # MODEL
    # -----------------------
    model = ShipLSTM(predict_steps=PRED_LEN).to(DEVICE)

    criterion = torch.nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    # -----------------------
    # EARLY STOPPING
    # -----------------------
    best_val_loss = float('inf')
    patience = 10  # stop if validation loss doesn't improve for 10 epochs
    patience_counter = 0

    # -----------------------
    # TRAIN LOOP
    # -----------------------
    try:
        for epoch in range(EPOCHS):
            model.train()
            total_loss = 0
            batch_count = 0

            for X, Y in train_loader:
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
                # Increased smoothness constraints: vel(0.4) + accel(0.2)
                # -----------------------
                loss = pos_loss + 0.4 * vel_loss + 0.2 * accel_loss

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                total_loss += loss.item()
                batch_count += 1

                if batch_count % 100 == 0:
                    print(f"Epoch {epoch+1}, Batch {batch_count}/{len(train_loader)}, Loss: {loss.item():.6f} (pos={pos_loss.item():.6f}, vel={vel_loss.item():.6f}, accel={accel_loss.item():.6f})")

            avg_train_loss = total_loss / len(train_loader)
            
            # -----------------------
            # VALIDATION PHASE
            # -----------------------
            model.eval()
            val_loss = 0
            val_batch_count = 0
            
            with torch.no_grad():
                for X_val, Y_val in val_loader:
                    X_val, Y_val = X_val.to(DEVICE), Y_val.to(DEVICE)
                    
                    pred_val = model(X_val)
                    
                    pos_loss_val = criterion(pred_val, Y_val)
                    pred_vel_val = pred_val[:, 1:, :] - pred_val[:, :-1, :]
                    gt_vel_val = Y_val[:, 1:, :] - Y_val[:, :-1, :]
                    vel_loss_val = criterion(pred_vel_val, gt_vel_val)
                    
                    pred_accel_val = pred_vel_val[:, 1:, :] - pred_vel_val[:, :-1, :]
                    gt_accel_val = gt_vel_val[:, 1:, :] - gt_vel_val[:, :-1, :]
                    accel_loss_val = criterion(pred_accel_val, gt_accel_val)
                    
                    loss_val = pos_loss_val + 0.4 * vel_loss_val + 0.2 * accel_loss_val
                    val_loss += loss_val.item()
                    val_batch_count += 1
            
            avg_val_loss = val_loss / len(val_loader)
            
            # -----------------------
            # EARLY STOPPING CHECK
            # -----------------------
            print(f"Epoch {epoch+1}/{EPOCHS}, Train Loss: {avg_train_loss:.6f}, Val Loss: {avg_val_loss:.6f}")
            
            if avg_val_loss < best_val_loss:
                best_val_loss = avg_val_loss
                patience_counter = 0
                torch.save(model.state_dict(), str(MODEL_PATH))
                print(f"✅ Model improved and saved at {MODEL_PATH}")
            else:
                patience_counter += 1
                print(f"⚠️ No improvement ({patience_counter}/{patience})")
                
                if patience_counter >= patience:
                    print(f"🛑 Early stopping at epoch {epoch+1} (validation loss plateaued)")
                    break

    except KeyboardInterrupt:
        print("\n⚠️ Training interrupted! Saving current model...")
        torch.save(model.state_dict(), str(MODEL_PATH))
        allow_sleep()  # 🔥 Re-enable system sleep

    except Exception as e:
        print(f"\n❌ Training error: {e}")
        torch.save(model.state_dict(), str(MODEL_PATH))
        allow_sleep()  # 🔥 Re-enable system sleep

    print("🎉 Training completed!")
    allow_sleep()  # 🔥 Re-enable system sleep after training
