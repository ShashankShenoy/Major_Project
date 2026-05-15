# # collision_detector.py
# """
# Collision Detection Module using Closest Point of Approach (CPA)

# Detects ships on collision courses by:
# 1. Computing CPA (minimum distance between trajectories)
# 2. Tracking time-to-collision (TTC)
# 3. Raising alerts when risk threshold exceeded
# """

# import numpy as np
# from collections import defaultdict
# from dataclasses import dataclass
# from typing import List, Tuple, Optional


# @dataclass
# class CollisionAlert:
#     """Data class for collision alerts"""
#     ship1_id: int
#     ship2_id: int
#     cpa_distance: float  # meters
#     time_to_cpa: float   # seconds
#     risk_level: str      # "low", "medium", "high", "critical"
#     ship1_pos: Tuple[float, float]
#     ship2_pos: Tuple[float, float]
    
#     def __str__(self):
#         return (f"⚠️ COLLISION ALERT: Ship {self.ship1_id} <-> Ship {self.ship2_id} | "
#                 f"CPA: {self.cpa_distance:.1f}m | TTC: {self.time_to_cpa:.1f}s | "
#                 f"Risk: {self.risk_level.upper()}")


# class CollisionDetector:
#     """
#     Detects collision risks between tracked ships.
    
#     Physics: Two objects collide if their trajectories pass within 
#     a safety distance at any point in time.
#     """
    
#     # Safety thresholds (in meters)
#     CPA_CRITICAL = 50    # < 50m = critical
#     CPA_HIGH = 100       # < 100m = high risk
#     CPA_MEDIUM = 200     # < 200m = medium risk
#     CPA_LOW = 500        # < 500m = low risk (informational)
    
#     # Time window for prediction (in seconds, assume 30fps)
#     PREDICTION_FRAMES = 300  # Look 10 seconds ahead
    
#     # Pixel to meters conversion (needs calibration for your area)
#     # For Singapore strait, roughly: 1 pixel ≈ 0.3-0.5 meters
#     PIXEL_TO_METER = 0.4
    
#     def __init__(self, fps=30.0, pixel_to_meter=None):
#         """
#         Initialize collision detector.
        
#         Args:
#             fps: Video frame rate
#             pixel_to_meter: Conversion factor (update based on your camera)
#         """
#         self.fps = fps
#         self.pixel_to_meter = pixel_to_meter or self.PIXEL_TO_METER
        
#         # Track active alerts to avoid duplicate warnings
#         self.active_alerts = defaultdict(dict)
#         self.alert_history = []
        
#         # Alert cooldown: don't repeat alerts for same pair within 30 frames
#         self.alert_cooldown = 30  # frames
    
#     def detect_collisions(self, ships: List[dict], frame_num: int) -> List[CollisionAlert]:
#         """
#         Check all pairs of ships for collision risk.
        
#         Args:
#             ships: List of ship dicts with keys:
#                    - id: ship ID
#                    - center: (x, y) position in pixels
#                    - heading: direction in degrees
#                    - speed: velocity in pixels/frame
#             frame_num: Current frame number
        
#         Returns:
#             List of CollisionAlert objects
#         """
#         alerts = []
        
#         # Check all pairs
#         for i in range(len(ships)):
#             for j in range(i + 1, len(ships)):
#                 ship1 = ships[i]
#                 ship2 = ships[j]
                
#                 alert = self._check_pair(ship1, ship2, frame_num)
#                 if alert:
#                     alerts.append(alert)
        
#         # Update active alerts
#         self._update_active_alerts(alerts, frame_num)
#         return alerts
    
#     def _check_pair(self, ship1: dict, ship2: dict, frame_num: int) -> Optional[CollisionAlert]:
#         """Check if two ships are on collision course"""
        
#         # Check alert cooldown to avoid spam
#         pair_key = (min(ship1['id'], ship2['id']), max(ship1['id'], ship2['id']))
#         last_alert_frame = self.active_alerts.get(pair_key, {}).get('frame', -self.alert_cooldown)
#         if frame_num - last_alert_frame < self.alert_cooldown:
#             return None  # Skip if recently alerted
        
#         # Extract position and velocity
#         pos1 = np.array(ship1['center'], dtype=float)
#         pos2 = np.array(ship2['center'], dtype=float)
        
#         # Convert heading + speed to velocity vector
#         vel1 = self._heading_speed_to_velocity(ship1['heading'], ship1['speed'])
#         vel2 = self._heading_speed_to_velocity(ship2['heading'], ship2['speed'])
        
