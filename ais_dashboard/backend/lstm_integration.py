import torch
import torch.nn as nn
from collections import deque
from typing import Tuple, List, Optional
from pathlib import Path


class ShipLSTM(nn.Module):
    """Sequence-to-sequence LSTM with attention for ship trajectory prediction"""

    def __init__(self, input_size: int = 4, hidden: int = 64, layers: int = 2, predict_steps: int = 20):
        super().__init__()
        self.predict_steps = predict_steps
        self.hidden_size = hidden

        self.encoder = nn.LSTM(
            input_size,
            hidden,
            num_layers=layers,
            batch_first=True,
            dropout=0.1,
            bidirectional=True
        )

        self.attention = nn.Sequential(
            nn.Linear(hidden * 2, hidden),
            nn.Tanh(),
            nn.Linear(hidden, 1)
        )

        self.decoder = nn.LSTMCell(
            2 + hidden * 2,
            hidden
        )

        self.output_head = nn.Linear(hidden, 2)

    def forward(self, x):
        """
        Input: (batch, seq_len, 4) - [x_norm, y_norm, vx, vy]
        Output: (batch, predict_steps, 2) - predicted [x_norm, y_norm]
        """
        batch_size = x.size(0)

        encoder_out, _ = self.encoder(x)

        attention_scores = self.attention(encoder_out)
        attention_weights = torch.softmax(attention_scores, dim=1)
        context = (encoder_out * attention_weights).sum(dim=1)

        predictions = []
        decoder_h = encoder_out[:, -1, :self.hidden_size]
        decoder_c = torch.zeros(batch_size, self.hidden_size, device=x.device)
        prev_pos = x[:, -1, :2]

        for _ in range(self.predict_steps):
            decoder_input = torch.cat([prev_pos, context], dim=1)
            decoder_h, decoder_c = self.decoder(
                decoder_input,
                (decoder_h, decoder_c)
            )
            pred_pos = self.output_head(decoder_h)
            predictions.append(pred_pos)
            prev_pos = pred_pos

        return torch.stack(predictions, dim=1)


class LSTMEngine:
    """Wrapper around LSTM predictor for integration with video processing"""

    def __init__(self, model_path: str, device: str = "cuda", predict_steps: int = 20, seq_len: int = 50, verbose: bool = False):
        self.device = device if torch.cuda.is_available() else "cpu"
        self.predict_steps = predict_steps
        self.seq_len = seq_len
        self.verbose = verbose

        # Initialize model
        self.model = ShipLSTM(
            input_size=4,
            hidden=64,
            layers=2,
            predict_steps=predict_steps
        ).to(self.device)

        self.model.eval()
        self.trained = False

        # Load model if path exists
        if Path(model_path).exists():
            try:
                try:
                    state_dict = torch.load(
                        model_path,
                        map_location=self.device,
                        weights_only=True
                    )
                except TypeError:
                    state_dict = torch.load(
                        model_path,
                        map_location=self.device
                    )
                self.model.load_state_dict(state_dict)
                self.trained = True
                if self.verbose:
                    print(f"✅ LSTM model loaded from {model_path}")
            except Exception as e:
                print(f"⚠️  Failed to load LSTM model: {e}")
                self.trained = False
        else:
            print(f"⚠️  Model file not found: {model_path} - using fallback kinematic predictions")

        # Track history per ship
        self.gps_history = {}

    def update(self, ship_id: str, x: float, y: float):
        """
        Update ship history with new position
        Args:
            ship_id: Unique ship identifier
            x: X coordinate in pixels (0-1920)
            y: Y coordinate in pixels (0-1080)
        """
        if ship_id not in self.gps_history:
            self.gps_history[ship_id] = deque(maxlen=self.seq_len)

        # Normalize position
        x_norm = x / 1920.0
        y_norm = y / 1080.0

        # Compute velocity
        if len(self.gps_history[ship_id]) > 0:
            prev = self.gps_history[ship_id][-1]
            vx = x_norm - prev[0]
            vy = y_norm - prev[1]
        else:
            vx, vy = 0.0, 0.0

        self.gps_history[ship_id].append([x_norm, y_norm, vx, vy])

    def predict(self, ship_id: str) -> Tuple[List[Tuple[float, float]], str]:
        """
        Predict future trajectory for ship
        Returns:
            (predicted_points: list of (x, y) tuples, method: str)
        """
        if ship_id not in self.gps_history:
            if self.verbose:
                print(f"[LSTM] ship={ship_id} no history")
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
            print(f"[LSTM] ship={ship_id} method={method} history={len(history)} steps={len(output)}")

        return output, method

    def _lstm_predict(self, history: List[List[float]]) -> List[Tuple[float, float]]:
        """Full LSTM prediction with complete history"""
        import numpy as np

        seq = torch.tensor(
            history[-self.seq_len :],
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

    def _lstm_predict_partial(self, history: List[List[float]]) -> List[Tuple[float, float]]:
        """Partial LSTM prediction with padding"""
        import numpy as np

        padded = history[-self.seq_len :]
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

    def _kinematic_predict(self, history: List[List[float]]) -> List[Tuple[float, float]]:
        """Fallback: linear extrapolation from velocity"""
        import numpy as np

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
            x = float(np.polyval(px, n + i)) * 1920.0
            y = float(np.polyval(py, n + i)) * 1080.0
            x = max(0, min(x, 1920))
            y = max(0, min(y, 1080))
            predicted.append((x, y))

        return predicted

    def reset_ship(self, ship_id: str):
        """Clear history for a ship"""
        if ship_id in self.gps_history:
            del self.gps_history[ship_id]

    def cleanup_old_ships(self, active_ship_ids: set):
        """Remove ships not in active set"""
        inactive = set(self.gps_history.keys()) - active_ship_ids
        for ship_id in inactive:
            del self.gps_history[ship_id]
