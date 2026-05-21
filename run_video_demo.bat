@echo off
REM run_video_demo.bat - Process prerecorded video on the map

setlocal enabledelayedexpansion

set VIDEO_FILE=%1
if "!VIDEO_FILE!"=="" set VIDEO_FILE=singapore_port_demo.mp4

set CAMERA_LAT=%2
if "!CAMERA_LAT!"=="" set CAMERA_LAT=1.264

set CAMERA_LON=%3
if "!CAMERA_LON!"=="" set CAMERA_LON=103.84

set SPEED=%4
if "!SPEED!"=="" set SPEED=1.0

echo.
echo ╔═══════════════════════════════════════════════════════╗
echo ║          MARITIME INTELLIGENCE - VIDEO DEMO            ║
echo ╠═══════════════════════════════════════════════════════╣
echo ║ Video: !VIDEO_FILE!
echo ║ Location: (!CAMERA_LAT!, !CAMERA_LON!)
echo ║ Playback speed: !SPEED!x
echo ╚═══════════════════════════════════════════════════════╝
echo.

if not exist "!VIDEO_FILE!" (
    echo ❌ Video file not found: !VIDEO_FILE!
    echo    Usage: run_video_demo.bat [video_path] [lat] [lon] [speed]
    echo    Example: run_video_demo.bat singapore_port.mp4 1.264 103.84 1.0
    pause
    exit /b 1
)

echo 📍 Make sure the backend is running:
echo    cd ais_dashboard\backend ^&^& python -m uvicorn ais_backend_multi:app --reload
echo.

echo ⏳ Starting video stream in 3 seconds...
echo    Open dashboard at: http://localhost:5500/ais_dashboard/frontend/index.html
echo.

timeout /t 3 /nobreak

python video_dashboard_streamer.py "!VIDEO_FILE!" ^
    --lat !CAMERA_LAT! ^
    --lon !CAMERA_LON! ^
    --speed !SPEED! ^
    --ws "ws://localhost:8000/ws"

pause
