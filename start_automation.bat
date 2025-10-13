@echo off
title CashGen Automation Service
echo ==========================================
echo Starting CashGen Automation Service
echo ==========================================

set PYTHON=python\python.exe
set PLAYWRIGHT_BROWSERS_PATH=python\local-browsers

for /d %%D in ("%PLAYWRIGHT_BROWSERS_PATH%\chromium-*") do set "CHROMIUM_DIR=%%D"

REM === Start Chromium with GPU and smooth performance ===
start "" "%CHROMIUM_DIR%\chrome-win\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%~dp0\python\playwright_user_data" ^
  --no-first-run ^
  --no-default-browser-check ^
  --start-maximized ^
  --enable-gpu ^
  --enable-webgl ^
  --ignore-gpu-blocklist ^
  --enable-features=UseOzonePlatform ^
  --use-gl=desktop ^
  --disable-background-timer-throttling ^
  --disable-renderer-backgrounding ^
  --disable-backgrounding-occluded-windows ^
  --process-per-site


REM Start FastAPI server locally
%PYTHON% -m uvicorn automation_agent:app --host 127.0.0.1 --port 8001

pause
