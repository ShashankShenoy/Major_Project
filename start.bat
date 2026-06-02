@echo off
REM Maritime Intelligence System — Unified Startup (Windows)
REM
REM  ┌──────────────────────────────────────────────────────────────┐
REM  │  This script ALWAYS starts both backends.                    │
REM  │  Mode selection (AIS-Only / Video / Hybrid) is done at:      │
REM  │  http://localhost:8000/hub.html  ← Hub makes the choice      │
REM  └──────────────────────────────────────────────────────────────┘

setlocal enabledelayedexpansion
chcp 65001 >nul
for /F %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"

REM ─────────────────────────────────────────────────────────────────────────
REM  Configuration — adjust if your paths or API key differ
REM ─────────────────────────────────────────────────────────────────────────
set AIS_API_KEY=9d0b24f784dfc1707e85d6aa588dd6254a7235d7
set VIDEO_PATH=C:\Users\91944\MajorProject\data\videos\input.avi
set DEVICE=cuda
set CAMERA_LAT=1.2400
set CAMERA_LON=103.8400
set FOV_KM=15.0
set AIS_ALLOW_INSECURE_SSL=true
set DISPLAY_UPDATE_SECONDS=1.0

REM Enable video processing for fusion dashboard
set ENABLE_VIDEO_PROCESSING=true

set PROJECT_DIR=%~dp0
set BACKEND_DIR=%PROJECT_DIR%ais_dashboard\backend
set MARVIS_BACKEND_DIR=%PROJECT_DIR%marvis_dashboard\backend
set FUSION_BACKEND_DIR=%PROJECT_DIR%fusion_dashboard\backend

