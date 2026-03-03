@echo off
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo An error occurred. If this is your first time running, use setup.bat instead.
    pause
)
