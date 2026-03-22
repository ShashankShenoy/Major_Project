# app.py
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '0'

import json
import sys
import torch
from video_processor import VideoProcessor
from map_view import MapView
from output_handler import save_output
from config import CONFIG

print(f"Using device: {'GPU - ' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")

def main():
    input_path  = sys.argv[1] if len(sys.argv) > 1 else CONFIG["input_video"]
    output_path = sys.argv[2] if len(sys.argv) > 2 else CONFIG["output_video"]
    json_path   = sys.argv[3] if len(sys.argv) > 3 else CONFIG["output_json"]

    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print(f"JSON:   {json_path}")
    print("-" * 40)

    # Init video processor
    processor = VideoProcessor()

    # Init map view — set your camera GPS here
    map_view = MapView(
        camera_lat = CONFIG["camera_lat"],
        camera_lon = CONFIG["camera_lon"],
        map_path   = CONFIG["map_path"],
        fov_km     = CONFIG["fov_km"]
    )

    results = processor.process_video_with_map(
        input_path, output_path, map_view
    )

    save_output(results, json_path)

    total_ships = sum(f["ship_count"] for f in results)
    print(f"\nSummary:")
    print(f"  Frames processed : {len(results)}")
    print(f"  Total detections : {total_ships}")
    print(f"  Avg per frame    : {total_ships / max(len(results), 1):.1f}")

if __name__ == "__main__":
    main()