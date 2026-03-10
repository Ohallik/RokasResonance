"""
updater.py - Background update checker for Roka's Resonance.
Checks GitHub Releases API; only notifies when a new *published* release exists.
"""

import json
import threading
import urllib.request

REPO = "Ohallik/RokasResonance"
_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def check_for_update(current_version: str, callback):
    """
    Spawns a daemon thread that checks for a newer GitHub release.
    If one is found, calls callback(latest_tag, release_url) on the result.
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
            latest_tag = data.get("tag_name", "").strip()
            html_url = data.get("html_url", "").strip()
            if latest_tag and _is_newer(latest_tag, current_version):
                callback(latest_tag, html_url)
        except Exception:
            pass  # no internet, rate-limited, repo not found, etc.

    threading.Thread(target=_check, daemon=True).start()


def _is_newer(latest: str, current: str) -> bool:
    """Return True if latest > current using semver-style comparison (vX.Y.Z)."""
    def parse(v):
        return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())
    try:
        return parse(latest) > parse(current)
    except Exception:
        return False
