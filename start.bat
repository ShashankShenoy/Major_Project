@echo off
setlocal enabledelayedexpansion

REM Set AIS API Key
set AIS_API_KEY=3493cfbd66acfed5d1ea65b5fb5c5353b88ef4b4

set PROJECT_DIR=%~dp0
set BACKEND_DIR=%PROJECT_DIR%ais_dashboard\backend
set FRONTEND_DIR=%PROJECT_DIR%ais_dashboard\frontend

echo.
echo Starting AIS Maritime Tracking Dashboard
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found
    pause
    exit /b 1
)

REM Start Backend
echo [1] Starting Backend on port 8000...
cd /d "%BACKEND_DIR%"
start "Backend" python ais_backend_multi.py
timeout /t 2 /nobreak

REM Start Frontend
echo [2] Starting Frontend on port 3000...
cd /d "%FRONTEND_DIR%"
start "Frontend" python -m http.server 3000

echo.
echo Services started!
echo - Frontend: http://localhost:3000
echo - Backend: ws://localhost:8000/ws
echo.
echo Close these windows to stop services.
pause
