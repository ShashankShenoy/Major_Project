#!/usr/bin/env python3
"""
DJI Drone Telemetry Extractor
Extracts GPS position, FOV, altitude, and other parameters from DJI drone footage
Outputs calibration data for maritime tracking system
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import subprocess

# DJI camera specs (focal length in mm, sensor size in mm)
DJI_SPECS = {
    "Phantom 4 Pro": {"focal_length": 24, "sensor_width": 13.2, "sensor_height": 8.8},
    "Phantom 4": {"focal_length": 24, "sensor_width": 13.2, "sensor_height": 8.8},
    "Air 2S": {"focal_length": 20, "sensor_width": 13.3, "sensor_height": 8.8},
    "Air 2": {"focal_length": 24, "sensor_width": 13.2, "sensor_height": 8.8},
    "Mini 2": {"focal_length": 24, "sensor_width": 13.2, "sensor_height": 8.8},
    "Mavic 3": {"focal_length": 24, "sensor_width": 13.2, "sensor_height": 8.8},
    "default": {"focal_length": 24, "sensor_width": 13.2, "sensor_height": 8.8},
}

VIDEO_RESOLUTION = {
    "1080p": {"width": 1920, "height": 1080},
    "2.7K": {"width": 2688, "height": 1512},
    "4K": {"width": 3840, "height": 2160},
    "default": {"width": 1920, "height": 1080},
}


def parse_dji_srt(srt_path: str) -> List[Dict]:
    """
    Parse DJI .srt telemetry file
    Format: [timestamp] Latitude: X Longitude: Y Altitude: Z Height: H Speed: S
    """
    telemetry_frames = []

    try:
        with open(srt_path, 'r') as f:
            content = f.read()

        # Split by frame blocks (separated by blank lines)
        frames = content.split('\n\n')

        for frame in frames:
            lines = frame.strip().split('\n')
            if len(lines) < 2:
                continue

            # Line 0: frame number
            # Line 1: timestamp (HH:MM:SS,mmm --> HH:MM:SS,mmm)
            # Line 2+: telemetry data

            try:
                timestamp_str = lines[1].split(' --> ')[0]
                telemetry_text = '\n'.join(lines[2:])

                # Extract GPS coordinates
                lat_match = re.search(r'Latitude:\s*([-\d.]+)', telemetry_text)
                lon_match = re.search(r'Longitude:\s*([-\d.]+)', telemetry_text)
                alt_match = re.search(r'Altitude:\s*([-\d.]+)', telemetry_text)
                height_match = re.search(r'Height:\s*([-\d.]+)', telemetry_text)
                yaw_match = re.search(r'Yaw:\s*([-\d.]+)', telemetry_text)
                pitch_match = re.search(r'Pitch:\s*([-\d.]+)', telemetry_text)
                roll_match = re.search(r'Roll:\s*([-\d.]+)', telemetry_text)
                speed_match = re.search(r'Speed:\s*([-\d.]+)', telemetry_text)

                frame_data = {
                    "timestamp": timestamp_str,
                    "latitude": float(lat_match.group(1)) if lat_match else None,
                    "longitude": float(lon_match.group(1)) if lon_match else None,
                    "altitude": float(alt_match.group(1)) if alt_match else None,
                    "height_agl": float(height_match.group(1)) if height_match else None,
                    "yaw": float(yaw_match.group(1)) if yaw_match else None,
                    "pitch": float(pitch_match.group(1)) if pitch_match else None,
                    "roll": float(roll_match.group(1)) if roll_match else None,
                    "speed": float(speed_match.group(1)) if speed_match else None,
                }

                if frame_data["latitude"] is not None and frame_data["longitude"] is not None:
                    telemetry_frames.append(frame_data)

            except (IndexError, ValueError) as e:
                continue

        return telemetry_frames

    except FileNotFoundError:
        print(f"SRT file not found: {srt_path}")
        return []


def calculate_horizontal_fov(focal_length_mm: float, sensor_width_mm: float) -> float:
    """Calculate horizontal field of view in degrees"""
    import math
    hfov = 2 * math.atan(sensor_width_mm / (2 * focal_length_mm))
    return math.degrees(hfov)


def calculate_ground_fov_km(altitude_m: float, hfov_deg: float) -> float:
    """Calculate ground coverage in km for given altitude and FOV"""
    import math
    altitude_km = altitude_m / 1000
    hfov_rad = math.radians(hfov_deg)
    ground_width_km = 2 * altitude_km * math.tan(hfov_rad / 2)
    return ground_width_km


def extract_video_metadata(video_path: str) -> Optional[Dict]:
    """Extract metadata from video file using ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate,duration',
            '-of', 'json',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get('streams'):
                stream = data['streams'][0]
                width = stream.get('width', 1920)
                height = stream.get('height', 1080)
                duration = float(stream.get('duration', 0))

                return {
                    "width": width,
                    "height": height,
                    "duration": duration,
                    "resolution": f"{width}x{height}"
                }
    except Exception as e:
        print(f"ffprobe error: {e}")

    return None


