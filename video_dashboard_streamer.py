# video_dashboard_streamer.py
"""
Processes prerecorded video, detects ships with CV + LSTM predictions,
converts to GPS coordinates, and streams to the dashboard map.
"""

import cv2
import asyncio
import websockets
import json
import time
import numpy as np
from pathlib import Path
from video_processor import VideoProcessor
from geo_mapper import GeoMapper
from config import CONFIG

class VideoDashboardStreamer:
    def __init__(self, video_path, camera_lat=1.264, camera_lon=103.84, fov_km=3.0):
        """Initialize video processor and geo mapper."""
        self.video_path = video_path
        self.camera_lat = camera_lat
        self.camera_lon = camera_lon

        # Initialize video processor
        self.processor = VideoProcessor()

        # Initialize geo mapper for pixel -> GPS conversion
        try:
            world_map_path = Path("world_map.tif")
            if not world_map_path.exists():
                print("⚠ World map not found, using estimated GPS conversion")
                self.geo_mapper = None
            else:
                self.geo_mapper = GeoMapper(
                    camera_lat=camera_lat,
                    camera_lon=camera_lon,
                    map_path=str(world_map_path),
                    fov_km=fov_km
                )
        except Exception as e:
            print(f"⚠ GeoMapper initialization failed: {e}")
            print("  Using estimated GPS conversion instead")
            self.geo_mapper = None

        self.frame_width = None
        self.frame_height = None
        self.fps = None

    def pixel_to_gps(self, px, py):
        """Convert pixel coordinates to GPS."""
        if self.geo_mapper:
            return self.geo_mapper.pixel_to_gps(
                px, py, self.frame_width, self.frame_height
            )
        else:
            # Fallback: estimate based on camera position and FOV
            km_per_deg_lat = 111.0
            km_per_deg_lon = 111.0 * np.cos(
                np.radians(self.camera_lat)
            )

            fov_km = 3.0
            norm_x = (px - self.frame_width / 2) / self.frame_width
            norm_y = (py - self.frame_height / 2) / self.frame_height

            dlat = -(norm_y * fov_km) / km_per_deg_lat
            dlon = (norm_x * fov_km) / km_per_deg_lon

            lat = self.camera_lat + dlat
            lon = self.camera_lon + dlon
            return round(lat, 6), round(lon, 6)

    def process_and_stream(self, speed_multiplier=1.0):
        """
        Process video frame by frame and yield WebSocket messages.
        speed_multiplier: >1 for faster, <1 for slower playback.
        """
        cap = cv2.VideoCapture(self.video_path)

        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {self.video_path}")

        self.frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        print(f"\n📹 Video: {self.frame_width}x{self.frame_height} @ {self.fps:.1f}fps")
        print(f"   Total frames: {total_frames}")
        print(f"   Camera location: ({self.camera_lat}, {self.camera_lon})")

        frame_count = 0
        frame_delay = (1.0 / self.fps) / speed_multiplier

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1

            # Process frame
            frame_data, _ = self.processor._process_frame(frame)

            # Convert pixel coords to GPS
            ais_ships = []
            for ship in frame_data["ships"]:
                if not ship["center"]:
                    continue

                px, py = ship["center"]
                lat, lon = self.pixel_to_gps(px, py)

                # Convert predicted path from pixels to GPS
                predicted_gps = []
                if ship.get("predicted_path"):
                    for pred_px, pred_py in ship["predicted_path"]:
                        pred_lat, pred_lon = self.pixel_to_gps(pred_px, pred_py)
                        predicted_gps.append([pred_lat, pred_lon])

                ais_ships.append({
                    "mmsi": ship["id"],
                    "name": f"Ship-{ship['id']}",
                    "class": ship["class"],
                    "confidence": ship["confidence"],
                    "pos": [lon, lat],  # [lon, lat] for GeoJSON
                    "sog": ship["speed"],  # pixels/frame -> treat as speed proxy
                    "cog": ship["heading"],
                    "track": [],  # Will be populated by frontend
                    "predicted": predicted_gps,  # GPS coordinates
                    "prediction_method": ship["prediction_method"],
                    "trackStats": {
                        "distance": 0,
                        "duration": 0
                    }
                })

            # Create WebSocket message in AIS format
            message = {
                "type": "unified",
                "frame": frame_count,
                "ais_ships": ais_ships,
                "timestamp": time.time()
            }

            yield message

            if frame_count % 30 == 0:
                print(f"  Frame {frame_count}/{total_frames} - "
                      f"{len(ais_ships)} ships detected")

            # Respect frame timing
            time.sleep(frame_delay)

        cap.release()
        print(f"\n✅ Video processing complete: {frame_count} frames")

    async def stream_to_websocket(self, ws_uri="ws://localhost:8000/ws",
                                   speed_multiplier=1.0):
        """Stream video data to WebSocket endpoint."""
        try:
            async with websockets.connect(ws_uri) as websocket:
                print(f"✅ Connected to {ws_uri}")

                for message in self.process_and_stream(speed_multiplier):
                    await websocket.send(json.dumps(message))
                    await asyncio.sleep(0.01)

                print("✅ Stream complete!")

        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            raise


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Stream video to AIS dashboard")
    parser.add_argument("video", help="Path to prerecorded video file")
    parser.add_argument("--lat", type=float, default=1.264,
                       help="Camera latitude (Singapore port default)")
    parser.add_argument("--lon", type=float, default=103.84,
                       help="Camera longitude (Singapore port default)")
    parser.add_argument("--speed", type=float, default=1.0,
                       help="Playback speed multiplier (default 1.0)")
    parser.add_argument("--fov", type=float, default=3.0,
                       help="Field of view in km (default 3.0)")
    parser.add_argument("--ws", default="ws://localhost:8000/ws",
                       help="WebSocket URI")

    args = parser.parse_args()

    if not Path(args.video).exists():
        print(f"❌ Video file not found: {args.video}")
        return

    print(f"""
╔════════════════════════════════════════╗
║  VIDEO DASHBOARD STREAMER              ║
╠════════════════════════════════════════╣
║  Video: {args.video:<25} ║
║  Location: ({args.lat}, {args.lon})       ║
║  Speed: {args.speed}x                         ║
║  WebSocket: {args.ws:<18} ║
╚════════════════════════════════════════╝
    """)

    streamer = VideoDashboardStreamer(
        video_path=args.video,
        camera_lat=args.lat,
        camera_lon=args.lon,
        fov_km=args.fov
    )

    asyncio.run(streamer.stream_to_websocket(
        ws_uri=args.ws,
        speed_multiplier=args.speed
    ))


if __name__ == "__main__":
    main()
