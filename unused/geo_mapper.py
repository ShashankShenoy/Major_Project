# geo_mapper.py
import cv2
import numpy as np
import os
from PIL import Image
from global_land_mask import globe


class GeoMapper:
    """
    Converts pixel positions from video into real GPS coordinates,
    detects the region, crops the world map, and checks land/water.
    """

    def __init__(self, camera_lat, camera_lon, map_path, fov_km=5.0):
        """
        camera_lat, camera_lon : GPS of the camera
        map_path               : path to world map image
        fov_km                 : how many km the camera can see
        """
        self.camera_lat = camera_lat
        self.camera_lon = camera_lon
        self.fov_km     = fov_km

        print(f"Loading world map from {map_path}...")
        map_path = os.path.normpath(map_path)

        # PIL handles .tif more reliably than cv2
        try:
            pil_img        = Image.open(map_path).convert("RGB")
            self.world_map = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        except Exception as e:
            raise FileNotFoundError(f"Cannot load map: {e}")

        self.map_h, self.map_w = self.world_map.shape[:2]
        print(f"Map loaded: {self.map_w}x{self.map_h}")

        # Degrees per pixel in the world map
        self.deg_per_px_lon = 360.0 / self.map_w
        self.deg_per_px_lat = 180.0 / self.map_h

        # Homography matrix — set by calibrate()
        self.H = None

        # Crop the world map to local region
        self.local_map, self.crop_bounds = self._crop_region()

    def calibrate(self, pixel_pts, gps_pts):
        """
        One-time calibration using known points.
        pixel_pts: list of (px, py) in video frame
        gps_pts:   list of (lat, lon) for same points

        If no calibration points available, uses estimated
        scale based on fov_km.
        """
        if pixel_pts is not None and len(pixel_pts) >= 4:
            src      = np.float32(pixel_pts)
            dst      = np.float32(gps_pts)
            self.H, _ = cv2.findHomography(src, dst)
            print("Calibrated with manual points.")
        else:
            print("No calibration points — using estimated homography.")

    def pixel_to_gps(self, px, py, frame_w, frame_h):
        """
        Converts a pixel position to GPS.
        Uses homography if calibrated, otherwise estimates
        from camera GPS + field of view.
        """
        if self.H is not None:
            pt     = np.array([[[float(px), float(py)]]], dtype=np.float32)
            result = cv2.perspectiveTransform(pt, self.H)
            lat    = float(result[0][0][0])
            lon    = float(result[0][0][1])
        else:
            km_per_deg_lat = 111.0
            km_per_deg_lon = 111.0 * np.cos(np.radians(self.camera_lat))

            # Normalize pixel to -0.5 .. +0.5
            norm_x = (px - frame_w / 2) / frame_w
            norm_y = (py - frame_h / 2) / frame_h

            # Convert to degree offset from camera
            dlat = -(norm_y * self.fov_km) / km_per_deg_lat
            dlon =  (norm_x * self.fov_km) / km_per_deg_lon

            lat = self.camera_lat + dlat
            lon = self.camera_lon + dlon

        return round(lat, 6), round(lon, 6)

    def gps_to_map_pixel(self, lat, lon):
        """
        Converts GPS coordinates to pixel position
        on the CROPPED local map image.
        """
        min_lat, max_lat, min_lon, max_lon = self.crop_bounds

        norm_x = (lon - min_lon) / (max_lon - min_lon)
        norm_y = (max_lat - lat) / (max_lat - min_lat)  # y flipped

        h, w = self.local_map.shape[:2]
        px   = int(norm_x * w)
        py   = int(norm_y * h)

        return px, py

    def is_on_land(self, lat, lon):
        try:
            return globe.is_land(lat, lon)
        except Exception:
            return False

    def snap_to_water(self, lat, lon, radius=0.05, steps=36):
        """
        Searches outward from a land point to find
        the nearest water coordinate.
        """
        for r in np.arange(0.005, radius, 0.005):
            for angle in np.linspace(0, 360, steps):
                dlat = r * np.cos(np.radians(angle))
                dlon = r * np.sin(np.radians(angle))
                clat = lat + dlat
                clon = lon + dlon
                if not self.is_on_land(clat, clon):
                    return clat, clon
        return lat, lon

    def _crop_region(self, margin_deg=5.0):
        """
        Crops the world map to a region around the camera.
        margin_deg controls how much area is shown.
        """
        lat = self.camera_lat
        lon = self.camera_lon

        min_lat = max(lat - margin_deg,  -90)
        max_lat = min(lat + margin_deg,   90)
        min_lon = max(lon - margin_deg, -180)
        max_lon = min(lon + margin_deg,  180)

        # Convert bounds to world map pixel coordinates
        def lon_to_px(l): return int((l + 180) / 360 * self.map_w)
        def lat_to_py(l): return int((90 - l)  / 180 * self.map_h)

        x1 = max(0, lon_to_px(min_lon))
        x2 = min(self.map_w, lon_to_px(max_lon))
        y1 = max(0, lat_to_py(max_lat))
        y2 = min(self.map_h, lat_to_py(min_lat))

        cropped = self.world_map[y1:y2, x1:x2]

        # Resize to fixed display size
        cropped = cv2.resize(cropped, (800, 600))

        bounds = (min_lat, max_lat, min_lon, max_lon)
        print(f"Map region: lat {min_lat:.1f} to {max_lat:.1f}, "
              f"lon {min_lon:.1f} to {max_lon:.1f}")

        return cropped, bounds

    def get_region_name(self):
        """ Returns human readable region name from camera GPS. """
        lat = self.camera_lat
        lon = self.camera_lon

        if -10 <= lat <= 10 and 95 <= lon <= 145:
            return "Southeast Asia"
        elif 20 <= lat <= 45 and 100 <= lon <= 145:
            return "East Asia"
        elif 35 <= lat <= 70 and -10 <= lon <= 40:
            return "Europe"
        elif -35 <= lat <= 37 and -20 <= lon <= 55:
            return "Africa"
        elif 25 <= lat <= 75 and -170 <= lon <= -50:
            return "North America"
        elif -60 <= lat <= 15 and -85 <= lon <= -30:
            return "South America"
        elif -50 <= lat <= -10 and 110 <= lon <= 180:
            return "Oceania"
        elif lat > 60:
            return "Arctic"
        elif lat < -60:
            return "Antarctic"
        else:
            return "Open Ocean"