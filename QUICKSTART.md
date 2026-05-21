# Quick Start Guide - 1 Step Startup

## 🚀 Run Instantly

### **Windows:**
```bash
cd C:\Users\91944\MajorProject
start.bat
```

### **Linux/Mac:**
```bash
cd ~/MajorProject
chmod +x start.sh
./start.sh
```

**That's it!** API key is hardcoded. Just pick your mode.

---

## 📋 What You'll See

```
╔════════════════════════════════════════════════╗
║  Maritime Intelligence System - Startup        ║
║  Choose Mode: AIS-Only or Hybrid               ║
╚════════════════════════════════════════════════╝

AIS API Key:
   3493cfbd66acfed5d1... (hardcoded)

Select Mode:
[1] AIS-Only (Live AIS dashboard, lightweight, no video processing)
[2] Hybrid (Video + AIS + LSTM, full system, GPU recommended)

Enter choice [1 or 2]:
```

---

## 🎯 Choose Your Mode

### **Mode 1: AIS-Only** (Type `1` and Enter)
- ✅ Instant startup
- ✅ No video needed
- ✅ No GPU needed
- 📍 Dashboard: `http://localhost:8000`

### **Mode 2: Hybrid** (Type `2` and Enter)
You'll be asked:
```
Enter video file path: 
  /path/to/video.mp4

Compute device [cuda/cpu] (default: cuda): 
  cuda  [just press Enter for default]

Camera Configuration:
  Latitude (default: 1.2800): [press Enter]
  Longitude (default: 103.8500): [press Enter]
  FOV KM (default: 2.0): [press Enter]
```

Then:
- 📍 AIS Dashboard: `http://localhost:8000`
- 📍 Marvis Dashboard: `http://localhost:5000`

---

## ✅ Open Dashboard

After startup completes, click or paste URL in browser:

**AIS-Only:** `http://localhost:8000`

**Hybrid:** 
- Main: `http://localhost:8000`
- Analysis: `http://localhost:5000`

---

## 🔑 API Key

**Already hardcoded:** `3493cfbd66acfed5d1ea65b5fb5c5353b88ef4b4`

To use a different key:
- **Windows:** Edit `start.bat`, change line 5
- **Linux/Mac:** Edit `start.sh`, change line 11

Or set environment variable before running:
```bash
export AIS_API_KEY="your_new_key"
```

---

## ⚡ Features by Mode

**Mode 1 (AIS-Only):**
- Live AIS ships on map
- Real-time updates (2 Hz)
- Lightweight, fast
- Perfect for just AIS tracking

**Mode 2 (Hybrid):**
- AIS ships
- Camera detections
- LSTM predictions
- Two coordinated dashboards
- Collision detection

---

## 🛑 Stop Services

**Press `Ctrl+C`** in any window, or close the terminal windows.

---

## 📞 Troubleshooting

| Issue | Solution |
|-------|----------|
| "Python not found" | Install Python 3.8+ |
| "Port 8000 in use" | Kill process: `lsof -i :8000` |
| "No ships" | Check your internet/camera coords |
| "Video not found" | Use full path to video file |

---

**🎉 That's it! Just run the script and choose your mode.**