echo.
echo %ESC%[94m╔════════════════════════════════════════════════════════════╗%ESC%[0m
echo %ESC%[94m║     Maritime Intelligence System — Unified Startup        ║%ESC%[0m
echo %ESC%[94m╚════════════════════════════════════════════════════════════╝%ESC%[0m
echo.

REM ── Python check ─────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo %ESC%[91m❌ ERROR: Python not found in PATH%ESC%[0m
    pause
    exit /b 1
)

REM ── Dependency pre-check (fast import test, catches missing packages early) ──
echo %ESC%[94mChecking Python dependencies...%ESC%[0m
python -c "import fastapi, uvicorn, websockets, numpy, certifi, pydantic" >nul 2>&1
if errorlevel 1 (
    echo %ESC%[93m⚠️  Some AIS backend packages are missing. Running install...%ESC%[0m
    pip install -r "!BACKEND_DIR!\requirements.txt"
)
python -c "import flask, cv2, numpy" >nul 2>&1
if errorlevel 1 (
    echo %ESC%[93m⚠️  Some Marvis backend packages are missing. Running install...%ESC%[0m
    pip install -r "!MARVIS_BACKEND_DIR!\requirements.txt"
)
echo %ESC%[92m✅ Dependencies OK%ESC%[0m

REM ── Video file check (warning only — AIS-Only works without it) ──────────
if not exist "!VIDEO_PATH!" (
    echo %ESC%[93m⚠️  WARNING: Video not found: !VIDEO_PATH!%ESC%[0m
    echo %ESC%[93m   AIS-Only mode will work fine.%ESC%[0m
    echo %ESC%[93m   Video/Marvis backend will show an error when you select that mode.%ESC%[0m
    echo.
) else (
    echo %ESC%[92m✅ Video found: !VIDEO_PATH!%ESC%[0m
)

REM ─────────────────────────────────────────────────────────────────────────
REM  [1/2] AIS Backend — real-time AIS ship tracking (port 8000)
REM ─────────────────────────────────────────────────────────────────────────
echo.
echo %ESC%[94m[1/2] Starting AIS Backend (port 8000)...%ESC%[0m
cd /d "!BACKEND_DIR!"

if not exist "ais_backend_unified.py" (
    echo %ESC%[91m❌ ERROR: ais_backend_unified.py not found in !BACKEND_DIR!%ESC%[0m
    pause
    exit /b 1
)

start "🌊 AIS Backend (8000)" cmd /k "set AIS_API_KEY=!AIS_API_KEY!&set ENABLE_VIDEO_PROCESSING=!ENABLE_VIDEO_PROCESSING!&set VIDEO_PATH=!VIDEO_PATH!&set DEVICE=!DEVICE!&set CAMERA_LAT=!CAMERA_LAT!&set CAMERA_LON=!CAMERA_LON!&set FOV_KM=!FOV_KM!&set AIS_ALLOW_INSECURE_SSL=!AIS_ALLOW_INSECURE_SSL!&echo AIS Backend starting...&python -m uvicorn ais_backend_unified:app --port 8000"

ping -n 3 127.0.0.1 >nul

REM ─────────────────────────────────────────────────────────────────────────
REM  [2/2] Marvis Backend — prerecorded video + LSTM analytics (port 5000)
REM  Always started. If video is missing the Marvis dashboard will report it.
REM ─────────────────────────────────────────────────────────────────────────
echo %ESC%[94m[2/2] Starting Marvis Backend (port 5000)...%ESC%[0m
cd /d "!MARVIS_BACKEND_DIR!"

if not exist "marvis_api.py" (
    echo %ESC%[93m⚠️  marvis_api.py not found — Video/Marvis mode unavailable.%ESC%[0m
) else (
    start "📊 Marvis Backend (5000)" cmd /k "set VIDEO_PATH=!VIDEO_PATH!&set DEVICE=!DEVICE!&set DISPLAY_UPDATE_SECONDS=!DISPLAY_UPDATE_SECONDS!&echo Marvis Backend starting...&python marvis_api.py"
    ping -n 3 127.0.0.1 >nul
)

REM ─────────────────────────────────────────────────────────────────────────
REM  [3/3] Fusion Backend — hybrid mode combining AIS and video (port 9000)
REM ─────────────────────────────────────────────────────────────────────────
echo %ESC%[94m[3/3] Starting Fusion Backend (port 9000)...%ESC%[0m
cd /d "!FUSION_BACKEND_DIR!"

if not exist "fusion_backend.py" (
    echo %ESC%[93m⚠️  fusion_backend.py not found — Fusion mode unavailable.%ESC%[0m
) else (
    echo %ESC%[93mCreating auto-restart wrapper for Fusion Backend...%ESC%[0m
    echo @echo off > run_fusion.bat
    echo set AIS_API_KEY=!AIS_API_KEY!>> run_fusion.bat
    echo set ENABLE_VIDEO_PROCESSING=true>> run_fusion.bat
    echo set VIDEO_PATH=!VIDEO_PATH!>> run_fusion.bat
    echo set DEVICE=!DEVICE!>> run_fusion.bat
    echo set CAMERA_LAT=!CAMERA_LAT!>> run_fusion.bat
    echo set CAMERA_LON=!CAMERA_LON!>> run_fusion.bat
    echo set FOV_KM=!FOV_KM!>> run_fusion.bat
    echo set AIS_ALLOW_INSECURE_SSL=!AIS_ALLOW_INSECURE_SSL!>> run_fusion.bat
    echo :loop >> run_fusion.bat
    echo echo Fusion Backend starting... >> run_fusion.bat
    echo python -m uvicorn fusion_backend:app --port 9000 >> run_fusion.bat
    echo echo %%ESC%%[91m⚠️ FUSION BACKEND CRASHED! Auto-restarting in 2 seconds...%%ESC%%[0m >> run_fusion.bat
    echo timeout /t 2 /nobreak ^>nul >> run_fusion.bat
    echo goto loop >> run_fusion.bat
    
    start "🔀 Fusion Backend (9000)" cmd /c "run_fusion.bat"
    ping -n 3 127.0.0.1 >nul
)

echo.
echo %ESC%[92m╔════════════════════════════════════════════════════════════╗%ESC%[0m
echo %ESC%[92m║            ✅ All 3 Backends Launched!                   ║%ESC%[0m
echo %ESC%[92m╚════════════════════════════════════════════════════════════╝%ESC%[0m
echo.
echo %ESC%[93m📌 ALL MODE SELECTION HAPPENS AT THE HUB:%ESC%[0m
echo    Hub URL:        http://localhost:8000/hub.html
echo.
echo    ➤ Click "AIS-Only"       → live AIS ship tracking map
echo    ➤ Click "Video / Marvis" → prerecorded video + analytics
echo    ➤ Click "Hybrid"         → reserved for later
echo.
echo %ESC%[93m🚀 Fast startup enabled. Heavy ML models will load on-demand when Hybrid mode is selected.%ESC%[0m

echo.
echo %ESC%[93m🌐 Opening Hub in browser...%ESC%[0m
start http://localhost:8000/hub.html

echo.
echo %ESC%[93m⏹️  To stop: close both backend terminal windows (or Ctrl+C in each).%ESC%[0m
echo.
