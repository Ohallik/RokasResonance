@echo off
echo ============================================
echo   Roka's Resonance - Setup
echo ============================================
echo.
echo Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.10 or newer from https://python.org
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo Python found!
echo.
echo Installing required packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo ============================================
echo   Setup complete!
echo ============================================
echo.
echo Note: The OMR (music recognition) feature uses homr, which will
echo download ML models (~200MB) on first use. This requires an internet
echo connection for the initial run only.
echo.
echo Launching Roka's Resonance...
echo.
python main.py
pause
