# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Roka's Resonance.

Usage (run from the installer/ folder):
    pyinstaller --clean --noconfirm RokasResonance.spec

Produces:
    installer/dist/RokasResonance/          - the bundled app folder
    installer/dist/RokasResonance/RokasResonance.exe

This file lives under installer/ so it stays isolated from the main project.
The existing setup.bat / run.bat workflow is untouched.
"""

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# The spec is loaded from installer/, so step up one level to reach the project root.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))

block_cipher = None

# Non-code resources shipped inside the bundle.
# Format: (source path on disk, destination folder inside the bundle)
datas = [
    (os.path.join(PROJECT_ROOT, "assets"), "assets"),
    (os.path.join(PROJECT_ROOT, "Getting_Started.txt"), "."),
    (os.path.join(PROJECT_ROOT, "User_Guide.txt"), "."),
]

# ttkbootstrap ships themes as package data files — pull them in.
datas += collect_data_files("ttkbootstrap")

# Modules that PyInstaller's static analysis tends to miss.
hiddenimports = [
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.font",
    "ttkbootstrap",
    "PIL._tkinter_finder",
    "anthropic",
    "openai",
    "httpx",
    "sqlite3",
]
hiddenimports += collect_submodules("ttkbootstrap")

a = Analysis(
    [os.path.join(PROJECT_ROOT, "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim heavy optional deps we don't actually ship in the default install.
    # Anything listed here that's actually needed at runtime will fail-fast on
    # import, so add back carefully if a feature breaks.
    #
    # The big offenders in a naive build are OMR deps (homr, cv2, scipy,
    # skimage, shapely) and music21's analysis deps (matplotlib, scipy).
    # OMR still requires an external Audiveris/homr install to run, so
    # excluding these just means OMR-triggered code paths fail fast with
    # an ImportError — the rest of the app is unaffected.
    excludes=[
        # OMR / ML stack
        "homr",
        "torch",
        "torchvision",
        "cv2",
        "skimage",
        "shapely",
        "music21",
        # Scientific stack (transitive only, not used by app code)
        "scipy",
        "matplotlib",
        "numpy",
        "pandas",
        "sympy",
        # Dev/notebook tooling
        "pytest",
        "IPython",
        "notebook",
        "jupyter",
        "jupyterlab",
        "sphinx",
        "tornado",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RokasResonance",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, "assets", "banner_logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RokasResonance",
)
