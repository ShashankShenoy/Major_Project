from pydantic import BaseModel, Field
from typing import List, Tuple, Optional, Dict
from enum import Enum


class SourceType(str, Enum):
    """Data source for ship detection"""
    CAMERA = "CAMERA"
    AIS = "AIS"
    LSTM = "LSTM"


class PredictionMethod(str, Enum):
    """Method used for prediction"""
    LSTM = "LSTM"
    LSTM_PARTIAL = "LSTM-PARTIAL"
    KINEMATIC = "KINEMATIC"
    AIS_EXTRAPOLATION = "AIS-EXTRAPOLATION"
    NO_HISTORY = "NO_HISTORY"


class Direction(str, Enum):
    """Cardinal direction"""
    N = "N"
    NE = "NE"
    E = "E"
    SE = "SE"
    S = "S"
    SW = "SW"
    W = "W"
    NW = "NW"
    STATIONARY = "stationary"


class ShipDetection(BaseModel):
    """Unified ship detection model across all sources (camera, AIS, LSTM)"""

    # Identification
    id: str = Field(..., description="Format: 'cam_001' (camera) or 'ais_123456789' (AIS)")
    mmsi: Optional[int] = Field(None, description="AIS MMSI number if known")
    name: Optional[str] = Field(None, description="Ship name from AIS")

    # Positioning (required)
    pixel_center: Tuple[float, float] = Field(..., description="[x, y] in 1920x1080 pixel space")
    gps_lat: float = Field(..., description="Latitude in decimal degrees")
    gps_lon: float = Field(..., description="Longitude in decimal degrees")
    heading: float = Field(..., description="Heading in degrees 0-360")

    # Motion
    speed: float = Field(default=0.0, description="Speed (pixels/frame or knots)")
    direction: Direction = Field(default=Direction.STATIONARY, description="Cardinal direction")

    # Detection Quality
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence 0-1")
    source: SourceType = Field(..., description="Data source: CAMERA, AIS, or LSTM")

    # Predictions (can be empty for stationary ships)
    predicted_path_pixels: List[Tuple[float, float]] = Field(
        default_factory=list,
        description="Predicted future positions in pixel coordinates"
    )
    predicted_path_gps: List[Tuple[float, float]] = Field(
        default_factory=list,
        description="Predicted future positions in GPS coordinates [lat, lon]"
    )
    prediction_method: PredictionMethod = Field(..., description="Method used for prediction")

    # Matching Status
    is_matched_to_ais: bool = Field(default=False, description="Whether matched to AIS ship")
    matched_ais_mmsi: Optional[int] = Field(None, description="MMSI of matched AIS ship")
    match_distance_km: Optional[float] = Field(None, description="Distance to matched AIS ship in km")

    # Metadata
    first_seen_frame: int = Field(..., description="Frame number when first detected")
    last_seen_frame: int = Field(..., description="Frame number of last detection")
    tracked_frames: int = Field(..., description="Total number of frames this ship appeared in")
    timestamp: float = Field(..., description="Unix timestamp of detection")

    # Optional AIS-specific fields
    sog: Optional[float] = Field(None, description="Speed over ground (knots) from AIS")
    cog: Optional[float] = Field(None, description="Course over ground (degrees) from AIS")


class CollisionAlert(BaseModel):
    """Collision risk alert between two ships"""
    ship1_id: str = Field(..., description="ID of first ship")
    ship2_id: str = Field(..., description="ID of second ship")
    cpa_distance: float = Field(..., description="Closest Point of Approach distance in meters")
    time_to_cpa: float = Field(..., description="Time to CPA in seconds")
    risk_level: str = Field(..., description="Risk level: critical, high, medium, low")
    ship1_pos: Tuple[float, float] = Field(..., description="Current position of ship 1 [x, y]")
    ship2_pos: Tuple[float, float] = Field(..., description="Current position of ship 2 [x, y]")


class CameraStatus(BaseModel):
    """Status of camera system"""
    available: bool = Field(default=False, description="Whether camera is operational")
    lat: float = Field(default=1.2800, description="Camera latitude")
    lon: float = Field(default=103.8500, description="Camera longitude")
    fov_km: float = Field(default=2.0, description="Field of view in kilometers")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="System confidence 0-1")
    timestamp: float = Field(default=0.0, description="Last update timestamp")


class FrameOutput(BaseModel):
    """Complete output for a single frame"""
    frame_number: int = Field(..., description="Frame index in video")
    timestamp: float = Field(..., description="Unix timestamp")
    total_detections: int = Field(..., description="Number of ships detected in frame")
    ships: List[ShipDetection] = Field(..., description="List of detected/tracked ships")
    collision_alerts: List[CollisionAlert] = Field(
        default_factory=list,
        description="Collision risks detected"
    )
    video_frame: Optional[str] = Field(None, description="Base64 encoded JPEG frame")
    frame_timestamp: Optional[float] = Field(None, description="Timestamp of the encoded frame")


class UnifiedMessage(BaseModel):
    """WebSocket message sent to dashboards"""
    type: str = Field(default="frame", description="Message type: 'frame', 'status', etc.")
    frame_number: int = Field(..., description="Frame number")
    timestamp: float = Field(..., description="Timestamp")
    ships: List[ShipDetection] = Field(..., description="All ships (camera + AIS + LSTM)")
    camera_status: CameraStatus = Field(..., description="Camera system status")
    collision_alerts: List[CollisionAlert] = Field(
        default_factory=list,
        description="Active collision alerts"
    )
    video_frame: Optional[str] = Field(None, description="Base64 encoded JPEG frame")
    frame_timestamp: Optional[float] = Field(None, description="Timestamp of the encoded frame")


class VideoProcessingConfig(BaseModel):
    """Configuration for video processing"""
    video_path: str = Field(..., description="Path to input video file")
    camera_lat: float = Field(default=1.2800, description="Camera latitude")
    camera_lon: float = Field(default=103.8500, description="Camera longitude")
    fov_km: float = Field(default=2.0, description="Field of view in km")
    device: str = Field(default="cuda", description="Device: 'cuda' or 'cpu'")
    yolo_model: str = Field(default="yolov8m", description="YOLO model variant")
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    cv_match_radius_deg: float = Field(default=0.05, description="CV-to-AIS matching radius in degrees (~5.5km)")
    track_match_distance_pixels: float = Field(default=80.0, description="Track association distance in pixels for DeepOcSort")
