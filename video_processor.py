# video_processor.py
import cv2
import numpy as np
from pathlib import Path
from ultralytics import YOLO
from collections import defaultdict, deque

from config import CONFIG
from tracker import ShipTracker
from direction import compute_direction, heading_to_cardinal
from lstm.lstm_predictor import LSTMPredictor
from collision.collision_detector import CollisionDetector
from output_handler import save_output

# Distinct colors per ID (cycles through these)
COLORS = [
    (255, 100, 100), (100, 255, 100), (100, 100, 255),
    (255, 255, 100), (255, 100, 255), (100, 255, 255),
    (255, 180,  50), ( 50, 180, 255), (180, 255,  50),
    (180,  50, 255), (255,  50, 180), ( 50, 255, 180),
]

def get_color(track_id):
    return COLORS[track_id % len(COLORS)]


class VideoProcessor:
    def __init__(self):
        print("Loading model...")
        self.model = YOLO(CONFIG["model_path"])
        try:
            import torch
            if torch.cuda.is_available():
                self.model.to("cuda")
                print("Model loaded on CUDA.")
            else:
                print("CUDA not available, running on CPU.")
        except Exception as exc:
            print(f"Warning: unable to verify CUDA availability: {exc}")
            print("Model will run using the default device.")

        # Use the model's OWN class names — not config
        self.class_names = self.model.names  # dict: {0: 'person', 8: 'boat', ...}

        print("Initializing tracker...")
        self.ship_tracker = ShipTracker()

        self.lstm_predictor = LSTMPredictor(
            predict_steps=CONFIG["predict_steps"],
            seq_len=CONFIG.get("lstm_seq_len", 30),
            device=CONFIG.get("device", "cpu")
        )

        model_path = Path(CONFIG.get("lstm_model_path", "models/lstm_model_trained.pt"))
        if model_path.exists():
            self.lstm_predictor.load_model(str(model_path))
        else:
            print(f"Warning: LSTM model not found at {model_path}. Prediction will fall back to kinematic behaviour.")

        self.results  = []
        self.frame_num = 0
        print("Ready.")

    def process_video(self, input_path, output_path, json_path=None):
        cap = cv2.VideoCapture(input_path)

        if not cap.isOpened():
            print(f"Error: cannot open video at {input_path}")
            return []

        w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps   = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        print(f"Video: {w}x{h} @ {fps:.1f}fps — {total} frames")

        writer = cv2.VideoWriter(
            output_path,
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (w, h)
        )

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            self.frame_num += 1
            print(f"Frame {self.frame_num}/{total}", end="\r")

            frame_data, annotated = self._process_frame(frame)
            self.results.append(frame_data)
            writer.write(annotated)

            cv2.imshow("Ship Tracker", annotated)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print("\nStopped by user.")
                break
            elif key == ord(' '):
                print("\nPaused — press space to continue.")
                while True:
                    if cv2.waitKey(0) & 0xFF == ord(' '):
                        break

        cap.release()
        writer.release()
        cv2.destroyAllWindows()
        if json_path:
            save_output(self.results, json_path)
        print(f"\nDone. Output saved to {output_path}")
        return self.results

    def _process_frame(self, frame):
        results = self.model(
            frame,
            conf=CONFIG["confidence"],
            verbose=False
        )[0]

        dets = results.boxes.data.cpu().numpy()
        if self.frame_num % 30 == 0:
            print(f"  Frame {self.frame_num}: {len(dets)} detections from YOLO")
        
        ships = self.ship_tracker.update(dets, frame)
        if self.frame_num % 30 == 0:
            print(f"  Frame {self.frame_num}: {len(ships)} tracked ships after tracker")

        for ship in ships:
            history  = self.ship_tracker.get_history(ship["id"])
            heading, speed   = compute_direction(history)
            cardinal         = heading_to_cardinal(heading)

            ship["heading"]   = heading
            ship["speed"]     = speed
            ship["direction"] = cardinal

            self.lstm_predictor.update(ship["id"], ship["center"][0], ship["center"][1])
            predicted, method = self.lstm_predictor.predict(ship["id"])

            ship["predicted_path"] = predicted
            ship["prediction_method"] = method

        frame_data = {
            "frame":      self.frame_num,
            "ship_count": len(ships),
            "ships": [
                {
                    "id":                int(s["id"]),
                    "class":             self.class_names.get(s["class_id"], "unknown"),
                    "confidence":        float(s["confidence"]),
                    "center":            [int(s["center"][0]), int(s["center"][1])],
                    "box":               [int(x) for x in s["box"]],
                    "heading":           float(s.get("heading", 0)),
                    "speed":             float(s.get("speed", 0)),
                    "direction":         str(s.get("direction", "--")),
                    "predicted_path":    [[float(p[0]), float(p[1])] for p in s.get("predicted_path", [])],
                    "prediction_method": str(s.get("prediction_method", "KIN"))
                }
                for s in ships
            ]
        }
        annotated = self._annotate(frame, ships)
        return frame_data, annotated

    def _annotate(self, frame, ships):
        overlay = frame.copy()

        for ship in ships:
            x1, y1, x2, y2 = ship["box"]
            cx, cy          = ship["center"]
            sid             = ship["id"]
            color           = get_color(sid)
            cls_name        = self.class_names.get(ship["class_id"], "unknown")

            # --- Filled semi-transparent box background ---
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)

            # --- Bold bounding box border ---
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # --- Label background pill ---
            # In _annotate method, find this line:
            label = f"ID:{sid} {cls_name} {ship['heading']}deg {ship['speed']:.1f}px/f"
            (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            label_x, label_y  = x1, y1 - 10
            cv2.rectangle(frame,
                          (label_x, label_y - th - 6),
                          (label_x + tw, label_y + baseline),
                          color, -1)

            # --- Label text in black for contrast ---
            cv2.putText(frame, label,
                        (label_x, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (0, 0, 0), 1, cv2.LINE_AA)

            # --- Track tail — fading colored line ---
            history = list(self.ship_tracker.get_history(sid))
            pts     = [(x, y) for x, y, _ in history]
            for i in range(1, len(pts)):
                alpha     = i / len(pts)
                fade      = tuple(int(c * alpha) for c in color)
                thickness = max(1, int(3 * alpha))
                cv2.line(frame, pts[i-1], pts[i], fade, thickness)

            # --- Predicted path — dashed dots fading to transparent ---
            predicted = []
            for point in ship.get("predicted_path", []):
                if (isinstance(point, (list, tuple)) and len(point) == 2 and
                        isinstance(point[0], (int, float)) and isinstance(point[1], (int, float))):
                    predicted.append((int(point[0]), int(point[1])))

            for i, (px, py) in enumerate(predicted):
                alpha  = 1 - i / max(len(predicted), 1)
                radius = max(2, int(5 * alpha))
                pfade  = tuple(int(c * alpha) for c in color)
                cv2.circle(frame, (px, py), radius, pfade, -1)
                # connect dots
                if i > 0:
                    prev = predicted[i-1]
                    cv2.line(frame, prev, (px, py),
                             tuple(int(c * alpha) for c in color), 1)

            # --- Direction arrow ---
            arrow_len  = 50
            angle_rad  = np.radians(ship["heading"])
            ex = int(cx + arrow_len * np.cos(angle_rad))
            ey = int(cy + arrow_len * np.sin(angle_rad))
            cv2.arrowedLine(frame, (cx, cy), (ex, ey),
                            color, 2, tipLength=0.35)

            # --- Center dot ---
            cv2.circle(frame, (cx, cy), 4, color, -1)
            cv2.circle(frame, (cx, cy), 4, (255,255,255), 1)

        # --- HUD top bar ---
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 45), (20, 20, 20), -1)
        cv2.putText(frame,
                    f"Frame: {self.frame_num}   Ships detected: {len(ships)}   "
                    f"Press Q to quit   SPACE to pause",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                    (255, 255, 255), 1, cv2.LINE_AA)

        return frame
    
    def process_video_with_map(self, input_path, output_path, map_view, json_path=None):
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            print(f"Error: cannot open {input_path}")
            return []

        w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps   = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"Video: {w}x{h} @ {fps:.1f}fps — {total} frames")

        self.collision_detector = CollisionDetector(fps=fps)
        save_interval = 8

        writer = cv2.VideoWriter(
            output_path,
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps, (w, h)
        )

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            self.frame_num += 1
            if self.frame_num % 30 == 0:
                print(f"\nFrame {self.frame_num}/{total}")

            frame_data, annotated = self._process_frame(frame)

            alerts = self.collision_detector.detect_collisions(
                frame_data["ships"], self.frame_num
            )
            frame_data["collision_alerts"] = [alert.__dict__ for alert in alerts]

            if alerts:
                if self.frame_num % 30 == 0:
                    print(f"  {len(alerts)} collision alerts detected")
                for idx, alert in enumerate(alerts[:3]):
                    msg = (f"ALERT {alert.ship1_id}-{alert.ship2_id} "
                           f"{alert.risk_level.upper()} {alert.time_to_cpa:.1f}s")
                    cv2.putText(
                        annotated, msg, (12, 70 + idx * 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 30, 220), 2, cv2.LINE_AA
                    )

            processed = map_view.update(frame_data["ships"], annotated, self.frame_num)
            if processed:
                processed_map = {ship["id"]: ship for ship in processed}
                for ship in frame_data["ships"]:
                    extra = processed_map.get(ship["id"], {})
                    ship["gps_lat"] = extra.get("gps_lat")
                    ship["gps_lon"] = extra.get("gps_lon")
                    ship["prediction_method"] = ship.get("prediction_method", "KIN")

            self.results.append(frame_data)
            writer.write(annotated)

            if json_path and self.frame_num % save_interval == 0:
                save_output(self.results, json_path)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print("\nStopped by user.")
                break
            elif key == ord(' '):
                while True:
                    if cv2.waitKey(0) & 0xFF == ord(' '):
                        break

        cap.release()
        writer.release()
        cv2.destroyAllWindows()
        
        # Final save to JSON
        if json_path:
            save_output(self.results, json_path)
            print(f"Results saved to {json_path}")
        
        # Print summary
        total_ships = sum(f["ship_count"] for f in self.results)
        unique_ids = set()
        total_alerts = sum(len(f.get("collision_alerts", [])) for f in self.results)
        for f in self.results:
            for s in f.get("ships", []):
                unique_ids.add(s["id"])
        
        print(f"\n╔═══════════════════════════════════════════════╗")
        print(f"║ PIPELINE SUMMARY                            ║")
        print(f"╠═══════════════════════════════════════════════╣")
        print(f"║ Total Frames Processed     : {self.frame_num:>27} ║")
        print(f"║ Total Detections           : {total_ships:>27} ║")
        print(f"║ Unique Ship IDs            : {len(unique_ids):>27} ║")
        print(f"║ Avg Detections/Frame       : {total_ships/max(self.frame_num, 1):>27.2f} ║")
        print(f"║ Collision Alerts Generated : {total_alerts:>27} ║")
        print(f"╚═══════════════════════════════════════════════╝")
        
        print(f"Output video: {output_path}")
        print(f"Output JSON : {json_path}")
        
        return self.results