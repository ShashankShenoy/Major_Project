# video_processor.py
import cv2
import numpy as np
from ultralytics import YOLO
from collections import defaultdict, deque

from config import CONFIG
from tracker import ShipTracker
from direction import compute_direction, heading_to_cardinal
from predictor import predict_path_curved

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
        self.model.to("cuda")

        # Use the model's OWN class names — not config
        self.class_names = self.model.names  # dict: {0: 'person', 8: 'boat', ...}

        print("Initializing tracker...")
        self.ship_tracker = ShipTracker()

        self.results  = []
        self.frame_num = 0
        print("Ready.")

    def process_video(self, input_path, output_path):
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
        print(f"\nDone. Output saved to {output_path}")
        return self.results

    def _process_frame(self, frame):
        results = self.model(
            frame,
            conf=CONFIG["confidence"],
            verbose=False
        )[0]

        dets = results.boxes.data.cpu().numpy()
        ships = self.ship_tracker.update(dets, frame)

        for ship in ships:
            history  = self.ship_tracker.get_history(ship["id"])
            heading, speed   = compute_direction(history)
            cardinal         = heading_to_cardinal(heading)
            predicted        = predict_path_curved(history, CONFIG["predict_steps"])

            ship["heading"]        = heading
            ship["speed"]          = speed
            ship["direction"]      = cardinal
            ship["predicted_path"] = predicted

        frame_data = {
            "frame":      self.frame_num,
            "ship_count": len(ships),
            "ships": [
                {
                    "id":            s["id"],
                    "class":         self.class_names.get(s["class_id"], "unknown"),
                    "confidence":    s["confidence"],
                    "center":        s["center"],
                    "heading":       s["heading"],
                    "speed":         s["speed"],
                    "direction":     s["direction"],
                    "predicted_path": s["predicted_path"]
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
            predicted = ship["predicted_path"]
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
    
    def process_video_with_map(self, input_path, output_path, map_view):
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            print(f"Error: cannot open {input_path}")
            return []

        w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps   = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"Video: {w}x{h} @ {fps:.1f}fps — {total} frames")

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
            print(f"Frame {self.frame_num}/{total}", end="\r")

            frame_data, annotated = self._process_frame(frame)
            self.results.append(frame_data)
            writer.write(annotated)

            # Pass annotated frame AND ship data to dashboard
            map_view.update(
                frame_data["ships"],
                annotated,          # ← pass the annotated video frame
                self.frame_num
            )

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
        print(f"\nDone. Saved to {output_path}")
        return self.results