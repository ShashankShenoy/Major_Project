# lstm_predictor.py
import numpy as np
import torch
import torch.nn as nn
from collections import deque


class ShipLSTM(nn.Module):
    """
    LSTM that takes last N GPS positions + velocities
    and predicts next K positions.
    """
    def __init__(self, input_size=4, hidden=64, layers=2, predict_steps=20):
        super().__init__()
        self.predict_steps = predict_steps
        self.lstm = nn.LSTM(input_size, hidden,
                            num_layers=layers,
                            batch_first=True,
                            dropout=0.1)
        self.fc = nn.Linear(hidden, predict_steps * 2)

    def forward(self, x):
        # x: (batch, seq_len, 4)
        out, _ = self.lstm(x)
        pred   = self.fc(out[:, -1])
        return pred.view(-1, self.predict_steps, 2)


class LSTMPredictor:
    """
    Wrapper that manages the LSTM model and GPS history per ship.
    Falls back to kinematic prediction until enough data is collected.
    """

    def __init__(self, predict_steps=20, seq_len=30, device="cuda"):
        self.predict_steps = predict_steps
        self.seq_len       = seq_len
        self.device        = device

        # GPS + velocity history per ship_id
        # Each entry: [lat, lon, vel_lat, vel_lon]
        self.gps_history = {}

        # Build model
        self.model = ShipLSTM(
            input_size=4,
            hidden=64,
            layers=2,
            predict_steps=predict_steps
        ).to(device)

        # Start in inference mode
        # (train separately once you have enough data)
        self.model.eval()
        self.trained = False

        print(f"LSTM predictor ready on {device}")

    def update(self, ship_id, lat, lon, vel_lat, vel_lon):
        """ Add a new GPS observation for a ship. """
        if ship_id not in self.gps_history:
            self.gps_history[ship_id] = deque(maxlen=self.seq_len)

        self.gps_history[ship_id].append(
            [lat, lon, vel_lat, vel_lon]
        )

    def predict(self, ship_id):
        """
        Returns list of predicted (lat, lon) positions.
        Uses LSTM if enough history, otherwise kinematic fallback.
        """
        if ship_id not in self.gps_history:
            return []

        history = list(self.gps_history[ship_id])

        # Need full sequence for LSTM
        if len(history) >= self.seq_len and self.trained:
            return self._lstm_predict(history)
        else:
            return self._kinematic_predict(history)

    def _lstm_predict(self, history):
        seq = torch.tensor(
            history[-self.seq_len:],
            dtype=torch.float32
        ).unsqueeze(0).to(self.device)

        with torch.no_grad():
            pred = self.model(seq)  # (1, steps, 2)

        return [(float(p[0]), float(p[1]))
                for p in pred[0].cpu().numpy()]

    def _kinematic_predict(self, history):
        """
        Simple fallback: extrapolate using average velocity.
        Used until LSTM has enough training data.
        """
        if len(history) < 3:
            return []

        recent = history[-10:]
        lats = [h[0] for h in recent]
        lons = [h[1] for h in recent]
        t    = list(range(len(recent)))

        # Weighted linear fit
        w = np.exp(np.linspace(0, 1, len(t)))
        try:
            p_lat = np.polyfit(t, lats, 1, w=w)
            p_lon = np.polyfit(t, lons, 1, w=w)
        except Exception:
            return []

        n = len(recent)
        predicted = []
        for i in range(1, self.predict_steps + 1):
            predicted.append((
                float(np.polyval(p_lat, n + i)),
                float(np.polyval(p_lon, n + i))
            ))

        return predicted

    def collect_training_data(self, ship_id):
        """
        Returns training sequence for this ship if long enough.
        Call this to build a training dataset over time.
        """
        if ship_id not in self.gps_history:
            return None
        history = list(self.gps_history[ship_id])
        if len(history) < self.seq_len + self.predict_steps:
            return None
        return history