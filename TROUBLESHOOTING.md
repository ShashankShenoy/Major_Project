# Troubleshooting Guide - Fusion Dashboard

## Quick Diagnostics

**Check system health anytime:**
```
http://localhost:9000/api/diagnostics
```

This returns:
- ✅ Current configuration
- ✅ Runtime status (ships, clients, video processing)
- ✅ Critical issues & warnings
- ✅ Troubleshooting suggestions

---

## Common Issues & Solutions

### 1. **Video Not Loading**

**Symptom:** Video takes 30+ seconds or doesn't appear at all

**Root Causes:**
- `ENABLE_VIDEO_PROCESSING=false` in `start.bat` ❌
- Backend not switched to hybrid mode
- Video file doesn't exist
- ML models (YOLO) failing to load

**Solution:**
1. Check `/api/diagnostics` - look for these issues:
   ```json
   {
     "configuration": {
       "video_processing_enabled": true,  // Must be TRUE
       "current_mode": "hybrid",           // Must be hybrid
       "video_path": "...",
       "video_exists": true                // Must be TRUE
     }
   }
   ```

2. If `video_processing_enabled` is `false`:
   - Edit `start.bat`
   - Change: `set ENABLE_VIDEO_PROCESSING=false`
   - To: `set ENABLE_VIDEO_PROCESSING=true`
   - Restart backend

3. If `current_mode` is `ais-only`:
   - Select a video from the dropdown
   - Backend will auto-switch to hybrid mode
   - Wait 10-15s for ML models to load

4. If `video_exists` is `false`:
   - Video file missing from `data/videos/`
   - Add video file and refresh

---

### 2. **"Video takes 30 seconds to load"**

**Why it happens:**
- YOLO model initialization: ~5-10s
- DeepOcSort tracker setup: ~2-3s
- First frame processing: ~5s
- **Total: ~12-18s is normal**

**If it's taking >30s:**
1. Check GPU is being used: `DEVICE=cuda` in `start.bat`
2. Check model file exists: `fusion_dashboard/backend/yolov8n.pt`
3. Run diagnostics to see actual load time
4. Check CPU/GPU resources aren't maxed out

---

### 3. **"No ships appearing on map"**

**Could be:**
- AIS stream not connected
- Video not selected (mode stuck in ais-only)
- Map not loaded

**Check diagnostics:**
```json
{
  "runtime_status": {
    "ais_ships_tracked": 0,        // Should be > 0
    "video_processing_active": true // Should be true if hybrid
  },
  "health": {
    "ais_stream_connected": false   // Should be true
  }
}
```

**Solutions:**
- If `ais_stream_connected: false` → AIS API issue (check AIS_API_KEY)
- If `ais_ships_tracked: 0` → Camera location wrong, no ships in area
- If `video_processing_active: false` → Check error logs, may need to select video again

---

### 4. **"Backend crashes on startup"**

**Check logs for:**
- `❌ AIS_API_KEY not set` → Set env var before running
- `❌ Video directory missing` → Create `data/videos/` folder
- `❌ No video found` → Add a video file there

**Startup validation runs automatically** - check for these messages:
```
✅ Startup validation
   ✅ AIS_API_KEY configured
   ✅ Video Processing ENABLED
   ✅ Video library: 2 files found
```

---

### 5. **"Backend won't initialize hybrid mode"**

**Symptoms:**
- Mode stuck in "ais-only" 
- Video doesn't process even after selecting
- `/api/mode/hybrid` returns error

**Debug:**
1. Check `/api/diagnostics` → `critical_issues`
2. Check console logs for orchestrator errors
3. Try manually switching mode:
   ```bash
   curl -X POST http://localhost:9000/api/mode/hybrid
   ```

**Common causes:**
- YOLO model corrupted → delete `fusion_dashboard/backend/yolov8n.pt`, backend will re-download
- Not enough GPU memory → reduce `FOV_KM` in `start.bat`
- Model path wrong → check `video_orchestrator.py` line ~142

---

### 6. **"Video plays but no detections"**

