# tracker.py
from collections import defaultdict, deque
from boxmot import DeepOcSort
from pathlib import Path
from config import CONFIG


class ShipTracker:
    """
    Wraps DeepOCSORT which gives us:
    - Unique persistent ID per ship
    - ReID: restores original ID if ship re-enters frame
    - Appearance embedding for matching
    """

    def __init__(self):
        self.tracker = DeepOcSort(
            reid_weights=Path("osnet_x0_25_msmt17.pt"),
            device="0",
            half=True
        )

        # Per ship: stores (cx, cy, frame_num) history
        self.track_history = defaultdict(
            lambda: deque(maxlen=CONFIG["track_history"])
        )

    def update(self, detections, frame):
        """
        Args:
            detections: raw YOLO results boxes (numpy array)
            frame:      current video frame (numpy array)
        
        Returns:
            list of dicts, one per tracked ship
        """
        if len(detections) == 0:
            return []

        # DeepOCSORT expects: x1,y1,x2,y2,conf,cls
        tracks = self.tracker.update(detections, frame)
        # tracks output: x1,y1,x2,y2,track_id,conf,cls,idx

        ships = []
        for track in tracks:
            x1, y1, x2, y2 = int(track[0]), int(track[1]), int(track[2]), int(track[3])
            track_id = int(track[4])
            conf = float(track[5])
            cls = int(track[6])

            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2

            # Add to history
            self.track_history[track_id].append((cx, cy, 0))

            ships.append({
                "id": track_id,
                "box": (x1, y1, x2, y2),
                "center": (cx, cy),
                "class_id": cls,
                "confidence": round(conf, 2),
                "history": list(self.track_history[track_id])
            })

        return ships

    def get_history(self, track_id):
        return self.track_history[track_id]