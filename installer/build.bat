@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   Roka's Resonance - Installer Build
echo ============================================
echo.

REM ── Step 1: check PyInstaller ─────────────────────────────────────
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller is not installed.
    set /p INSTALL_PI="Install pyinstaller now via pip? [Y/N]: "
    if /i "!INSTALL_PI!"=="Y" (
        python -m pip install pyinstaller
        if errorlevel 1 (
            echo ERROR: pip install pyinstaller failed.
            pause
            exit /b 1
        )
    ) else (
        echo Aborted. Install pyinstaller manually and re-run.
        pause
        exit /b 1
    )
)

REM ── Step 1b: extract version from main.py ─────────────────────────
REM main.py is the single source of truth. The line looks like:
REM     VERSION = "v0.9.0"
REM findstr finds the line; the for /f pulls the third whitespace-delimited
REM token (the quoted version), then we strip the surrounding quotes.
set "APP_VERSION="
for /f "tokens=3 delims= " %%a in ('findstr /b /c:"VERSION = " "..\main.py"') do set "APP_VERSION=%%a"
set "APP_VERSION=%APP_VERSION:"=%"
if "%APP_VERSION%"=="" (
    echo ERROR: could not read VERSION from ..\main.py
    pause
    exit /b 1
)
echo App version: %APP_VERSION%
echo.

REM ── Step 2: build the bundle ──────────────────────────────────────
echo.
echo Building PyInstaller bundle...
echo.
python -m PyInstaller --clean --noconfirm RokasResonance.spec
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

if not exist "dist\RokasResonance\RokasResonance.exe" (
    echo.
    echo ERROR: expected dist\RokasResonance\RokasResonance.exe was not produced.
    pause
    exit /b 1
)

echo.
echo Bundle built at: dist\RokasResonance\
echo.

REM ── Step 3: locate Inno Setup compiler ────────────────────────────
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
    echo.
    echo NOTE: Inno Setup 6 was not found in Program Files.
    echo       Download it from https://jrsoftware.org/isdl.php
    echo.
    echo       The PyInstaller bundle was built successfully — you can still
    echo       test it by running:
    echo           dist\RokasResonance\RokasResonance.exe
    echo.
    echo       Re-run build.bat after installing Inno Setup to produce the
    echo       single-file installer .exe.
    pause
    exit /b 0
)

echo Found Inno Setup: %ISCC%
echo.

REM ── Step 4: compile the installer ─────────────────────────────────
echo Compiling installer...
echo.
"%ISCC%" /DMyAppVersion=%APP_VERSION% installer.iss
if errorlevel 1 (
    echo.
    echo ERROR: Inno Setup compile failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Build complete
echo ============================================
echo.
echo Installer: output\Install-RokasResonance.exe
echo.
pause