#         # Compute CPA
#         cpa_distance, time_to_cpa = self._compute_cpa(
#             pos1, vel1, pos2, vel2, 
#             max_frames=self.PREDICTION_FRAMES
#         )
        
#         # Check risk threshold
#         risk_level = self._assess_risk(cpa_distance)
        
#         if risk_level in ["high", "critical"]:  # Only alert on high risk or above
#             alert = CollisionAlert(
#                 ship1_id=ship1['id'],
#                 ship2_id=ship2['id'],
#                 cpa_distance=cpa_distance * self.pixel_to_meter,  # Convert to meters
#                 time_to_cpa=time_to_cpa / self.fps if time_to_cpa >= 0 else -1,  # Convert to seconds
#                 risk_level=risk_level,
#                 ship1_pos=tuple(pos1),
#                 ship2_pos=tuple(pos2)
#             )
#             # Record this alert
#             self.active_alerts[pair_key] = {'frame': frame_num, 'risk': risk_level}
#             return alert
        
#         return None
    
#     def _heading_speed_to_velocity(self, heading: float, speed: float) -> np.ndarray:
#         """
#         Convert heading (degrees) and speed to velocity vector.
        
#         Heading: 0° = East, 90° = North (standard maritime)
#         """
#         heading_rad = np.radians(heading)
#         vx = speed * np.cos(heading_rad)
#         vy = speed * np.sin(heading_rad)
#         return np.array([vx, vy])
    
#     def _compute_cpa(self, pos1: np.ndarray, vel1: np.ndarray,
#                      pos2: np.ndarray, vel2: np.ndarray,
#                      max_frames: int = 300) -> Tuple[float, int]:
#         """
#         Compute Closest Point of Approach between two moving objects.
        
#         Using relative velocity: Find when distance is minimized.
        
#         Returns:
#             (minimum_distance_in_pixels, frame_of_closest_approach)
#         """
        
#         # Relative position and velocity
#         relative_pos = pos2 - pos1
#         relative_vel = vel2 - vel1
        
#         # Time to CPA: minimize |relative_pos + t * relative_vel|
#         # d/dt[|r(t)|^2] = 0
#         # => t = -(r · v) / (v · v)
        
#         numerator = -np.dot(relative_pos, relative_vel)
#         denominator = np.dot(relative_vel, relative_vel)
        
#         if denominator < 1e-6:  # Ships moving in parallel or stationary
#             # Find minimum distance over time window
#             min_dist = np.linalg.norm(relative_pos)
#             min_frame = 0
#         else:
#             t_cpa = numerator / denominator
            
#             # Clamp to valid time range
#             if t_cpa < 0:
#                 t_cpa = 0  # Already passed closest point
#             elif t_cpa > max_frames:
#                 t_cpa = max_frames  # Beyond prediction window
            
#             # Distance at CPA
#             closest_pos = relative_pos + t_cpa * relative_vel
#             min_dist = np.linalg.norm(closest_pos)
#             min_frame = int(t_cpa)
        
#         return min_dist, min_frame
    
#     def _assess_risk(self, distance: float) -> str:
#         """Classify risk level based on CPA distance"""
#         if distance < self.CPA_CRITICAL:
#             return "critical"
#         elif distance < self.CPA_HIGH:
#             return "high"
#         elif distance < self.CPA_MEDIUM:
#             return "medium"
#         elif distance < self.CPA_LOW:
#             return "low"
#         else:
#             return "none"
    
#     def _update_active_alerts(self, new_alerts: List[CollisionAlert], frame_num: int):
#         """Track active alerts to avoid duplicate warnings"""
#         for alert in new_alerts:
#             key = (alert.ship1_id, alert.ship2_id)
#             self.active_alerts[key] = alert
#             self.alert_history.append((frame_num, alert))
    
#     def get_critical_alerts(self) -> List[CollisionAlert]:
#         """Get only critical/high risk alerts"""
#         return [a for a in self.active_alerts.values() 
#                 if a.risk_level in ["critical", "high"]]
    
#     def get_summary(self) -> dict:
#         """Get collision summary statistics"""
#         return {
#             "total_pairs_tracked": len(self.active_alerts),
#             "critical_alerts": len([a for a in self.active_alerts.values() if a.risk_level == "critical"]),
#             "high_risk": len([a for a in self.active_alerts.values() if a.risk_level == "high"]),
#             "total_alerts_history": len(self.alert_history)
#         }


# def integrate_collision_detection(ships: List[dict], collision_detector: CollisionDetector, 
#                                    frame_num: int) -> List[CollisionAlert]:
#     """
#     Helper function to integrate collision detection into video processing.
    
#     Usage in video_processor.py:
#     ```
#     collision_detector = CollisionDetector(fps=fps_value)
    
