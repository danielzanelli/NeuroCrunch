# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
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
import ssl
import subprocess
import sys
import urllib.request
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

try:
    import certifi
except ImportError:  # optional — the OS trust store alone usually suffices
    certifi = None

GITHUB_LATEST_RELEASE = 'https://api.github.com/repos/{repo}/releases/latest'
# GitHub requires a User-Agent header on API requests.
_USER_AGENT = 'NeuroCrunch-Updater'


def _build_ssl_context() -> ssl.SSLContext:
    """SSL context trusting both the OS store and certifi's Mozilla bundle.

    The default context only sees the OS trust store. On Windows, Python can
    only enumerate roots *already cached* in that store — Windows normally
    fetches missing roots on demand through its own crypto stack, which
    OpenSSL/Python cannot trigger — so machines that never cached the GitHub
    CA roots fail with CERTIFICATE_VERIFY_FAILED. Loading certifi on top
    fixes those, while keeping the OS store honors corporate proxy CAs.
    """
    context = ssl.create_default_context()
    if certifi is not None:
        try:
            context.load_verify_locations(cafile=certifi.where())
        except (OSError, ssl.SSLError):
            pass
    return context


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


def build_windows_update_script() -> str:
    """Batch script that waits for the app to exit, installs, and relaunches.

    Runs detached from the app (see ``_spawn_windows_updater``). The sequence is:

      1. Poll until the app process (NC_PID) is gone, capped at ~30s.
      2. Force-kill any lingering process with the app's image name (NC_IMAGE).
         The app is a PyInstaller *onefile* build, so a bootloader parent and a
         Python child both run as ``NeuroCrunch.exe``; the installer needs *both*
         gone or Inno's Restart Manager pops a blocking "files in use" dialog.
         This step guarantees the installed exe is unlocked before the installer
         runs, which is what previously required manual (crash-inducing) closing.
      3. Run the installer fully silent, suppressing any message box so nothing
         can block the unattended update.
      4. Relaunch the app and delete this script.

    ``NC_IMAGE`` is only set for frozen builds (see ``_spawn_windows_updater``);
    it is deliberately absent in dev so the fallback never kills ``python.exe``.

    All paths reach the script through environment variables (NC_PID,
    NC_INSTALLER, NC_APP_EXE, NC_IMAGE, optional NC_APP_ARG) instead of being
    inlined: cmd decodes .cmd files with the legacy OEM codepage, which would
    corrupt non-ASCII characters (e.g. accented Windows user names) in inline
    paths. ``ping`` is the sleep primitive because ``timeout`` refuses to run
    without an interactive console.
    """
    return '\n'.join([
        '@echo off',
        'set /a tries=0',
        ':wait',
        'set /a tries+=1',
        'if %tries% gtr 30 goto kill',
        'tasklist /FI "PID eq %NC_PID%" | findstr /C:"%NC_PID%" >nul',
        'if not errorlevel 1 (',
        '    ping -n 2 127.0.0.1 >nul',
        '    goto wait',
        ')',
        ':kill',
        'if defined NC_IMAGE taskkill /IM "%NC_IMAGE%" /F >nul 2>&1',
        'ping -n 3 127.0.0.1 >nul',
        ':install',
        '"%NC_INSTALLER%" /SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS',
        'ping -n 3 127.0.0.1 >nul',
        'if defined NC_APP_ARG (',
        '    start "" "%NC_APP_EXE%" "%NC_APP_ARG%"',
        ') else (',
        '    start "" "%NC_APP_EXE%"',
        ')',
        'del "%~f0"',
    ]) + '\n'


def _spawn_windows_updater(asset_path: str) -> None:
    """Launch the update script as a detached process, then return.

    The install + relaunch must happen *outside* this process: the installer
    (CloseApplications=yes) terminates NeuroCrunch to replace its exe, so any
    in-process code waiting on the installer is killed before it can relaunch
    the app. The caller must exit the app right after this returns.
    """
    script_path = os.path.join(get_updates_dir(), 'apply_update.cmd')
    with open(script_path, 'w', encoding='ascii', newline='\r\n') as fh:
        fh.write(build_windows_update_script())

    env = os.environ.copy()
    env['NC_PID'] = str(os.getpid())
    env['NC_INSTALLER'] = asset_path
    if getattr(sys, 'frozen', False):
        # PyInstaller bundle: sys.executable is the installed app exe, which
        # the installer replaces in place. NC_IMAGE enables the script's
        # force-kill fallback — safe here because the name is the app's own exe.
        env['NC_APP_EXE'] = sys.executable
        env['NC_IMAGE'] = os.path.basename(sys.executable)
        env.pop('NC_APP_ARG', None)
    else:
        # Dev run: sys.executable is python.exe, so NC_IMAGE stays unset —
        # force-killing every python.exe on the machine would be catastrophic.
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env['NC_APP_EXE'] = sys.executable
        env['NC_APP_ARG'] = os.path.join(base_dir, 'src', 'NeuroCrunch.py')
        env.pop('NC_IMAGE', None)

    # CREATE_NO_WINDOW (not DETACHED_PROCESS) keeps a hidden console that
    # tasklist/findstr/ping inherit — with no console at all, each of them
    # would flash open its own window.
    subprocess.Popen(
        ['cmd', '/c', script_path],
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


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
    with urllib.request.urlopen(req, timeout=timeout, context=_build_ssl_context()) as resp:
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
            self.error.emit(f'Could not check for updates: {exc}')
            return

        tag = str(data.get('tag_name', ''))
        if not tag:
            self.error.emit('The latest release has no tag_name.')
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
            with urllib.request.urlopen(req, timeout=30.0, context=_build_ssl_context()) as resp, \
                    open(dest_path, 'wb') as out:
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
            self.error.emit(f'Error downloading the update: {exc}')
            return
        self.finished_ok.emit(dest_path)


def apply_update(asset_path: str) -> None:
    """Launch the downloaded asset to apply the update, wait for completion, then relaunch.

    Per-OS behaviour:
      * Windows: spawn a detached helper script that waits for this process to
        exit, runs the Inno Setup installer silently, then restarts the app.
        The app must exit right after this call.
      * Linux AppImage: mark executable and launch the new AppImage; the user
        replaces the old file manually (or a future step swaps it in place).
      * macOS: open the .dmg so the user can drag the new .app over the old one.
    """
    system = sys.platform
    if system == 'win32':
        _spawn_windows_updater(asset_path)
    elif system == 'darwin':
        subprocess.Popen(['open', asset_path])
    else:
        try:
            os.chmod(asset_path, 0o755)
        except OSError:
            pass
        subprocess.Popen([asset_path])
