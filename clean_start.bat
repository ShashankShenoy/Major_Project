@echo off
echo =======================================================
echo   EXAM MODE: FORCE CLEANUP ^& STABLE STARTUP
echo =======================================================
echo.
echo [1/3] Killing all orphaned Python background processes...
echo This ensures no frozen models are hogging RAM or blocking ports.
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1

echo.
echo [2/3] Waiting for ports to clear...
timeout /t 3 /nobreak >nul

echo.
echo [3/3] Launching stable start script...
call "%~dp0start.bat"