#     for frame in video:
#         ships = detector.detect(frame)
#         alerts = integrate_collision_detection(ships, collision_detector, frame_num)
        
#         for alert in alerts:
#             print(alert)
#             # Draw warning on frame
#     ```
#     """
#     return collision_detector.detect_collisions(ships, frame_num)


# collision_detector.py
"""
Collision Detection Module using Closest Point of Approach (CPA)

Detects ships on collision courses by:
1. Computing CPA (minimum distance between trajectories)
2. Tracking time-to-collision (TTC)
3. Raising alerts when risk threshold exceeded
"""

import numpy as np
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Tuple, Optional


@dataclass
class CollisionAlert:
    """Data class for collision alerts"""
    ship1_id: int
    ship2_id: int
    cpa_distance: float  # meters
    time_to_cpa: float   # seconds
    risk_level: str      # "low", "medium", "high", "critical"
    ship1_pos: Tuple[float, float]
    ship2_pos: Tuple[float, float]
    
    def __str__(self):
        return (f"⚠️ COLLISION ALERT: Ship {self.ship1_id} <-> Ship {self.ship2_id} | "
                f"CPA: {self.cpa_distance:.1f}m | TTC: {self.time_to_cpa:.1f}s | "
                f"Risk: {self.risk_level.upper()}")


