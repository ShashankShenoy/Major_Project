from typing import Dict, Optional, Tuple
from math import radians, cos, sin, asin, sqrt
from data_models import ShipDetection, SourceType


def calculate_distance_km(pos1: Tuple[float, float], pos2: Tuple[float, float]) -> float:
    """
    Calculate distance between two GPS positions in kilometers (Haversine formula)
    Args:
        pos1: (lat, lon)
        pos2: (lat, lon)
    Returns:
        Distance in kilometers
    """
    lon1, lat1 = pos1[1], pos1[0]
    lon2, lat2 = pos2[1], pos2[0]

    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    r = 6371  # Earth radius in km

    return c * r


def match_cv_to_ais(
    cv_detection: ShipDetection,
    ais_ships: Dict[int, Dict],
    match_radius_km: float = 5.5
) -> Optional[Tuple[int, float]]:
    """
    Match a camera detection to an AIS ship
    Args:
        cv_detection: Camera-detected ship
        ais_ships: Dictionary of AIS ships keyed by MMSI
        match_radius_km: Maximum distance for match in kilometers (~0.05 degrees)
    Returns:
        (mmsi, distance_km) if match found, else None
    """
    best_match = None
    best_distance = match_radius_km

    for mmsi, ais_ship in ais_ships.items():
        if not ais_ship.get("history") or len(ais_ship["history"]) < 1:
            continue

        # Get latest AIS position
        latest_pos = ais_ship["history"][-1]
        ais_lon, ais_lat = latest_pos[1], latest_pos[2]

        # Calculate distance
        distance = calculate_distance_km(
            (cv_detection.gps_lat, cv_detection.gps_lon),
            (ais_lat, ais_lon)
        )

        # Update best match if closer
        if distance < best_distance:
            best_distance = distance
            best_match = (mmsi, distance)

    return best_match


def enrich_cv_detection_with_ais(
    cv_detection: ShipDetection,
    ais_ship: Dict
) -> ShipDetection:
    """
    Enrich a CV detection with AIS data
    Args:
        cv_detection: Original camera detection
        ais_ship: AIS ship data
    Returns:
        Updated detection with AIS information
    """
    cv_detection.is_matched_to_ais = True
    cv_detection.matched_ais_mmsi = ais_ship.get("mmsi")
    cv_detection.mmsi = ais_ship.get("mmsi")
    cv_detection.name = ais_ship.get("name", cv_detection.name)

    # Update with AIS motion data if available
    if "sog" in ais_ship:
        cv_detection.sog = ais_ship["sog"]
    if "cog" in ais_ship:
        cv_detection.cog = ais_ship["cog"]
        cv_detection.heading = ais_ship["cog"]

    return cv_detection


class CVMatcher:
    """CV-to-AIS matching engine"""

    def __init__(self, match_radius_km: float = 5.5, verbose: bool = False):
        self.match_radius_km = match_radius_km
        self.verbose = verbose
        self.match_history = {}  # Track previous matches for consistency

    def match_detections(
        self,
        cv_detections: list[ShipDetection],
        ais_ships: Dict[int, Dict]
    ) -> list[ShipDetection]:
        """
        Match all CV detections to AIS ships
        Args:
            cv_detections: List of camera detections
            ais_ships: Dictionary of AIS ships
        Returns:
            List of detections with matches updated
        """
        matched_detections = []
        matched_mmsis = set()

        for cv_det in cv_detections:
            match_result = match_cv_to_ais(cv_det, ais_ships, self.match_radius_km)

            if match_result:
                mmsi, distance = match_result
                matched_mmsis.add(mmsi)

                # Enrich with AIS data
                cv_det = enrich_cv_detection_with_ais(cv_det, ais_ships[mmsi])
                cv_det.match_distance_km = distance

                if self.verbose:
                    print(f"[CVMatcher] Matched camera ship {cv_det.id} to AIS {mmsi} (distance: {distance:.2f} km)")
            else:
                cv_det.is_matched_to_ais = False
                if self.verbose:
                    print(f"[CVMatcher] No AIS match for camera ship {cv_det.id}")

            matched_detections.append(cv_det)

        return matched_detections

    def get_unmatched_camera_ships(self, detections: list[ShipDetection]) -> list[ShipDetection]:
        """Get only camera detections not matched to AIS"""
        return [d for d in detections if d.source == SourceType.CAMERA and not d.is_matched_to_ais]

    def get_matched_camera_ships(self, detections: list[ShipDetection]) -> list[ShipDetection]:
        """Get only camera detections matched to AIS"""
        return [d for d in detections if d.source == SourceType.CAMERA and d.is_matched_to_ais]
