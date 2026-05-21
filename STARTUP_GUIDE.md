# Quick Start Guide

## 🚀 Running the System

### Option 1: Windows (Easiest)
Simply **double-click** `start.bat` in the project root directory.

```
MajorProject/
  ├── start.bat          ← Double-click this
  ├── start.sh
  └── ais_dashboard/
```

The script will:
1. ✅ Start Backend (port 8000)
2. ✅ Start Frontend (port 3000)
3. ❓ Ask if you want CV Processor (port 8765)

### Option 2: Windows PowerShell / Git Bash
```bash
cd c:\Users\91944\MajorProject
bash start.sh
```

### Option 3: Linux / macOS
```bash
cd ~/path/to/MajorProject
chmod +x start.sh
./start.sh
```

---

## 📋 Prerequisites

### Required
- **Python 3.8+** installed and in PATH
- **AIS API Key** (get from: https://aisstream.io/)

### Optional
- **FFmpeg** (for video metadata extraction)
- **ffprobe** (included with FFmpeg)

---

## ⚙️ Configuration

### Set AIS API Key (Required!)

**Windows (PowerShell):**
```powershell
$env:AIS_API_KEY = "your_api_key_here"
.\start.bat
```

**Windows (Command Prompt):**
```cmd
set AIS_API_KEY=your_api_key_here
start.bat
```

**Linux / macOS:**
```bash
export AIS_API_KEY="your_api_key_here"
./start.sh
```

**Permanent (Windows):**
```powershell
[Environment]::SetEnvironmentVariable("AIS_API_KEY", "your_key", "User")
# Then restart terminal
```

---

## 🌐 Access Points

Once running:

| Service | URL | Purpose |
|---------|-----|---------|
| **Frontend** | http://localhost:3000 | Dashboard UI |
| **Backend** | ws://localhost:8000/ws | AIS data stream |
| **CV Processor** | ws://localhost:8765 | Video + detections (optional) |

---

## 📝 What Each Script Does

### `start.bat` (Windows)
- Auto-detects Python installation
- Starts 3 separate terminal windows (Backend, Frontend, CV)
- Auto-prompts for AIS API key if not set
- Handles port forwarding and cleanup

### `start.sh` (Bash)
- Works on Linux, macOS, Windows (WSL/Git Bash)
- Colored output for easy monitoring
- Graceful shutdown with Ctrl+C
- Real-time process monitoring
- Better logging and error handling

---

## ✅ Verification

### Backend Running?
```
Backend started (PID: 1234)
Ships tracked: 0
Connected to AISStream
```

### Frontend Running?
Visit http://localhost:3000 in your browser. You should see:
- Maritime tracking map
- Empty ship list (waiting for tracking area)
- Controls to start tracking

### CV Processor Running?
- Reads from prerecorded video
- Outputs detections to `outputs/results.json`
- Processes frames at ~15 FPS

---

## 🐛 Troubleshooting

### Backend won't start
```
Error: AIS_API_KEY environment variable is not set
```
→ Set your API key (see Configuration section above)

### Port already in use
```
Address already in use: ('0.0.0.0', 8000)
```
→ Kill existing process:
- Windows: `taskkill /F /IM python.exe`
- Linux/Mac: `pkill -f ais_backend_multi.py`
- Or change port in script

### Python not found
```
'python' is not recognized
```
→ Install Python 3.8+ from https://python.org  
→ Or use full path: `C:\Python311\python.exe`

### Frontend shows blank/white screen
→ Check browser console (F12)  
→ Verify backend is running on port 8000  
→ Clear browser cache (Ctrl+Shift+Delete)

---

## 🛑 Stopping Services

### Windows
- Close the terminal windows, or press Ctrl+C in each

### Linux / macOS / WSL
- Press Ctrl+C in the terminal running `start.sh`
- Script will auto-cleanup all processes

### Force Kill (if hung)
**Windows:**
```
taskkill /F /IM python.exe
```

**Linux/Mac:**
```
pkill -f python
```

---

## 📊 System Layout

```
Terminal 1: Backend (AIS Stream)
├── Connects to aisstream.io
├── Receives vessel data globally
├── Broadcasts to frontend via WebSocket
└── Listens on: ws://localhost:8000/ws

Terminal 2: Frontend (Dashboard)
├── Serves HTML/CSS/JS
├── Connects to backend
├── Displays map & controls
└── Available at: http://localhost:3000

Terminal 3 (Optional): CV Processor (Video)
├── Reads prerecorded video
├── Runs YOLOv8 detection
├── Generates detections JSON
└── Connects to ws://localhost:8765
```

---

## 🧪 Testing Workflow

1. **Start services**: `start.bat` or `./start.sh`
2. **Open frontend**: http://localhost:3000
3. **Wait for backend**: ~2 seconds for AIS connection
4. **Set tracking area**:
   - Click "Set Tracking Area"
   - Enter GPS: Lat 1.28, Lon 103.85 (Singapore)
   - Click "Start Tracking"
5. **Watch data flow**:
   - Ships should appear on map within 10 seconds
   - Check anomalies, data sources, etc.
6. **Optional - Enable camera**:
   - If CV processor running: Switch to [Live] or [Hybrid] view
   - Video + detections overlay should appear

---

## 📝 Notes

- **First run**: Backend takes ~5-10s to connect to AISStream
- **Video files**: Ensure prerecorded video has matching `.srt` telemetry file
- **API rate limits**: Free tier of aisstream.io may have connection limits
- **Performance**: Smooth with 50+ vessels; slower with 500+ (limit frontend rendering)

---

**Having issues?** Check the terminal output for error messages. Most common issues are:
1. ❌ Missing AIS_API_KEY → Set environment variable
2. ❌ Port already in use → Kill existing process or change port
3. ❌ Python not installed → Install Python 3.8+
4. ❌ Backend can't reach aisstream.io → Check internet connection
