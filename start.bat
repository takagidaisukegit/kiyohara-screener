@echo off
title Kiyohara Screener

echo ============================================
echo  Kiyohara Screener - Starting...
echo ============================================
echo.

cd /d "%~dp0backend"

:: Create venv if not exists
if not exist "venv\Scripts\activate.bat" (
    echo [1/3] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Python not found. Please install Python 3.11+.
        pause
        exit /b 1
    )
)

:: Activate venv
call venv\Scripts\activate.bat

:: Install / update packages
echo [2/3] Installing packages...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install packages.
    pause
    exit /b 1
)

:: Open browser after 2 sec delay
echo [3/3] Starting server...
echo.
echo  URL : http://localhost:8000
echo  Stop: Ctrl+C
echo.
start /b cmd /c "timeout /t 2 >nul && start http://localhost:8000"

:: Start server
python main.py

pause
