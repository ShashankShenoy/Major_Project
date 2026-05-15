import numpy as np
import torch
import torch.nn as nn
from collections import deque
from lstm.model import ShipLSTM


# -------------------------------
# PREDICTOR
# -------------------------------
class LSTMPredictor:

    def __init__(self, predict_steps=20, seq_len=50, device="cpu", verbose=False):
        self.predict_steps = predict_steps
        self.seq_len = seq_len
        self.device = device
        self.verbose = verbose

        self.gps_history = {}

        self.model = ShipLSTM(
            input_size=4,
            hidden=64,
            layers=2,
            predict_steps=predict_steps
        ).to(device)

        self.model.eval()
        self.trained = False

        print(f"LSTM predictor ready on {device}")
        if self.verbose:
            print(f"LSTM predictor verbose mode enabled")

    # -------------------------------
    # LOAD MODEL
    # -------------------------------
    def load_model(self, model_path):
        try:
            self.model.load_state_dict(
                torch.load(model_path, map_location=self.device)
            )
            self.model.eval()
            self.trained = True
            print(f"✅ Loaded trained LSTM model from {model_path}")
        except Exception as e:
            print(f"❌ Failed to load model: {e}")
            self.trained = False

    # -------------------------------
    # UPDATE (CORRECT VERSION)
    # -------------------------------
    def update(self, ship_id, x, y):
        if ship_id not in self.gps_history:
            self.gps_history[ship_id] = deque(maxlen=self.seq_len)

        # 🔥 NORMALIZE POSITION
        x_norm = x / 1920.0
        y_norm = y / 1080.0

        # 🔥 COMPUTE VELOCITY (IN NORMALIZED SPACE)
        if len(self.gps_history[ship_id]) > 0:
            prev = self.gps_history[ship_id][-1]
            vx = x_norm - prev[0]
            vy = y_norm - prev[1]
        else:
            vx, vy = 0.0, 0.0

        self.gps_history[ship_id].append([x_norm, y_norm, vx, vy])

    # -------------------------------
    # PREDICT
    # -------------------------------
    def predict(self, ship_id):
        if ship_id not in self.gps_history:
            if self.verbose:
                print(f"[LSTM predictor] ship={ship_id} no history available")
            return [], "NO_HISTORY"

        history = list(self.gps_history[ship_id])

        if len(history) >= self.seq_len and self.trained:
            output = self._lstm_predict(history)
            method = "LSTM"
        elif len(history) >= 10 and self.trained:
            output = self._lstm_predict_partial(history)
            method = "LSTM-PARTIAL"
        else:
            output = self._kinematic_predict(history)
            method = "KINEMATIC"

        if self.verbose:
            print(f"[LSTM predictor] ship={ship_id}, method={method}, history={len(history)}, predicted_steps={len(output)}")
            if len(output) > 0:
                preview = output[:min(3, len(output))]
                print(f"[LSTM predictor] ship={ship_id} preview points: {preview}")

        return output, method

    # -------------------------------
    # FULL LSTM
    # -------------------------------
    def _lstm_predict(self, history):
        seq = torch.tensor(
            history[-self.seq_len:],
            dtype=torch.float32
        ).unsqueeze(0).to(self.device)

        with torch.no_grad():
            pred = self.model(seq)

        output = []

        for p in pred[0].cpu().numpy():
            x = float(p[0]) * 1920.0
            y = float(p[1]) * 1080.0

            x = max(0, min(x, 1920))
            y = max(0, min(y, 1080))

            output.append((x, y))

        return output

    # -------------------------------
    # PARTIAL LSTM
    # -------------------------------
    def _lstm_predict_partial(self, history):
        padded = history[-self.seq_len:]

        while len(padded) < self.seq_len:
            padded.insert(0, padded[0])

        seq = torch.tensor(
            padded,
            dtype=torch.float32
        ).unsqueeze(0).to(self.device)

        with torch.no_grad():
            pred = self.model(seq)

        output = []

        for p in pred[0].cpu().numpy():
            x = float(p[0]) * 1920.0
            y = float(p[1]) * 1080.0

            x = max(0, min(x, 1920))
            y = max(0, min(y, 1080))

            output.append((x, y))

        return output

    # -------------------------------
    # FALLBACK (LINEAR)
    # -------------------------------
    def _kinematic_predict(self, history):
        if len(history) < 3:
            return []

        recent = history[-10:]

        xs = [h[0] for h in recent]
        ys = [h[1] for h in recent]
        t = list(range(len(xs)))

        try:
            px = np.polyfit(t, xs, 1)
            py = np.polyfit(t, ys, 1)
        except:
            return []

        n = len(xs)
        predicted = []

        for i in range(1, self.predict_steps + 1):
            predicted.append((
                float(np.polyval(px, n + i)) * 1920.0,
                float(np.polyval(py, n + i)) * 1080.0
            ))

        return predicted
    


#Each time step has 4 values,Usually:

# x position
# y position
# velocity x
# velocity y

# 👉 So model sees:
# 👉 “Where + how fast”#