def generate_calibration_data(
    srt_path: str,
    video_path: str = None,
    drone_model: str = "default",
    resolution: str = "1080p"
) -> Dict:
    """
    Generate complete calibration data for maritime tracking system
    """

    # Parse telemetry
    telemetry = parse_dji_srt(srt_path)

    if not telemetry:
        print("❌ No valid telemetry data extracted from SRT file")
        return {}

    # Get drone specs
    specs = DJI_SPECS.get(drone_model, DJI_SPECS["default"])

    # Calculate FOV
    hfov = calculate_horizontal_fov(specs["focal_length"], specs["sensor_width"])

    # Get video metadata
    video_meta = None
    if video_path:
        video_meta = extract_video_metadata(video_path)

    # Extract key frames (start, middle, end)
    frame_indices = [0, len(telemetry) // 2, len(telemetry) - 1]
    key_frames = [telemetry[i] for i in frame_indices if i < len(telemetry)]

    # Calculate average position
    avg_lat = sum(f["latitude"] for f in telemetry) / len(telemetry)
    avg_lon = sum(f["longitude"] for f in telemetry) / len(telemetry)
    avg_altitude = sum(f["altitude"] for f in telemetry if f["altitude"]) / len([f for f in telemetry if f["altitude"]])
    avg_height_agl = sum(f["height_agl"] for f in telemetry if f["height_agl"]) / len([f for f in telemetry if f["height_agl"]])

    # Calculate FOV in km at average altitude
    fov_km = calculate_ground_fov_km(avg_height_agl, hfov)

    calibration = {
        "metadata": {
            "extraction_time": datetime.now().isoformat(),
            "drone_model": drone_model,
            "srt_file": srt_path,
            "video_file": video_path,
            "telemetry_frames": len(telemetry),
        },

        "camera_specs": {
            "focal_length_mm": specs["focal_length"],
            "sensor_width_mm": specs["sensor_width"],
            "sensor_height_mm": specs["sensor_height"],
            "horizontal_fov_degrees": round(hfov, 2),
        },

        "video_specs": video_meta or {},

        "drone_position": {
            "latitude": round(avg_lat, 6),
            "longitude": round(avg_lon, 6),
            "altitude_msl_m": round(avg_altitude, 1),
            "altitude_agl_m": round(avg_height_agl, 1),
        },

        "coverage": {
            "fov_km": round(fov_km, 2),
            "coverage_area_sqkm": round(fov_km ** 2, 2),
        },

        "key_frames": [
            {
                "timestamp": f["timestamp"],
                "lat": f["latitude"],
                "lon": f["longitude"],
                "altitude_m": f["altitude"],
                "height_agl_m": f["height_agl"],
                "yaw": f["yaw"],
                "pitch": f["pitch"],
                "roll": f["roll"],
                "speed_ms": f["speed"],
            }
            for f in key_frames
        ],

        "config_for_system": {
            "CAMERA_LAT": round(avg_lat, 4),
            "CAMERA_LON": round(avg_lon, 4),
            "FOV_KM": round(fov_km, 2),
            "ALTITUDE_M": round(avg_height_agl, 0),
            "CV_MATCH_RADIUS_DEG": round(fov_km / 111.0, 3),
        }
    }

    return calibration


def main():
    """Example usage"""
    import sys

    if len(sys.argv) < 2:
        print("DJI Telemetry Extractor")
        print("=" * 50)
        print("\nUsage:")
        print(f"  python {sys.argv[0]} <srt_file> [video_file] [drone_model]")
        print("\nExample:")
        print(f"  python {sys.argv[0]} DJI_0001.srt DJI_0001.mp4 'Air 2S'")
        print("\nSupported Drone Models:")
        for model in DJI_SPECS.keys():
            if model != "default":
                print(f"  - {model}")
        return

    srt_file = sys.argv[1]
    video_file = sys.argv[2] if len(sys.argv) > 2 else None
    drone_model = sys.argv[3] if len(sys.argv) > 3 else "default"

    print(f"\n📍 Extracting DJI telemetry...")
    print(f"   SRT file: {srt_file}")
    print(f"   Video file: {video_file}")
    print(f"   Drone model: {drone_model}\n")

    calibration = generate_calibration_data(srt_file, video_file, drone_model)

    if calibration:
        # Print summary
        print("✅ Telemetry Extracted Successfully\n")
        print("📊 Summary:")
        print(f"   Frames: {calibration['metadata']['telemetry_frames']}")
        print(f"   Drone Position: {calibration['drone_position']['latitude']}°, {calibration['drone_position']['longitude']}°")
        print(f"   Altitude AGL: {calibration['drone_position']['altitude_agl_m']}m")
        print(f"   FOV: {calibration['coverage']['fov_km']}km")
        print(f"   Coverage: {calibration['coverage']['coverage_area_sqkm']}km²\n")

        # Save JSON output
        output_file = Path(srt_file).stem + "_calibration.json"
        with open(output_file, 'w') as f:
            json.dump(calibration, f, indent=2)

        print(f"💾 Calibration saved to: {output_file}\n")

        # Print config
        print("🔧 System Config (copy to ais_backend_multi.py):")
        config = calibration["config_for_system"]
        for key, value in config.items():
            print(f"   {key} = {value}")
    else:
        print("❌ Failed to extract telemetry data")


if __name__ == "__main__":
    main()
