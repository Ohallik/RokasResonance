# Installer build

Everything in this folder is isolated from the main app.
The existing `setup.bat` / `run.bat` workflow still works unchanged — this is
an additional distribution path you can test in parallel.

## What this builds

`Install-RokasResonance.exe` — a single-file installer for Windows that:

- Installs to `%LOCALAPPDATA%\Programs\RokasResonance` (per-user, no admin needed)
- Creates a Start Menu shortcut (Desktop shortcut is opt-in)
- Bundles Python + all dependencies inside the `.exe` — end user does not need Python installed
- User data (profiles, database, settings) stays in `%LOCALAPPDATA%\RokasResonance`, so the copy-files build and the installed build share the same data on the same machine

## One-time prerequisites

1. **PyInstaller** — `build.bat` will offer to `pip install` it on first run
2. **Inno Setup 6** — download and install from <https://jrsoftware.org/isdl.php>

## Build

From this folder:

```
build.bat
```

That script runs PyInstaller, then Inno Setup. Output lands in
`installer/output/Install-RokasResonance.exe`.

If you haven't installed Inno Setup yet, `build.bat` still produces the
PyInstaller bundle at `installer/dist/RokasResonance/` — you can run
`RokasResonance.exe` directly from there to test the bundled app without
an installer.

## Test the installer

Just run `output\Install-RokasResonance.exe`.

Because the installer isn't code-signed, **Windows SmartScreen will show an
"unknown publisher" warning on first launch**. On your own test machines:
click *More info* → *Run anyway*. For wider distribution, either:

- Buy a code-signing certificate (~$100–400/yr), or
- Ask district IT to push it through Intune / SCCM as an approved app
  (they can whitelist the publisher for managed devices)

## Nothing touched in the main project

- `setup.bat` / `run.bat` — untouched
- `main.py`, source files — untouched
- Project root — unchanged
- `profiles.json`, `*.db` in the source tree — not read by the installed build
  (it only reads from `%LOCALAPPDATA%\RokasResonance`)

You can delete the entire `installer/` folder at any time without affecting the
rest of the app.
