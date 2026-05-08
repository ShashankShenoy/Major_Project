import numpy as np
import torch
from torch.utils.data import Dataset


class TrajectoryDataset(Dataset):
    def __init__(self, trajectories, seq_len=30, pred_len=20):
        self.X = []
        self.Y = []

        for traj in trajectories:
            if len(traj) < seq_len + pred_len:
                continue

            for i in range(len(traj) - (seq_len + pred_len)):
                history = traj[i:i+seq_len]
                future  = traj[i+seq_len:i+seq_len+pred_len]

                history = np.array(history, dtype=np.float32)
                future  = np.array(future, dtype=np.float32)

                # -------------------------------
                # 🔥 NORMALIZATION (VERY IMPORTANT)
                # -------------------------------
                history[:, 0] /= 1920.0   # x
                history[:, 1] /= 1080.0   # y

                future[:, 0]  /= 1920.0
                future[:, 1]  /= 1080.0

                # -------------------------------
                # 🔥 VELOCITY (AFTER NORMALIZATION)
                # -------------------------------
                vx = np.diff(history[:, 0], prepend=history[0, 0])
                vy = np.diff(history[:, 1], prepend=history[0, 1])

                # -------------------------------
                # INPUT FORMAT: [x, y, vx, vy]
                # -------------------------------
                inp = np.stack(
                    [history[:, 0], history[:, 1], vx, vy],
                    axis=1
                )

                self.X.append(inp)
                self.Y.append(future)

        # Convert to tensors
        self.X = torch.tensor(self.X, dtype=torch.float32)
        self.Y = torch.tensor(self.Y, dtype=torch.float32)

        print("Dataset size:", len(self.X))

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.Y[idx]