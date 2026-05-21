@echo off
REM Maritime Intelligence System — Unified Startup (Windows)
REM
REM  ┌──────────────────────────────────────────────────────────────┐
REM  │  This script ALWAYS starts both backends.                    │
REM  │  Mode selection (AIS-Only / Video / Hybrid) is done at:      │
REM  │  http://localhost:8000/hub.html  ← Hub makes the choice      │
REM  └──────────────────────────────────────────────────────────────┘

setlocal enabledelayedexpansion

REM ─────────────────────────────────────────────────────────────────────────
REM  Configuration — adjust if your paths or API key differ
REM ─────────────────────────────────────────────────────────────────────────
set AIS_API_KEY=9d0b24f784dfc1707e85d6aa588dd6254a7235d7
set VIDEO_PATH=C:\Users\91944\MajorProject\data\videos\input.avi
set DEVICE=cuda
set CAMERA_LAT=1.2800
set CAMERA_LON=103.8500
set FOV_KM=2.0
set AIS_ALLOW_INSECURE_SSL=true
set DISPLAY_UPDATE_SECONDS=1.0

REM AIS backend = pure AIS tracking only (no video).
REM Video is handled by the Marvis backend on port 5000.
set ENABLE_VIDEO_PROCESSING=false

set PROJECT_DIR=%~dp0
set BACKEND_DIR=%PROJECT_DIR%ais_dashboard\backend
set MARVIS_BACKEND_DIR=%PROJECT_DIR%marvis_dashboard\backend

echo.
echo [94m╔════════════════════════════════════════════════════════════╗[0m
echo [94m║     Maritime Intelligence System — Unified Startup        ║[0m
echo [94m╚════════════════════════════════════════════════════════════╝[0m
echo.

REM ── Python check ─────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [91m❌ ERROR: Python not found in PATH[0m
    pause
    exit /b 1
)

REM ── Dependency pre-check (fast import test, catches missing packages early) ──
echo [94mChecking Python dependencies...[0m
python -c "import fastapi, uvicorn, websockets, numpy, certifi, pydantic" >nul 2>&1
if errorlevel 1 (
    echo [93m⚠️  Some AIS backend packages are missing. Running install...[0m
    pip install -r "!BACKEND_DIR!\requirements.txt"
)
python -c "import flask, cv2, numpy" >nul 2>&1
if errorlevel 1 (
    echo [93m⚠️  Some Marvis backend packages are missing. Running install...[0m
    pip install -r "!MARVIS_BACKEND_DIR!\requirements.txt"
)
echo [92m✅ Dependencies OK[0m

REM ── Video file check (warning only — AIS-Only works without it) ──────────
if not exist "!VIDEO_PATH!" (
    echo [93m⚠️  WARNING: Video not found: !VIDEO_PATH![0m
    echo [93m   AIS-Only mode will work fine.[0m
    echo [93m   Video/Marvis backend will show an error when you select that mode.[0m
    echo.
) else (
    echo [92m✅ Video found: !VIDEO_PATH![0m
)

REM ─────────────────────────────────────────────────────────────────────────
REM  [1/2] AIS Backend — real-time AIS ship tracking (port 8000)
REM ─────────────────────────────────────────────────────────────────────────
echo.
echo [94m[1/2] Starting AIS Backend (port 8000)...[0m
cd /d "!BACKEND_DIR!"

if not exist "ais_backend_unified.py" (
    echo [91m❌ ERROR: ais_backend_unified.py not found in !BACKEND_DIR![0m
    pause
    exit /b 1
)

start "🌊 AIS Backend (8000)" cmd /k "set AIS_API_KEY=!AIS_API_KEY!&set ENABLE_VIDEO_PROCESSING=!ENABLE_VIDEO_PROCESSING!&set VIDEO_PATH=!VIDEO_PATH!&set DEVICE=!DEVICE!&set CAMERA_LAT=!CAMERA_LAT!&set CAMERA_LON=!CAMERA_LON!&set FOV_KM=!FOV_KM!&set AIS_ALLOW_INSECURE_SSL=!AIS_ALLOW_INSECURE_SSL!&echo AIS Backend starting...&python -m uvicorn ais_backend_unified:app --port 8000"

timeout /t 2 /nobreak

REM ─────────────────────────────────────────────────────────────────────────
REM  [2/2] Marvis Backend — prerecorded video + LSTM analytics (port 5000)
REM  Always started. If video is missing the Marvis dashboard will report it.
REM ─────────────────────────────────────────────────────────────────────────
echo [94m[2/2] Starting Marvis Backend (port 5000)...[0m
cd /d "!MARVIS_BACKEND_DIR!"

if not exist "marvis_api.py" (
    echo [93m⚠️  marvis_api.py not found — Video/Marvis mode unavailable.[0m
) else (
    start "📊 Marvis Backend (5000)" cmd /k "set VIDEO_PATH=!VIDEO_PATH!&set DEVICE=!DEVICE!&set DISPLAY_UPDATE_SECONDS=!DISPLAY_UPDATE_SECONDS!&echo Marvis Backend starting...&python marvis_api.py"
    timeout /t 2 /nobreak
)

echo.
echo [92m╔════════════════════════════════════════════════════════════╗[0m
echo [92m║            ✅ Both Backends Launched!                    ║[0m
echo [92m╚════════════════════════════════════════════════════════════╝[0m
echo.
echo [93m📌 ALL MODE SELECTION HAPPENS AT THE HUB:[0m
echo    Hub URL:        http://localhost:8000/hub.html
echo.
echo    ➤ Click "AIS-Only"       → live AIS ship tracking map
echo    ➤ Click "Video / Marvis" → prerecorded video + analytics
echo    ➤ Click "Hybrid"         → reserved for later
echo.
echo [93m⏳ Waiting 7s for backends to finish loading (torch + cv2 take time)...[0m
timeout /t 7 /nobreak

echo.
echo [93m🌐 Opening Hub in browser...[0m
start http://localhost:8000/hub.html

echo.
echo [93m⏹️  To stop: close both backend terminal windows (or Ctrl+C in each).[0m
echo.
