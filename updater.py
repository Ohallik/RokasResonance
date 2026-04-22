"""
updater.py - Background update checker and installer for Roka's Resonance.
Checks GitHub Releases API; only notifies when a new *published* release exists.
"""

import json
import os
import shutil
import tempfile
import threading
import urllib.request
import zipfile

REPO = "Ohallik/RokasResonance"
_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

# Name of the installer asset attached to each GitHub release. When the app is
# running as a PyInstaller bundle, the update flow points users at this file
# (downloaded directly from the release) instead of the source zipball.
INSTALLER_ASSET_NAME = "Install-RokasResonance.exe"

# Folders/files to never overwrite — user data that lives in the app folder
_SKIP = {"profiles", "MusicPics", ".claude", "__pycache__", ".imported",
         "rokas_resonance.db", "Claude-Proxy.txt", "Claude-Proxy"}


def check_for_update(current_version: str, callback):
    """
    Spawns a daemon thread that checks for a newer GitHub release.
    If one is found, calls callback(latest_tag, html_url, zipball_url, installer_url).
    installer_url is the direct download URL for INSTALLER_ASSET_NAME if the
    release has it attached, otherwise None.
    Never raises — silently ignores network errors, rate limits, etc.
    """
    def _check():
        try:
            req = urllib.request.Request(
                _API_URL,
                headers={"User-Agent": "RokasResonance-UpdateChecker"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            latest_tag  = data.get("tag_name",    "").strip()
            html_url    = data.get("html_url",    "").strip()
            zipball_url = data.get("zipball_url", "").strip()
            installer_url = None
            for asset in (data.get("assets") or []):
                if asset.get("name") == INSTALLER_ASSET_NAME:
                    installer_url = (asset.get("browser_download_url") or "").strip() or None
                    break
            if latest_tag and _is_newer(latest_tag, current_version):
                callback(latest_tag, html_url, zipball_url, installer_url)
        except Exception:
            pass  # no internet, rate-limited, repo not found, etc.

    threading.Thread(target=_check, daemon=True).start()


def download_and_install(app_dir: str, zipball_url: str,
                         on_progress, on_done, on_error):
    """
    Downloads the release zip from GitHub and installs it over app_dir.
    All callbacks are invoked from the background thread — callers must
    marshal to the UI thread (e.g. with self.after(0, ...)).

    on_progress(message: str)
    on_done()
    on_error(message: str)
    """
    def _run():
        try:
            on_progress("Downloading update…")
            req = urllib.request.Request(
                zipball_url,
                headers={"User-Agent": "RokasResonance-Updater"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()

            on_progress("Extracting files…")
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = os.path.join(tmpdir, "update.zip")
                with open(zip_path, "wb") as f:
                    f.write(data)

                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(tmpdir)

                # GitHub extracts to "Owner-Repo-commithash/" subfolder
                subdirs = [
                    e for e in os.listdir(tmpdir)
                    if os.path.isdir(os.path.join(tmpdir, e))
                    and e not in ("__MACOSX",)
                    and e != "update.zip"
                ]
                if not subdirs:
                    raise RuntimeError("Unexpected archive structure — cannot find extracted folder.")
                src_dir = os.path.join(tmpdir, subdirs[0])

                on_progress("Installing files…")
                for item in os.listdir(src_dir):
                    if item in _SKIP:
                        continue
                    src = os.path.join(src_dir, item)
                    dst = os.path.join(app_dir, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)

            on_done()
        except Exception as e:
            on_error(str(e))

    threading.Thread(target=_run, daemon=True).start()


def _is_newer(latest: str, current: str) -> bool:
    """Return True if latest > current using semver-style comparison (vX.Y.Z)."""
    def parse(v):
        return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())
    try:
        return parse(latest) > parse(current)
    except Exception:
        return False
