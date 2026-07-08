# This Python file uses the following encoding: utf-8
"""NeuroCrunch - In-app Updater (Phase 6).

On startup the app checks GitHub Releases for a newer stable version and, if one
exists, offers to download and apply the platform-appropriate installer/asset.

The network-free pieces (version comparison, asset selection) are plain functions
so they can be unit-tested without hitting GitHub. The ``QThread`` wrappers keep
network I/O off the UI thread and report back via Qt signals, matching the pattern
used by ``script_runner.ScriptRunner``.

Asset naming must match Phase 7 CI (see .github/workflows/build.yml):
    NeuroCrunch-{version}-windows-setup.exe
    NeuroCrunch-{version}-macos.dmg
    NeuroCrunch-{version}-linux.AppImage
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import urllib.request
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

GITHUB_LATEST_RELEASE = 'https://api.github.com/repos/{repo}/releases/latest'
# GitHub requires a User-Agent header on API requests.
_USER_AGENT = 'NeuroCrunch-Updater'


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable, no Qt / no network)
# ---------------------------------------------------------------------------

def parse_version(value: str) -> tuple:
    """Parse a version string into a comparable tuple of ints.

    Tolerant of a leading ``v`` and of pre-release suffixes on a component
    (``1.2.0-rc1`` -> ``(1, 2, 0)``). Missing/garbage components become 0.
    """
    value = (value or '').strip().lstrip('vV')
    parts: List[int] = []
    for component in value.split('.'):
        digits = ''
        for ch in component:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def is_newer(latest: str, current: str) -> bool:
    """True if ``latest`` is a strictly greater version than ``current``."""
    return parse_version(latest) > parse_version(current)


def asset_suffix_for_platform(system: Optional[str] = None) -> str:
    """The release-asset filename suffix for the given (or current) OS."""
    system = (system or platform.system()).lower()
    if system.startswith('win'):
        return 'windows-setup.exe'
    if system == 'darwin':
        return 'macos.dmg'
    return 'linux.AppImage'


def select_asset(assets: List[Dict[str, Any]], system: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Pick the release asset matching this platform, or None if absent."""
    suffix = asset_suffix_for_platform(system)
    for asset in assets:
        if str(asset.get('name', '')).endswith(suffix):
            return asset
    return None


def read_current_version(version_json_path: str) -> Dict[str, Any]:
    """Load ``version.json`` ({version, channel, repo}); {} on any failure."""
    try:
        with open(version_json_path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def get_updates_dir() -> str:
    """Writable directory where downloaded update assets are stored."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        path = os.path.join(base, 'NeuroCrunch', 'updates')
    elif sys.platform == 'darwin':
        path = os.path.expanduser('~/Library/Application Support/NeuroCrunch/updates')
    else:
        path = os.path.expanduser('~/.config/NeuroCrunch/updates')
    os.makedirs(path, exist_ok=True)
    return path


def _fetch_latest_release(repo: str, timeout: float = 10.0) -> Dict[str, Any]:
    """GET the latest release JSON from the GitHub API."""
    url = GITHUB_LATEST_RELEASE.format(repo=repo)
    req = urllib.request.Request(url, headers={
        'User-Agent': _USER_AGENT,
        'Accept': 'application/vnd.github+json',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


# ---------------------------------------------------------------------------
# QThread workers
# ---------------------------------------------------------------------------

class UpdateChecker(QThread):
    """Checks GitHub Releases for a newer version. Emits exactly one signal.

    update_available(dict): {version, asset, html_url, notes} for a newer release
    up_to_date(): already on the latest (or newer) version
    error(str): the check failed (offline, rate-limited, no release, etc.)
    """
    update_available = Signal(dict)
    up_to_date = Signal()
    error = Signal(str)

    def __init__(self, repo: str, current_version: str, parent=None) -> None:
        super().__init__(parent)
        self.repo = repo
        self.current_version = current_version

    def run(self) -> None:
        try:
            data = _fetch_latest_release(self.repo)
        except Exception as exc:  # network/HTTP/JSON — surface, don't crash startup
            self.error.emit(f'No se pudo verificar actualizaciones: {exc}')
            return

        tag = str(data.get('tag_name', ''))
        if not tag:
            self.error.emit('La última versión no tiene tag_name.')
            return

        if is_newer(tag, self.current_version):
            self.update_available.emit({
                'version': tag,
                'asset': select_asset(data.get('assets', []) or []),
                'html_url': data.get('html_url', ''),
                'notes': data.get('body', ''),
            })
        else:
            self.up_to_date.emit()


class UpdateDownloader(QThread):
    """Downloads a release asset to the updates dir, reporting progress.

    progress(int): 0-100 (best effort; may stay at 0 if length unknown)
    finished_ok(str): absolute path to the downloaded file
    error(str): the download failed
    """
    progress = Signal(int)
    finished_ok = Signal(str)
    error = Signal(str)

    def __init__(self, url: str, filename: str, dest_dir: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.url = url
        self.filename = filename
        self.dest_dir = dest_dir or get_updates_dir()

    def run(self) -> None:
        dest_path = os.path.join(self.dest_dir, self.filename)
        try:
            req = urllib.request.Request(self.url, headers={'User-Agent': _USER_AGENT})
            with urllib.request.urlopen(req, timeout=30.0) as resp, open(dest_path, 'wb') as out:
                total = int(resp.headers.get('Content-Length', 0) or 0)
                downloaded = 0
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        self.progress.emit(min(int(downloaded / total * 100), 100))
        except Exception as exc:
            self.error.emit(f'Error al descargar la actualización: {exc}')
            return
        self.finished_ok.emit(dest_path)


def apply_update(asset_path: str) -> None:
    """Launch the downloaded asset to apply the update, then the app should quit.

    Per-OS behaviour:
      * Windows: run the Inno Setup installer silently; it replaces the running
        install and can relaunch. The app must exit right after this call.
      * Linux AppImage: mark executable and launch the new AppImage; the user
        replaces the old file manually (or a future step swaps it in place).
      * macOS: open the .dmg so the user can drag the new .app over the old one.
    """
    system = sys.platform
    if system == 'win32':
        # /SILENT runs without wizard pages; /CLOSEAPPLICATIONS lets Inno close us.
        # Use shell=True with quoted path to handle spaces in the path correctly.
        subprocess.Popen(f'"{asset_path}" /SILENT /CLOSEAPPLICATIONS', shell=True)
    elif system == 'darwin':
        subprocess.Popen(['open', asset_path])
    else:
        try:
            os.chmod(asset_path, 0o755)
        except OSError:
            pass
        subprocess.Popen([asset_path])
