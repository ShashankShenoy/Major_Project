# output_handler.py
import json
import os
from datetime import datetime


def build_output(frame_num, ships, class_names):
    """
    Builds a dictionary for one frame's worth of detections.
    """
    frame_data = {
        "frame": frame_num,
        "timestamp": datetime.now().isoformat(),
        "ship_count": len(ships),
        "ships": []
    }

    for ship in ships:
        cls_name = class_names[ship["class_id"]] if ship["class_id"] < len(class_names) else "unknown"
        frame_data["ships"].append({
            "id": ship["id"],
            "class": cls_name,
            "confidence": ship["confidence"],
            "center": ship["center"],
            "box": ship["box"],
            "heading": ship.get("heading", 0.0),
            "speed": ship.get("speed", 0.0),
            "direction": ship.get("direction", "N/A"),
            "predicted_path": ship.get("predicted_path", [])
        })

    return frame_data


def save_output(all_frames_data, output_path):
    """
    Saves full results to JSON.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_frames_data, f, indent=2)
    print(f"Results saved to {output_path}")