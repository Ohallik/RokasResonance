# -*- mode: python ; coding: utf-8 -*-
"""
Debug variant of the PyInstaller spec — identical to RokasResonance.spec
except:
  - console=True (opens a cmd-style window alongside the app so all stdout /
    stderr / bootloader errors are visible)
  - debug="imports" (PyInstaller bootloader prints every module it loads,
    which is exactly what you need when the app dies before Python reaches
    main.py)
  - Output folder is RokasResonance-debug so it doesn't clobber the normal
    build.

Build (from the installer/ folder):
    pyinstaller --clean --noconfirm RokasResonance-debug.spec

Then copy dist/RokasResonance-debug/ to the VM and double-click
RokasResonance-debug.exe.  A black console window will open — any crash,
missing DLL, bootloader error, or Python traceback shows up there.
"""

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))

block_cipher = None

datas = [
    (os.path.join(PROJECT_ROOT, "assets"), "assets"),
    (os.path.join(PROJECT_ROOT, "Getting_Started.txt"), "."),
    (os.path.join(PROJECT_ROOT, "User_Guide.txt"), "."),
]
datas += collect_data_files("ttkbootstrap")

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
    excludes=[
        "homr", "torch", "torchvision", "cv2", "skimage", "shapely", "music21",
        "scipy", "matplotlib", "numpy", "pandas", "sympy",
        "pytest", "IPython", "notebook", "jupyter", "jupyterlab",
        "sphinx", "tornado",
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
    name="RokasResonance-debug",
    debug="imports",       # <<< noisy bootloader: prints every import
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # <<< console window visible
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
    name="RokasResonance-debug",
)
