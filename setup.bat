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

echo Checking Python version ^(3.10+ required^)...
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.10 or newer is required.
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Found: %%v
    echo Please install Python 3.10 or newer from https://python.org
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Found: %%v
echo.

echo Upgrading pip...
python -m pip install --upgrade pip
echo.

echo Installing required packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: One or more packages failed to install.
    echo Check the output above for details.
    pause
    exit /b 1
)
echo.

echo ============================================
echo   Setup complete!
echo ============================================
echo.
echo Note: The OMR (music recognition) feature uses homr, which will
echo download ML models on first use. This requires an internet
echo connection for the initial run only. The download includes
echo PyTorch and related ML libraries, which may be several GB.
echo.
echo Launching Roka's Resonance...
echo.
python main.py
pause
