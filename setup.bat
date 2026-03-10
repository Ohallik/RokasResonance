@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================
echo   Roka's Resonance - Setup
echo ============================================
echo.

echo Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    goto :python_missing
)

echo Checking Python version ^(3.10+ required^)...
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.10 or newer is required.
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Found: %%v
    goto :python_missing
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Found: %%v
goto :python_ok

:python_missing
echo.
echo Python 3.10 or newer is not installed or not found in PATH.
echo.
if exist "%~dp0python-3.14.3-amd64.exe" (
    echo A Python installer was found in this folder:
    echo   python-3.14.3-amd64.exe
    echo.
    echo Please run it to install Python, then run setup.bat again.
    echo IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    set /p LAUNCH_NOW="Launch the Python installer now? [Y/N]: "
    if /i "!LAUNCH_NOW!"=="Y" (
        echo Launching installer...
        start "" "%~dp0python-3.14.3-amd64.exe"
    )
) else (
    echo Please download and install Python 3.14 from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: Check "Add Python to PATH" during installation.
    echo After installing, run setup.bat again.
)
pause
exit /b 1

:python_ok
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

set /p CREATE_SHORTCUT="Create a desktop shortcut for Roka's Resonance? [Y/N]: "
if /i "!CREATE_SHORTCUT!"=="Y" (
    echo Creating desktop shortcut...
    python create_shortcut.py
    if errorlevel 1 (
        echo Warning: Shortcut creation failed. You can create it manually later
        echo by running: python create_shortcut.py
    )
    echo.
)

echo Launching Roka's Resonance...
echo.
python main.py
pause