class CollisionDetector:
    """
    Detects collision risks between tracked ships.
    
    Physics: Two objects collide if their trajectories pass within 
    a safety distance at any point in time.
    """
    
    # Safety thresholds (in meters)
    CPA_CRITICAL = 50    # < 50m = critical
    CPA_HIGH = 100       # < 100m = high risk
    CPA_MEDIUM = 200     # < 200m = medium risk
    CPA_LOW = 500        # < 500m = low risk (informational)
    
    # Time window for prediction (in seconds, assume 30fps)
    PREDICTION_FRAMES = 300  # Look 10 seconds ahead
    
    # Pixel to meters conversion (needs calibration for your area)
    # For Singapore strait, roughly: 1 pixel ≈ 0.3-0.5 meters
    PIXEL_TO_METER = 0.4
    
    def __init__(self, fps=30.0, pixel_to_meter=None):
        """
        Initialize collision detector.
        
        Args:
            fps: Video frame rate
            pixel_to_meter: Conversion factor (update based on your camera)
        """
        self.fps = fps
        self.pixel_to_meter = pixel_to_meter or self.PIXEL_TO_METER
        
        # Track active alerts to avoid duplicate warnings
        self.active_alerts = defaultdict(dict)
        self.alert_history = []
        
        # Alert cooldown: don't repeat alerts for same pair within 30 frames
        self.alert_cooldown = 30  # frames
    
    def detect_collisions(self, ships: List[dict], frame_num: int) -> List[CollisionAlert]:
        """
        Check all pairs of ships for collision risk.
        
        Args:
            ships: List of ship dicts with keys:
                   - id: ship ID
                   - center: (x, y) position in pixels
                   - heading: direction in degrees
                   - speed: velocity in pixels/frame
            frame_num: Current frame number
        
        Returns:
            List of CollisionAlert objects
        """
        alerts = []
        
        # Check all pairs
        for i in range(len(ships)):
            for j in range(i + 1, len(ships)):
                ship1 = ships[i]
                ship2 = ships[j]
                
                alert = self._check_pair(ship1, ship2, frame_num)
                if alert:
                    alerts.append(alert)
        
        # Update active alerts
        self._update_active_alerts(alerts, frame_num)
        return alerts
    
    def _check_pair(self, ship1: dict, ship2: dict, frame_num: int) -> Optional[CollisionAlert]:
        """Check if two ships are on collision course"""
        
        # Check alert cooldown to avoid spam
        pair_key = (min(ship1['id'], ship2['id']), max(ship1['id'], ship2['id']))
        last_alert_frame = self.active_alerts.get(pair_key, {}).get('frame', -self.alert_cooldown)
        if frame_num - last_alert_frame < self.alert_cooldown:
            return None  # Skip if recently alerted
        
        # Extract position and velocity
        pos1 = np.array(ship1['center'], dtype=float)
        pos2 = np.array(ship2['center'], dtype=float)
        
        # Convert heading + speed to velocity vector
        vel1 = self._heading_speed_to_velocity(ship1['heading'], ship1['speed'])
        vel2 = self._heading_speed_to_velocity(ship2['heading'], ship2['speed'])
        
        # Compute CPA
        cpa_distance, time_to_cpa = self._compute_cpa(
            pos1, vel1, pos2, vel2, 
            max_frames=self.PREDICTION_FRAMES
        )
        
        # Check risk threshold
        risk_level = self._assess_risk(cpa_distance)
        
        if risk_level in ["high", "critical"]:  # Only alert on high risk or above
            alert = CollisionAlert(
                ship1_id=ship1['id'],
                ship2_id=ship2['id'],
                cpa_distance=cpa_distance * self.pixel_to_meter,  # Convert to meters
                time_to_cpa=time_to_cpa / self.fps if time_to_cpa >= 0 else -1,  # Convert to seconds
                risk_level=risk_level,
                ship1_pos=tuple(pos1),
                ship2_pos=tuple(pos2)
            )
            # Record this alert
            self.active_alerts[pair_key] = {'frame': frame_num, 'risk': risk_level}
            return alert
        
        return None
    
    def _heading_speed_to_velocity(self, heading: float, speed: float) -> np.ndarray:
        """
        Convert heading (degrees) and speed to velocity vector.
        
        Heading: 0° = East, 90° = North (standard maritime)
        """
        heading_rad = np.radians(heading)
        vx = speed * np.cos(heading_rad)
        vy = speed * np.sin(heading_rad)
        return np.array([vx, vy])
    
    def _compute_cpa(self, pos1: np.ndarray, vel1: np.ndarray,
                     pos2: np.ndarray, vel2: np.ndarray,
                     max_frames: int = 300) -> Tuple[float, int]:
        """
        Compute Closest Point of Approach between two moving objects.
        
        Using relative velocity: Find when distance is minimized.
        
        Returns:
            (minimum_distance_in_pixels, frame_of_closest_approach)
        """
        
        # Relative position and velocity
        relative_pos = pos2 - pos1
        relative_vel = vel2 - vel1
        
        # Time to CPA: minimize |relative_pos + t * relative_vel|
        # d/dt[|r(t)|^2] = 0
        # => t = -(r · v) / (v · v)
        
        numerator = -np.dot(relative_pos, relative_vel)
        denominator = np.dot(relative_vel, relative_vel)
        
        if denominator < 1e-6:  # Ships moving in parallel or stationary
            # Find minimum distance over time window
            min_dist = np.linalg.norm(relative_pos)
            min_frame = 0
        else:
            t_cpa = numerator / denominator
            
            # Clamp to valid time range
            if t_cpa < 0:
                t_cpa = 0  # Already passed closest point
            elif t_cpa > max_frames:
                t_cpa = max_frames  # Beyond prediction window
            
            # Distance at CPA
            closest_pos = relative_pos + t_cpa * relative_vel
            min_dist = np.linalg.norm(closest_pos)
            min_frame = int(t_cpa)
        
        return min_dist, min_frame
    
    def _assess_risk(self, distance: float) -> str:
        """Classify risk level based on CPA distance"""
        if distance < self.CPA_CRITICAL:
            return "critical"
        elif distance < self.CPA_HIGH:
            return "high"
        elif distance < self.CPA_MEDIUM:
            return "medium"
        elif distance < self.CPA_LOW:
            return "low"
        else:
            return "none"
    
    def _update_active_alerts(self, new_alerts: List[CollisionAlert], frame_num: int):
        """Track active alerts to avoid duplicate warnings"""
        for alert in new_alerts:
            key = (alert.ship1_id, alert.ship2_id)
            self.active_alerts[key] = alert
            self.alert_history.append((frame_num, alert))
    
    def get_critical_alerts(self) -> List[CollisionAlert]:
        """Get only critical/high risk alerts"""
        return [a for a in self.active_alerts.values() 
                if a.risk_level in ["critical", "high"]]
    
    def get_summary(self) -> dict:
        """Get collision summary statistics"""
        return {
            "total_pairs_tracked": len(self.active_alerts),
            "critical_alerts": len([a for a in self.active_alerts.values() if a.risk_level == "critical"]),
            "high_risk": len([a for a in self.active_alerts.values() if a.risk_level == "high"]),
            "total_alerts_history": len(self.alert_history)
        }


def integrate_collision_detection(ships: List[dict], collision_detector: CollisionDetector, 
                                   frame_num: int) -> List[CollisionAlert]:
    """
    Helper function to integrate collision detection into video processing.
    
    Usage in video_processor.py:
    ```
    collision_detector = CollisionDetector(fps=fps_value)
    
    for frame in video:
        ships = detector.detect(frame)
        alerts = integrate_collision_detection(ships, collision_detector, frame_num)
        
        for alert in alerts:
            print(alert)
            # Draw warning on frame
    ```
    """
    return collision_detector.detect_collisions(ships, frame_num)
