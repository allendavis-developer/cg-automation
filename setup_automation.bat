@echo off
echo ==========================================
echo Setting up CashGen Embedded Python Environment
echo ==========================================

set PYTHON=python\python.exe
set BROWSER_PATH=%~dp0python\local-browsers

REM Step 1: Check if pip exists before installing
echo Checking for pip...
%PYTHON% -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo pip not found, installing...
    %PYTHON% get-pip.py
) else (
    echo pip already installed.
)

REM Step 2: Upgrade pip
%PYTHON% -m pip install --upgrade pip

REM Step 3: Install dependencies
echo Installing dependencies from requirements.txt...
%PYTHON% -m pip install -r requirements.txt

REM Step 4: Install Playwright browsers to local path
echo Installing Playwright Chromium browser locally...
set PLAYWRIGHT_BROWSERS_PATH=%BROWSER_PATH%
%PYTHON% -m playwright install chromium

echo.
echo Setup complete! You can now run start_automation.bat
pause
