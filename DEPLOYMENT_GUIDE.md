# Deployment Guide - Unified Maritime Intelligence System

## Two Modes of Operation

The system can run in two modes:

### 1. **HYBRID MODE** (Default)
Video Processing + AIS + LSTM Predictions

### 2. **AIS-ONLY MODE** 
Real-time AIS dashboard only (like the original system)

---

## Quick Start - Choose Your Mode

### **Option A: AIS-Only Mode (Easiest)**

Perfect for:
- Just viewing live AIS data
- No video processing needed
- Lightweight setup
- Works like the original ais_dashboard

**Start the backend:**
```bash
cd ais_dashboard/backend
export AIS_API_KEY="your_aisstream_key"
export ENABLE_VIDEO_PROCESSING="false"
python -m uvicorn ais_backend_unified:app --reload --port 8000
```

**Open dashboard:**
```
http://localhost:8000
```

**Expected:**
- Live AIS ships on map
- Real-time position updates (2 Hz)
- No camera feed or LSTM predictions
- Lightweight, fast, minimal dependencies

---

### **Option B: Hybrid Mode (Full System)**

Perfect for:
- Complete demo of all capabilities
- Camera detection + AIS matching
- LSTM predictions for unmatched ships
- Two coordinated dashboards

**Set up environment:**
```bash
cd ais_dashboard/backend

export AIS_API_KEY="your_aisstream_key"
export ENABLE_VIDEO_PROCESSING="true"
export VIDEO_PATH="/path/to/prerecorded/video.mp4"
export CAMERA_LAT="1.2800"
export CAMERA_LON="103.8500"
export FOV_KM="2.0"
export DEVICE="cuda"  # or "cpu"
```

**Start unified backend:**
```bash
python -m uvicorn ais_backend_unified:app --reload --port 8000
```

**In another terminal, start Marvis backend:**
```bash
cd marvis_dashboard/backend
python marvis_api.py
```

**Open dashboards:**
- **AIS Dashboard** (Primary): `http://localhost:8000`
- **Marvis Dashboard** (Secondary): `http://localhost:5000`

**Expected:**
- AIS Dashboard shows live map with both AIS ships and camera detections
- Marvis Dashboard shows analysis charts and LSTM predictions
- Real-time synchronized updates between both
- Processing as fast as GPU allows

---

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_VIDEO_PROCESSING` | `true` | Enable/disable video processing (`true`/`false`) |
| `AIS_API_KEY` | (required) | API key from AISStream |
| `VIDEO_PATH` | `path/to/video.mp4` | Path to prerecorded video (ignored if `ENABLE_VIDEO_PROCESSING=false`) |
| `CAMERA_LAT` | `1.2800` | Camera latitude (Singapore Strait) |
| `CAMERA_LON` | `103.8500` | Camera longitude |
| `FOV_KM` | `2.0` | Field of view in kilometers |
| `DEVICE` | `cuda` | Compute device: `cuda` or `cpu` |
| `CONFIDENCE_THRESHOLD` | `0.5` | YOLO confidence threshold (0-1) |
| `CV_MATCH_RADIUS_KM` | `5.5` | Distance threshold for CV-to-AIS matching |

---

## Mode Comparison

| Feature | AIS-Only | Hybrid |
|---------|----------|--------|
| Live AIS Data | ✅ | ✅ |
| Camera Detection | ❌ | ✅ |
| LSTM Predictions | ❌ | ✅ |
| CV-to-AIS Matching | ❌ | ✅ |
| Marvis Dashboard | ❌ | ✅ |
| GPU Required | ❌ | ✅ |
| Video File Needed | ❌ | ✅ |
| Setup Time | ~1 min | ~5 min |
| Performance | Lightweight | GPU-accelerated |

---

## Switching Between Modes

**To switch from AIS-Only to Hybrid:**
```bash
# Stop current backend (Ctrl+C)

# Set environment variables
export ENABLE_VIDEO_PROCESSING="true"
export VIDEO_PATH="/path/to/video.mp4"

