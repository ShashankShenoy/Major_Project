import asyncio
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from datetime import datetime
import time
import cv2
import numpy as np
from math import radians, cos, sin, asin, sqrt

# Add unused folder to path to import video_processor
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "unused"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lstm"))

from data_models import (
    ShipDetection, FrameOutput, SourceType, PredictionMethod,
    Direction, CameraStatus, VideoProcessingConfig
)
from lstm_integration import LSTMEngine
from cv_matcher import CVMatcher

# Try to import YOLO for object detection
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    print("⚠️  ultralytics (YOLO) not installed - video detection will be limited")
    YOLO_AVAILABLE = False

# Try to import VideoProcessor (legacy, optional)
try:
    from video_processor import VideoProcessor
except ImportError as e:
    print(f"⚠️  Could not import VideoProcessor: {e}")
    VideoProcessor = None


class DirectionCalculator:
    """Calculate direction from heading"""

    @staticmethod
    def heading_to_direction(heading: float) -> Direction:
        """Convert heading (0-360) to cardinal direction"""
        if heading < 0:
            heading = (heading % 360 + 360) % 360

        dirs = [Direction.N, Direction.NE, Direction.E, Direction.SE,
                Direction.S, Direction.SW, Direction.W, Direction.NW]
        idx = int(round(heading / 45)) % 8
        return dirs[idx]


class GPSConverter:
    """Convert pixel coordinates to GPS coordinates"""

    def __init__(self, camera_lat: float, camera_lon: float, fov_km: float,
                 video_width: int = 1920, video_height: int = 1080):
        self.camera_lat = camera_lat
        self.camera_lon = camera_lon
        self.fov_km = fov_km
        self.video_width = video_width
        self.video_height = video_height
        self.center_x = video_width / 2
        self.center_y = video_height / 2

    def pixels_to_gps(self, px: float, py: float) -> Tuple[float, float]:
        """Convert pixel coordinates to GPS [lat, lon]"""
        # Normalize to [-1, 1]
        norm_x = (px - self.center_x) / self.center_x
        norm_y = (self.center_y - py) / self.center_y

        # Convert to lat/lon offset
        lat_offset = norm_y * (self.fov_km / 111.0)
        lon_offset = norm_x * (self.fov_km / (111.0 * cos(radians(self.camera_lat))))

        return (
            self.camera_lat + lat_offset,
            self.camera_lon + lon_offset
        )


