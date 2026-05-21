# Video Demo Guide for Your Presentation

## Quick Setup

### Step 1: Place Your Video
Copy your prerecorded Singapore port video to the project root:
```
MajorProject/
├── singapore_port_demo.mp4  ← Your video file here
├── run_video_demo.bat       ← Run this (Windows)
├── run_video_demo.sh        ← Or this (Mac/Linux)
└── video_dashboard_streamer.py
```

### Step 2: Start Backend (Terminal 1)
```bash
cd ais_dashboard/backend
python -m uvicorn ais_backend_multi:app --reload
```
Expected output:
```
INFO:     Application startup complete
Uvicorn running on http://127.0.0.1:8000
```

### Step 3: Open Dashboard (Browser)
Open in a new browser tab:
```
http://localhost:5500/ais_dashboard/frontend/index.html
```

### Step 4: Stream Video to Map (Terminal 2)

**Windows:**
```bash
run_video_demo.bat singapore_port_demo.mp4
```

**Mac/Linux:**
```bash
bash run_video_demo.sh singapore_port_demo.mp4
```

**Or manually:**
```bash
python video_dashboard_streamer.py singapore_port_demo.mp4 \
    --lat 1.264 \
    --lon 103.84 \
    --speed 1.0
```

## What You'll See

The dashboard will display:

✅ **Ship Detections** - Blue circles on the map (from YOLO CV detection)
✅ **Real-time Tracking** - Ship IDs and positions update frame by frame  
✅ **LSTM Path Predictions** - Dashed lines showing predicted ship trajectories  
✅ **Ship Info Panel** - Speed, heading, and confidence on the right  
✅ **Analytics** - Fleet statistics updating in real-time  

## Options

### Adjust Playback Speed
```bash
# 2x faster
run_video_demo.bat singapore_port_demo.mp4
python video_dashboard_streamer.py singapore_port_demo.mp4 --speed 2.0

# 0.5x slower
python video_dashboard_streamer.py singapore_port_demo.mp4 --speed 0.5
```

### Different Location
If your video is from a different port:
```bash
# Hong Kong
python video_dashboard_streamer.py hongkong_port.mp4 --lat 22.28 --lon 114.17

# Shanghai
python video_dashboard_streamer.py shanghai_port.mp4 --lat 31.40 --lon 121.64

# Custom location
python video_dashboard_streamer.py video.mp4 --lat 35.5 --lon 140.1
```

## For Your Presentation

**Demo Flow:**
1. Start backend in terminal
2. Open dashboard in browser (positioned on screen)
3. Run video streamer
4. Watch ships appear and track on the map
5. Show the predicted paths (dashed lines) - this is your LSTM prediction
6. Show the analytics panel updating with detections
7. Toggle filters (Predicted Routes, Direction Arrows, etc.) to highlight different features

**Key Points to Highlight:**
- "CV detection running at inference time"
- "LSTM predicts next 20 positions for collision avoidance"
- "Real-time multi-source fusion on the map"
- "Collision detection alerts (if enabled)"

## Troubleshooting

**No ships appearing on map?**
- Check backend is running (see "Uvicorn running" message)
- Check console for CV detection output
- Verify camera coordinates match your video location

**Wrong coordinates?**
- Adjust `--lat` and `--lon` to match the port
- Use `--fov 5.0` for wider coverage

**Slow performance?**
- Reduce `--speed` (e.g., 0.5x)
- Close other browser tabs
- Check if model inference is CPU/GPU bottleneck

**ModuleNotFoundError?**
```bash
pip install websockets opencv-python ultralytics torch torchvision
```

## Output Files

The streamer generates:
- **Live map data** - Sent via WebSocket to dashboard
- **Detection JSON** - Saved to `output_results.json` (if needed)
- **Annotated video** - Saved to `output_annotated.mp4` (if needed)

---

**Ready to present? Run `run_video_demo.bat` and watch the magic happen! 🚀**
