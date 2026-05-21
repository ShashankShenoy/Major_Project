#!/bin/bash
# run_video_demo.sh - Process prerecorded video on the map

set -e

VIDEO_FILE="${1:-singapore_port_demo.mp4}"
CAMERA_LAT="${2:-1.264}"
CAMERA_LON="${3:-103.84}"
SPEED="${4:-1.0}"

echo "╔═══════════════════════════════════════════════════════╗"
echo "║          MARITIME INTELLIGENCE - VIDEO DEMO            ║"
echo "╠═══════════════════════════════════════════════════════╣"
echo "║ Video: $VIDEO_FILE"
echo "║ Location: ($CAMERA_LAT, $CAMERA_LON)"
echo "║ Playback speed: ${SPEED}x"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

if [ ! -f "$VIDEO_FILE" ]; then
    echo "❌ Video file not found: $VIDEO_FILE"
    echo "   Usage: ./run_video_demo.sh <video_path> [lat] [lon] [speed]"
    echo "   Example: ./run_video_demo.sh singapore_port.mp4 1.264 103.84 1.0"
    exit 1
fi

echo "📍 Make sure the backend is running:"
echo "   cd ais_dashboard/backend && python -m uvicorn ais_backend_multi:app --reload"
echo ""

echo "⏳ Starting video stream in 3 seconds..."
echo "   Open dashboard at: http://localhost:5500/ais_dashboard/frontend/index.html"
echo ""

sleep 3

python video_dashboard_streamer.py "$VIDEO_FILE" \
    --lat "$CAMERA_LAT" \
    --lon "$CAMERA_LON" \
    --speed "$SPEED" \
    --ws "ws://localhost:8000/ws"