class VideoOrchestrator:
    """Orchestrates video processing, detection, LSTM prediction, and GPS conversion"""

    def __init__(self, config: VideoProcessingConfig):
        self.config = config
        self.device = config.device

        # Initialize components
        self.gps_converter = GPSConverter(
            config.camera_lat, config.camera_lon, config.fov_km
        )

        # Absolute path so it works regardless of CWD when uvicorn is launched
        _model_path = str(
            Path(__file__).resolve().parent.parent.parent / "models" / "lstm_model_trained.pt"
        )
        self.lstm_engine = LSTMEngine(
            model_path=_model_path,
            device=self.device,
            verbose=True
        )

        self.cv_matcher = CVMatcher(
            match_radius_km=config.cv_match_radius_deg * 111.0,  # Convert degrees to km
            verbose=True
        )

        self.video_processor: Optional[VideoProcessor] = None
        self.camera_status = CameraStatus(
            available=False,
            lat=config.camera_lat,
            lon=config.camera_lon,
            fov_km=config.fov_km
        )

        self.frame_queue: asyncio.Queue = None
        self.is_processing = False
        self.processed_frames = 0
        self.start_time = None
        self.next_track_id = 0

    async def initialize(self, queue: asyncio.Queue):
        """Initialize orchestrator with output queue"""
        self.frame_queue = queue

        # Load YOLO model if available
        if YOLO_AVAILABLE:
            try:
                print("📦 Loading YOLO model...")
                self.yolo_model = YOLO("yolov8n.pt")  # nano model for speed
                print("✅ YOLO model loaded")
            except Exception as e:
                print(f"⚠️  YOLO load failed: {e}")
                self.yolo_model = None
        else:
            print("⚠️  YOLO not available - video detection disabled")

        print("✅ Video Orchestrator initialized")
        print(f"   Device: {self.device}")
        print(f"   Camera: ({self.config.camera_lat}, {self.config.camera_lon})")
        print(f"   LSTM: {'Ready' if self.lstm_engine.trained else 'Fallback (kinematic)'}")
        print(f"   YOLO: {'Available' if self.yolo_model else 'Disabled'}")

    async def process_video(self, video_path: str):
        """Process video frames continuously"""
        if not Path(video_path).exists():
            print(f"❌ Video file not found: {video_path}")
            return

        self.is_processing = True
        self.start_time = time.time()
        self.processed_frames = 0

        print(f"🎬 Starting video processing: {video_path}")

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                print(f"❌ Failed to open video: {video_path}")
                return

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            print(f"   FPS: {fps}, Total frames: {total_frames}")

            # Initialize video processor if available
            if VideoProcessor is not None:
                try:
                    self.video_processor = VideoProcessor(
                        yolo_model="yolov8m",
                        device=self.device,
                        conf=self.config.confidence_threshold
                    )
                    print("✅ VideoProcessor initialized")
                except Exception as e:
                    print(f"⚠️  VideoProcessor init failed: {e}")
                    self.video_processor = None

            frame_count = 0
            tracked_ships = {}  # Track ships across frames

            while self.is_processing:
                ret, frame = cap.read()
                if not ret:
                    break

                # Process frame
                detections = await self._process_frame(frame, frame_count, tracked_ships)

                # Create frame output
                frame_output = FrameOutput(
                    frame_number=frame_count,
                    timestamp=time.time(),
                    total_detections=len(detections),
                    ships=detections,
                    collision_alerts=[]  # TODO: implement collision detection
                )

                # Put in queue for broadcaster
                await self.frame_queue.put(frame_output)

                frame_count += 1
                self.processed_frames += 1

                # Log progress every 100 frames
                if frame_count % 100 == 0:
                    elapsed = time.time() - self.start_time
                    fps = frame_count / elapsed
                    print(f"   Frame {frame_count}/{total_frames} ({fps:.1f} fps)")

                # Yield to event loop
                await asyncio.sleep(0)

            cap.release()

            elapsed = time.time() - self.start_time
            avg_fps = self.processed_frames / elapsed if elapsed > 0 else 0
            print(f"✅ Video processing complete: {self.processed_frames} frames in {elapsed:.1f}s ({avg_fps:.1f} fps)")

        except Exception as e:
            print(f"❌ Video processing error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.is_processing = False
            self.camera_status.available = False

    async def _process_frame(self, frame: np.ndarray, frame_num: int,
                            tracked_ships: Dict) -> List[ShipDetection]:
        """
        Process a single frame
        Returns: List of ShipDetection objects
        """
        detections = []

        # Detect ships using YOLO or legacy video_processor
        try:
            if self.yolo_model is not None:
                # Use YOLO directly
                frame_detections = await self._run_detection(
                    frame,
                    frame_num,
                    tracked_ships
                )
                detections.extend(frame_detections)
            elif self.video_processor is not None:
                # Use legacy VideoProcessor if available
                frame_detections = await self._run_detection(
                    frame,
                    frame_num,
                    tracked_ships
                )
                detections.extend(frame_detections)
        except Exception as e:
            print(f"⚠️  Detection failed on frame {frame_num}: {e}")

        # Update camera status
        self.camera_status.available = len(detections) > 0
        self.camera_status.timestamp = time.time()

        return detections

    async def _run_detection(self, frame: np.ndarray, frame_num: int,
                             tracked_ships: Dict) -> List[ShipDetection]:
        """Run YOLO detection on frame"""
        detections = []

        if self.yolo_model is None:
            return detections

        try:
            # Run YOLO detection
            results = self.yolo_model(frame, conf=self.config.confidence_threshold, verbose=False)

            if not results or len(results) == 0:
                return detections

            result = results[0]
            boxes = result.boxes

            frame_matches = []

            for idx, box in enumerate(boxes):
                # Extract detection info
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                confidence = float(box.conf[0].cpu().numpy())

                # Calculate center
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2

                ship_id, track_state = self._assign_track_id(
                    cx,
                    cy,
                    frame_num,
                    tracked_ships
                )
                frame_matches.append(ship_id)

                # Convert to GPS
                gps_lat, gps_lon = self.gps_converter.pixels_to_gps(cx, cy)

                # Get LSTM prediction
                self.lstm_engine.update(ship_id, cx, cy)
                predicted_path_px, method = self.lstm_engine.predict(ship_id)

                # Convert predicted path to GPS
                predicted_path_gps = [
                    self.gps_converter.pixels_to_gps(px, py)
                    for px, py in predicted_path_px
                ]

                # Create ShipDetection
                detection = ShipDetection(
                    id=ship_id,
                    mmsi=None,
                    name=f"Camera Det {idx}",
                    pixel_center=[cx, cy],
                    gps_lat=gps_lat,
                    gps_lon=gps_lon,
                    heading=0,
                    speed=0,
                    direction=Direction.STATIONARY,
                    confidence=confidence,
                    source=SourceType.CAMERA,
                    predicted_path_pixels=predicted_path_px,
                    predicted_path_gps=predicted_path_gps,
                    prediction_method=method,
                    is_matched_to_ais=False,
                    first_seen_frame=frame_num,
                    last_seen_frame=frame_num,
                    tracked_frames=track_state["tracked_frames"],
                    timestamp=time.time()
                )

                detections.append(detection)

            self._cleanup_tracks(
                tracked_ships,
                set(frame_matches),
                frame_num
            )

        except Exception as e:
            print(f"⚠️  YOLO detection error on frame {frame_num}: {e}")

        return detections

    def _assign_track_id(self, cx: float, cy: float, frame_num: int,
                         tracked_ships: Dict) -> Tuple[str, Dict]:
        """Assign a stable camera track ID using nearest-neighbor matching."""
        max_match_distance = 80.0
        best_id = None
        best_distance = max_match_distance

        for ship_id, state in tracked_ships.items():
            if state.get("matched_this_frame"):
                continue

            distance = float(
                np.hypot(cx - state["cx"], cy - state["cy"])
            )
            if distance < best_distance:
                best_distance = distance
                best_id = ship_id

        if best_id is None:
            ship_id = f"cam_{self.next_track_id:05d}"
            self.next_track_id += 1
            tracked_ships[ship_id] = {
                "cx": cx,
                "cy": cy,
                "first_seen_frame": frame_num,
                "last_seen_frame": frame_num,
                "tracked_frames": 1,
                "matched_this_frame": True
            }
            return ship_id, tracked_ships[ship_id]

        state = tracked_ships[best_id]
        state["cx"] = cx
        state["cy"] = cy
        state["last_seen_frame"] = frame_num
        state["tracked_frames"] += 1
        state["matched_this_frame"] = True
        return best_id, state

    def _cleanup_tracks(self, tracked_ships: Dict, active_ids: set,
                        frame_num: int) -> None:
        """Expire stale tracks and keep LSTM history aligned."""
        stale_ids = []

        for ship_id, state in tracked_ships.items():
            if ship_id in active_ids:
                state["matched_this_frame"] = False
                continue

            if frame_num - state["last_seen_frame"] > 15:
                stale_ids.append(ship_id)

        for ship_id in stale_ids:
            tracked_ships.pop(ship_id, None)

        self.lstm_engine.cleanup_old_ships(set(tracked_ships.keys()))

    def stop(self):
        """Stop video processing"""
        self.is_processing = False
        print("🛑 Video processing stopped")


async def create_video_orchestrator(config: VideoProcessingConfig) -> VideoOrchestrator:
    """Factory function to create and initialize orchestrator"""
    orchestrator = VideoOrchestrator(config)
    return orchestrator
