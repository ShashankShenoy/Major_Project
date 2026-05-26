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
import base64

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
                _yolo_path = str(Path(__file__).resolve().parent / "yolov8n.pt")
                print(f"📦 Loading YOLO model from: {_yolo_path}")
                self.yolo_model = YOLO(_yolo_path)  # use yolov8n for low RAM/CPU usage
                print("✅ YOLO model loaded")
            except Exception as e:
                print(f"⚠️  YOLO load failed: {e}")
                self.yolo_model = None
        else:
            print("⚠️  YOLO not available - video detection disabled")

        try:
            from boxmot import DeepOcSort
            reid_weights = Path(__file__).resolve().parent.parent.parent / "unused" / "osnet_x0_25_msmt17.pt"
            self.tracker = DeepOcSort(
                reid_weights=str(reid_weights),
                device="0" if self.device == "cuda" else "cpu",
                half=(self.device == "cuda"),
                det_thresh=0.3,
                max_age=30,
                min_hits=3,
                iou_threshold=0.3,
            )
            print("✅ DeepOcSort loaded")
        except Exception as e:
            print(f"⚠️ DeepOcSort load failed: {e}")
            self.tracker = None

        self.last_video_update = 0
        self.history = {}

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
                detections, video_frame_b64 = await self._process_frame(frame, frame_count, tracked_ships)

                # Create frame output
                frame_output = FrameOutput(
                    frame_number=frame_count,
                    timestamp=time.time(),
                    total_detections=len(detections),
                    ships=detections,
                    collision_alerts=[],  # TODO: implement collision detection
                    video_frame=video_frame_b64,
                    frame_timestamp=time.time() if video_frame_b64 else None
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

                # Deeply throttle processing to 1 frame every 5 seconds to minimize CPU load
                await asyncio.sleep(5.0)

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
                            tracked_ships: Dict) -> Tuple[List[ShipDetection], Optional[str]]:
        """
        Process a single frame
        Returns: Tuple of List of ShipDetection objects, and optional base64 encoded frame
        """
        detections = []
        video_frame_b64 = None

        # Detect ships using YOLO + DeepOcSort
        try:
            if self.yolo_model is not None:
                # Use YOLO directly
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
        
        current_time = time.time()
        if current_time - self.last_video_update >= 5.0:
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                video_frame_b64 = base64.b64encode(encoded).decode("utf-8")
                self.last_video_update = current_time

        return detections, video_frame_b64

    async def _run_detection(self, frame: np.ndarray, frame_num: int,
                             tracked_ships: Dict) -> List[ShipDetection]:
        """Run YOLO detection and DeepOcSort tracking on frame"""
        detections = []

        if self.yolo_model is None:
            return detections

        try:
            # Run YOLO detection for boats (class 8)
            results = self.yolo_model(frame, conf=self.config.confidence_threshold, classes=[8], verbose=False)[0]
            dets = results.boxes.data.cpu().numpy()
            
            if self.tracker is not None:
                if len(dets) > 0:
                    tracks = self.tracker.update(dets, frame)
                else:
                    tracks = self.tracker.update(np.empty((0, 6)), frame)
            else:
                tracks = []

            if tracks is None or len(tracks) == 0:
                return detections

            frame_matches = []

            for t in tracks:
                x1, y1, x2, y2 = int(t[0]), int(t[1]), int(t[2]), int(t[3])
                ship_id_int = int(t[4])
                ship_id = f"cam_{ship_id_int:05d}"
                confidence = float(t[5]) if len(t) > 5 else 0.9

                # Calculate center
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2

                if ship_id not in self.history:
                    self.history[ship_id] = []
                self.history[ship_id].append((cx, cy))
                if len(self.history[ship_id]) > 30:
                    self.history[ship_id].pop(0)
                    
                frame_matches.append(ship_id)

                if ship_id not in tracked_ships:
                    tracked_ships[ship_id] = {
                        "first_seen_frame": frame_num,
                        "last_seen_frame": frame_num,
                        "tracked_frames": 1,
                        "cx": cx,
                        "cy": cy
                    }
                else:
                    tracked_ships[ship_id]["last_seen_frame"] = frame_num
                    tracked_ships[ship_id]["tracked_frames"] += 1
                    tracked_ships[ship_id]["cx"] = cx
                    tracked_ships[ship_id]["cy"] = cy

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
                
                # Draw on frame
                color = (0, 255, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, f"ID:{ship_id_int} {method}", (x1, max(y1 - 10, 0)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                
                # Draw trajectory
                pts = self.history[ship_id]
                for i in range(1, len(pts)):
                    cv2.line(frame, (int(pts[i-1][0]), int(pts[i-1][1])), 
                             (int(pts[i][0]), int(pts[i][1])), color, 2)
                             
                # Draw LSTM prediction
                if len(predicted_path_px) > 0:
                    prev = (int(cx), int(cy))
                    for px_p, py_p in predicted_path_px:
                        cv2.circle(frame, (int(px_p), int(py_p)), 2, (0, 0, 255), -1)
                        cv2.line(frame, prev, (int(px_p), int(py_p)), (0, 0, 255), 1)
                        prev = (int(px_p), int(py_p))

                # Create ShipDetection
                detection = ShipDetection(
                    id=ship_id,
                    mmsi=None,
                    name=f"Camera Det {ship_id_int}",
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
                    first_seen_frame=tracked_ships[ship_id]["first_seen_frame"],
                    last_seen_frame=frame_num,
                    tracked_frames=tracked_ships[ship_id]["tracked_frames"],
                    timestamp=time.time()
                )

                detections.append(detection)

            self._cleanup_tracks(
                tracked_ships,
                set(frame_matches),
                frame_num
            )

        except Exception as e:
            print(f"⚠️  Detection error on frame {frame_num}: {e}")
            import traceback
            traceback.print_exc()

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
