@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python 3 is required. Install it from https://www.python.org/downloads/windows/
    echo Enable "Add python.exe to PATH" during setup, then run this file again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Preparing the app for first launch...
    py -3 -m venv .venv
    if errorlevel 1 goto failed
    .venv\Scripts\python.exe -m pip install --upgrade pip
    if errorlevel 1 goto failed
)

.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed

.venv\Scripts\python.exe main.py
if errorlevel 1 pause
exit /b

:failed
echo Setup failed. Check the message above and try again.
pause
exit /b 1
