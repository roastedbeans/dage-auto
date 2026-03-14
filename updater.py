"""
Background update checker — polls GitHub Releases API without blocking the UI.

Usage:
    updater.start_check(GITHUB_REPO, APP_VERSION)
    # later, on a QTimer tick:
    result = updater.poll()
    if result and result.get("available"):
        ...show dialog...
"""

import json
import threading
import urllib.error
import urllib.request

_result: dict | None = None
_done = threading.Event()


def _parse_version(tag: str) -> tuple:
    """Convert 'v1.0.6' or '1.0.6' to (1, 0, 6) for comparison."""
    try:
        return tuple(int(x) for x in tag.lstrip("v").split("."))
    except ValueError:
        return (0,)


def _check(repo: str, current_version: str) -> None:
    global _result
    try:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "dage-auto-updater"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        tag = data.get("tag_name", "")
        html_url = data.get("html_url", f"https://github.com/{repo}/releases")
        if _parse_version(tag) > _parse_version(current_version):
            _result = {"available": True, "version": tag, "url": html_url}
        else:
            _result = {"available": False}
    except Exception:
        _result = {"available": False}
    finally:
        _done.set()


def start_check(repo: str, current_version: str) -> None:
    """Start a background update check. Non-blocking."""
    global _result
    _result = None
    _done.clear()
    t = threading.Thread(target=_check, args=(repo, current_version), daemon=True)
    t.start()


def poll() -> dict | None:
    """Return the result dict when the check is done, or None if still in progress."""
    if _done.is_set():
        return _result
    return None
