@echo off
title CashGen Automation Service
echo ==========================================
echo Starting CashGen Automation Service
echo ==========================================

set PYTHON=python\python.exe

REM Optional: auto-update from Git
git pull

REM Start FastAPI server locally
%PYTHON% -m uvicorn automation_agent:app --host 127.0.0.1 --port 8001

pause