**If CV ships = 0:**
- YOLO not detecting ships in video
- Confidence threshold too high (currently 0.5)
- Video has no ships to detect

**Solutions:**
1. Lower `CONFIDENCE_THRESHOLD` in `start.bat`:
   ```batch
   set CONFIDENCE_THRESHOLD=0.3
   ```

2. Verify YOLO is running:
   - Check `/api/diagnostics` → `video_frames_processed` (should increase)
   - Look for "📦 Loading YOLO model" in console

3. Check video has ships:
   - Play locally in VLC
   - Verify timestamp matches Singapore Strait (camera location)

---

### 7. **"High latency / Slow frame updates"**

**Check broadcast FPS:**
```json
{
  "configuration": {
    "broadcast_fps": 2  // Frames per second to dashboard
  }
}
```

**How to optimize:**
- Reduce `BROADCAST_FPS` in `start.bat` for lower bandwidth
- Reduce `FOV_KM` to process smaller area
- Lower `CONFIDENCE_THRESHOLD` to detect fewer objects

---

## Environment Variables Checklist

All set in `start.bat`:

```batch
✅ AIS_API_KEY=9d0b24...       (required)
✅ ENABLE_VIDEO_PROCESSING=true (critical for video)
✅ VIDEO_PATH=...              (will auto-select first video)
✅ DEVICE=cuda                 (cuda or cpu)
✅ CAMERA_LAT=1.24             (your camera location)
✅ CAMERA_LON=103.84
✅ FOV_KM=15.0                 (field of view in km)
✅ CONFIDENCE_THRESHOLD=0.5    (YOLO detection confidence)
```

---

## Performance Diagnostics

**Backend is running slow?** Check these metrics in `/api/diagnostics`:

```json
{
  "runtime_status": {
    "video_frames_processed": 150,     // Should increase over time
    "video_queue_size": 2,             // Should be small (< 5)
    "ais_ships_tracked": 45,           // Depends on location
    "connected_clients": 1             // Should match browser windows
  }
}
```

**Red flags:**
- `video_queue_size` constantly > 10 → Processing too slow, reduce quality
- `video_frames_processed` not increasing → Processing paused/crashed
- `connected_clients: 0` → WebSocket disconnected, check browser console

---

## Testing Without Video

**Want to test AIS-only mode first?**

1. Don't select a video (stay in "ais-only" mode)
2. Dashboard shows real AIS ships from Singapore Strait
3. This validates AIS streaming works
4. Then add video by selecting from dropdown

---

## Still Having Issues?

**Collect these for debugging:**

1. Full diagnostics:
   ```bash
   curl http://localhost:9000/api/diagnostics > diagnostics.json
   ```

2. Backend console output (last 50 lines)

3. Browser console errors (F12 → Console tab)

4. Exact steps to reproduce the issue

**Then check:**
- Did you restart backend after changing `start.bat`?
- Is `ENABLE_VIDEO_PROCESSING` actually `true`?
- Did video selection auto-switch mode to hybrid?

---

## System Architecture

```
Frontend (http://localhost:9000/hub.html)
    ↓ WebSocket /ws
    ↓
Backend (http://localhost:9000)
    ├─ AIS Stream (wss://stream.aisstream.io)
    ├─ Video Orchestrator (if hybrid mode)
    │  ├─ YOLO Detection
    │  ├─ DeepOcSort Tracking
    │  └─ LSTM Prediction
    └─ Unified Broadcaster (2 FPS to frontend)
```

**Key insight:** Video processing only runs when `current_mode="hybrid"`. Selecting a video auto-switches this.

---

## Reset/Recovery

**If everything breaks:**

1. Stop backend (Ctrl+C)
2. Delete video processing files:
   ```bash
   rm -r fusion_dashboard/backend/__pycache__
   ```
3. Clear CUDA cache (if applicable)
4. Restart: `.\start.bat`
5. Select mode 2 (Hybrid)
6. Select a video

**Nuclear option:**
- Revert `start.bat` to defaults
- Ensure `ENABLE_VIDEO_PROCESSING=true`
- Restart everything
