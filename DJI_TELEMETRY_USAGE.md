# DJI Telemetry Extractor - Usage Guide

## Overview
This utility extracts GPS position, field of view (FOV), altitude, and orientation data from DJI drone footage. It outputs calibration parameters ready to integrate into the maritime tracking system.

## Input Files

### Required: DJI .SRT File
DJI drones record telemetry in subtitle (.srt) files alongside video:
- Format: `DJI_0001.srt` (same name as video, different extension)
- Location: Same directory as the video file
- Content: Frame-by-frame GPS, altitude, yaw/pitch/roll data

**Example SRT content:**
```
1
00:00:00,000 --> 00:00:00,033
Latitude: 1.28321 Longitude: 103.85421 Altitude: 45.2 Height: 45.1 Yaw: 0.0 Pitch: -65.0 Roll: 0.0 Speed: 0.0

2
00:00:00,033 --> 00:00:00,066
Latitude: 1.28325 Longitude: 103.85425 Altitude: 45.5 Height: 45.4 Yaw: 5.2 Pitch: -65.0 Roll: 1.1 Speed: 0.3
```

### Optional: Video File
For video metadata extraction (resolution, duration, frame rate):
- Used to validate and detect video specifications
- Requires `ffprobe` installed (part of FFmpeg)

## Supported Drone Models

```python
"Phantom 4 Pro"  # Professional drone
"Phantom 4"      # Consumer flagship
"Air 2S"         # High-res medium-range
"Air 2"          # Popular compact
"Mini 2"         # Ultra-portable
"Mavic 3"        # Latest pro model
"default"        # Generic specs (24mm, 13.2x8.8mm sensor)
```

## Usage

### Basic Usage (SRT only)
```bash
python dji_telemetry_extractor.py DJI_0001.srt
```

### With Video File
```bash
python dji_telemetry_extractor.py DJI_0001.srt DJI_0001.mp4
```

### Specify Drone Model
```bash
python dji_telemetry_extractor.py DJI_0001.srt DJI_0001.mp4 "Air 2S"
```

## Output

### File: `DJI_0001_calibration.json`

```json
{
  "metadata": {
    "extraction_time": "2026-05-19T10:30:45.123456",
    "drone_model": "Air 2S",
    "srt_file": "DJI_0001.srt",
    "telemetry_frames": 2400
  },
  
  "camera_specs": {
    "focal_length_mm": 20,
    "sensor_width_mm": 13.3,
    "sensor_height_mm": 8.8,
    "horizontal_fov_degrees": 84.3
  },
  
  "drone_position": {
    "latitude": 1.283214,
    "longitude": 103.854123,
    "altitude_msl_m": 45.3,
    "altitude_agl_m": 45.2
  },
  
  "coverage": {
    "fov_km": 2.12,
    "coverage_area_sqkm": 4.49
  },
  
  "key_frames": [
    {
      "timestamp": "00:00:00,000",
      "lat": 1.28321,
      "lon": 103.85421,
      "altitude_m": 45.2,
      "height_agl_m": 45.1,
      "yaw": 0.0,
      "pitch": -65.0,
      "roll": 0.0,
      "speed_ms": 0.0
    }
  ],
  
  "config_for_system": {
    "CAMERA_LAT": 1.2832,
    "CAMERA_LON": 103.8541,
    "FOV_KM": 2.12,
    "ALTITUDE_M": 45,
    "CV_MATCH_RADIUS_DEG": 0.019
  }
}
```

## Integration Steps (When Ready)

1. **Extract calibration:**
   ```bash
   python dji_telemetry_extractor.py drone_video.srt drone_video.mp4 "Air 2S"
   ```

2. **Review output:**
   - Check `config_for_system` section
   - Verify GPS coordinates match expected region

3. **Apply to system:**
   - Copy values from `config_for_system` to `ais_backend_multi.py`:
     ```python
     CAMERA_LAT = 1.2832
     CAMERA_LON = 103.8541
     FOV_KM = 2.12
     CV_MATCH_RADIUS_DEG = 0.019
     ```
   - Update `app.py` video source to point to drone video file

4. **Run system:**
   ```bash
   # Terminal 1: Backend
   python ais_backend_multi.py
   
   # Terminal 2: CV processor (with drone video)
   python app.py
   
   # Terminal 3: Frontend
   python -m http.server 3000
   ```

## Key Parameters Explained

| Parameter | Meaning | Unit |
|-----------|---------|------|
| `CAMERA_LAT` | Drone's latitude during flight | degrees |
| `CAMERA_LON` | Drone's longitude during flight | degrees |
| `FOV_KM` | Horizontal field of view coverage | km |
| `ALTITUDE_M` | Height above ground (AGL) | meters |
| `CV_MATCH_RADIUS_DEG` | Matching radius for CV→AIS linking | degrees |

## Common Issues

### ❌ "SRT file not found"
- Ensure SRT file is in the same directory as video
- DJI SRT files are created automatically when recording
- Some drones/firmware versions may not generate SRT files

### ❌ "No valid telemetry data extracted"
- Check SRT file format (may vary by drone model)
- Try with `drone_model="default"`
- Ensure latitude/longitude data is present

### ❌ ffprobe not found
- Install FFmpeg: https://ffmpeg.org/download.html
- Or provide video metadata manually

### ❌ Wrong GPS coordinates
- Verify SRT file contains actual flight data
- Check if drone was recording before takeoff
- Match drone model to specs in script

## Testing

For Singapore port testing:
```bash
# Assuming you have: singapore_port.srt + singapore_port.mp4
python dji_telemetry_extractor.py singapore_port.srt singapore_port.mp4 "Air 2S"

# Verify output shows Singapore coordinates (~1.28°N, 103.85°E)
```

## Next Steps

Once you have the calibration file:
1. Validate GPS coordinates match video content
2. Review FOV coverage - should match video field of view
3. When ready to integrate: copy `config_for_system` values to backend/frontend
4. Run full system test with prerecorded drone video

---

**Created:** Separate utility for drone telemetry extraction  
**Not yet integrated:** Into `ais_backend_multi.py` or `app.py`  
**Ready for:** Manual validation before system integration
