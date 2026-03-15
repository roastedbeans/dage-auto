"""
Background update checker and in-app updater for Dage Auto.

Flow:
  1. start_check()         — background thread hits GitHub Releases API
  2. poll()                — called on a QTimer tick; returns result when ready
  3. download_and_install()— background download + extract + shell-script swap
  4. download_progress()   — 0-100 int, poll on a QTimer tick
  5. download_finished()   — (done: bool, error: str)
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import tempfile
import threading
import urllib.request
import zipfile

# ── update check ──────────────────────────────────────────────────────────────

_result: dict | None = None
_done = threading.Event()


def _parse_version(tag: str) -> tuple:
    try:
        return tuple(int(x) for x in tag.lstrip("v").split("."))
    except ValueError:
        return (0,)


def _check(repo: str, current_version: str) -> None:
    global _result
    try:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "dage-auto-updater"})
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            data = json.loads(resp.read().decode())
        tag = data.get("tag_name", "")
        html_url = data.get("html_url", f"https://github.com/{repo}/releases")
        assets = data.get("assets", [])
        asset_url = next(
            (a["browser_download_url"] for a in assets if a["name"].endswith(".zip")),
            None,
        )
        if _parse_version(tag) > _parse_version(current_version):
            _result = {"available": True, "version": tag, "url": html_url, "asset_url": asset_url}
        else:
            _result = {"available": False}
    except Exception as e:
        _result = {"available": False, "error": str(e)}
    finally:
        _done.set()


def start_check(repo: str, current_version: str) -> None:
    """Start a background update check. Non-blocking."""
    global _result
    _result = None
    _done.clear()
    threading.Thread(target=_check, args=(repo, current_version), daemon=True).start()


def poll() -> dict | None:
    """Return result dict when done, or None if still in progress."""
    return _result if _done.is_set() else None


# ── in-app download + install ─────────────────────────────────────────────────

_dl_progress: int = 0
_dl_done = threading.Event()
_dl_error: str = ""


def download_progress() -> int:
    return _dl_progress


def download_finished() -> tuple[bool, str]:
    """Returns (finished, error_message)."""
    return _dl_done.is_set(), _dl_error


def download_and_install(asset_url: str, app_path: str) -> None:
    """
    Download the release zip, extract it, write a shell script that replaces
    the running .app bundle after this process exits, then signals done.
    """
    global _dl_progress, _dl_error
    _dl_progress = 0
    _dl_error = ""
    _dl_done.clear()

    def _worker() -> None:
        global _dl_progress, _dl_error
        try:
            tmp_dir = tempfile.mkdtemp(prefix="dage-update-")
            zip_path = os.path.join(tmp_dir, "update.zip")

            def _reporthook(count: int, block: int, total: int) -> None:
                global _dl_progress
                if total > 0:
                    _dl_progress = min(95, int(count * block * 100 / total))

            urllib.request.urlretrieve(asset_url, zip_path, _reporthook)
            _dl_progress = 96

            extract_dir = os.path.join(tmp_dir, "extracted")
            os.makedirs(extract_dir)
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(extract_dir)
            _dl_progress = 98

            new_app = os.path.join(extract_dir, "Dage Auto.app")
            if not os.path.isdir(new_app):
                _dl_error = "Could not find 'Dage Auto.app' in the update package."
                return

            # Shell script: waits for app to quit, swaps bundle, relaunches
            script = os.path.join(tmp_dir, "apply_update.sh")
            with open(script, "w") as f:
                f.write(
                    "#!/bin/bash\n"
                    "sleep 1\n"
                    f"rm -rf '{app_path}'\n"
                    f"cp -R '{new_app}' '{app_path}'\n"
                    f"xattr -cr '{app_path}'\n"      # clear macOS quarantine
                    f"open '{app_path}'\n"
                    f"rm -rf '{tmp_dir}'\n"
                )
            os.chmod(script, 0o755)
            subprocess.Popen(
                ["/bin/bash", script],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _dl_progress = 100

        except Exception as e:
            _dl_error = str(e)
        finally:
            _dl_done.set()

    threading.Thread(target=_worker, daemon=True).start()