# Restart
python -m uvicorn ais_backend_unified:app --reload --port 8000
```

**To switch from Hybrid to AIS-Only:**
```bash
# Stop current backend (Ctrl+C)

# Set environment variables
export ENABLE_VIDEO_PROCESSING="false"

# Restart
python -m uvicorn ais_backend_unified:app --reload --port 8000
```

---

## Testing Each Mode

### **Test AIS-Only Mode:**

1. Start backend with `ENABLE_VIDEO_PROCESSING=false`
2. Open `http://localhost:8000`
3. Should see live AIS ships appearing on map
4. Check console output:
   ```
   🚀 AIS Backend starting up...
      Video Processing: DISABLED (AIS-only mode)
      Ready: Live AIS only
   ```

### **Test Hybrid Mode:**

1. Start backend with `ENABLE_VIDEO_PROCESSING=true` and valid `VIDEO_PATH`
2. Open `http://localhost:8000`
3. Should see both AIS ships and camera detections
4. Open `http://localhost:5000` (Marvis)
5. Check console output:
   ```
   🚀 AIS Backend starting up...
      Video Processing: ENABLED
      Ready: Live AIS + Video + LSTM
   ✅ Video Orchestrator initialized
   🎬 Starting video processing: /path/to/video.mp4
   ```

---

## Health Check

Both modes support health check:
```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "ok",
  "video_processing": true,
  "ais_ships": 42,
  "connected_clients": 2
}
```

---

## Troubleshooting

### **AIS-Only Mode Issues:**

**Ships not appearing:**
- Verify `AIS_API_KEY` is valid
- Check bounding box (camera coordinates should contain ship traffic)
- Try moving the box or expanding FOV

**WebSocket disconnecting:**
- Check if port 8000 is in use: `lsof -i :8000`
- Browser console should show reconnection attempts

### **Hybrid Mode Issues:**

**No video detected:**
- Verify `VIDEO_PATH` points to actual video file
- Check file permissions
- Try absolute path instead of relative

**LSTM not predicting:**
- Check `models/lstm_model_trained.pt` exists
- If missing, system will use kinematic fallback
- Check console for LSTM initialization message

**High CPU/GPU usage:**
- Video processing is intensive - this is expected
- Reduce video resolution or model size if needed
- Hybrid mode uses GPU; ensure `DEVICE=cuda` if GPU available

---

## Production Deployment

For production:

1. Use **AIS-Only mode** for lower resource usage
2. Or use **Hybrid mode** with GPU for real-time processing
3. Configure appropriate environment variables
4. Use process manager (systemd, supervisor) to keep running
5. Set up log rotation for console output

---

## Architecture

```
┌─────────────────────────────────────────┐
│     AIS Backend (unified)               │
│     Listens: ws://localhost:8000/ws     │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────────────────────────┐   │
│  │  Persistent AIS Stream           │   │
│  │  (Always active)                 │   │
│  └──────────────────────────────────┘   │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │  Video Orchestrator              │   │
│  │  (Optional, if enabled)          │   │
│  │  - Video Processing              │   │
│  │  - LSTM Predictions              │   │
│  │  - CV-to-AIS Matching            │   │
│  └──────────────────────────────────┘   │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │  Unified Broadcaster             │   │
│  │  (Sends both AIS + CV data)      │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
         │               │
         ▼               ▼
    ┌─────────────┐  ┌──────────────┐
    │ AIS Display │  │ Marvis       │
    │ Dashboard   │  │ Dashboard    │
    │ (Primary)   │  │ (Optional)   │
    └─────────────┘  └──────────────┘
```

---

## Key Takeaways

- **AIS-Only**: Fast, simple, works immediately with just AIS key
- **Hybrid**: Full-featured, requires video processing setup
- **Single Backend**: One unified AIS backend handles both modes
- **Flexible**: Switch between modes by changing one environment variable
- **Same Data Format**: Both dashboards work seamlessly in either mode
