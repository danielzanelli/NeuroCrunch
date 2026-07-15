# This Python file uses the following encoding: utf-8
"""Tests for the network-free logic in src/updater.py (Phase 6)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from updater import (  # noqa: E402
    parse_version,
    is_newer,
    asset_suffix_for_platform,
    select_asset,
    read_current_version,
    build_windows_update_script,
    _build_ssl_context,
)


# -- parse_version ---------------------------------------------------------

def test_parse_version_strips_leading_v():
    assert parse_version('v1.2.3') == (1, 2, 3)
    assert parse_version('1.2.3') == (1, 2, 3)


def test_parse_version_ignores_prerelease_suffix():
    assert parse_version('1.2.0-rc1') == (1, 2, 0)


def test_parse_version_handles_empty_and_garbage():
    assert parse_version('') == (0,)
    assert parse_version('x.y') == (0, 0)


# -- is_newer --------------------------------------------------------------

def test_is_newer_true_for_higher():
    assert is_newer('1.2.0', '1.1.9') is True
    assert is_newer('v0.2.0', '0.1.0') is True


def test_is_newer_false_for_equal_or_older():
    assert is_newer('0.1.0', '0.1.0') is False
    assert is_newer('0.1.0', '0.2.0') is False


def test_is_newer_numeric_not_lexical():
    # 0.10.0 must be newer than 0.2.0 (would fail under string comparison)
    assert is_newer('0.10.0', '0.2.0') is True


# -- asset suffix / selection ---------------------------------------------

def test_asset_suffix_per_platform():
    assert asset_suffix_for_platform('Windows') == 'windows-setup.exe'
    assert asset_suffix_for_platform('Darwin') == 'macos.dmg'
    assert asset_suffix_for_platform('Linux') == 'linux.AppImage'


def test_select_asset_matches_platform():
    assets = [
        {'name': 'NeuroCrunch-1.0.0-windows-setup.exe', 'browser_download_url': 'w'},
        {'name': 'NeuroCrunch-1.0.0-macos.dmg', 'browser_download_url': 'm'},
        {'name': 'NeuroCrunch-1.0.0-linux.AppImage', 'browser_download_url': 'l'},
    ]
    assert select_asset(assets, 'Windows')['browser_download_url'] == 'w'
    assert select_asset(assets, 'Darwin')['browser_download_url'] == 'm'
    assert select_asset(assets, 'Linux')['browser_download_url'] == 'l'


def test_select_asset_returns_none_when_absent():
    assert select_asset([{'name': 'notes.txt'}], 'Windows') is None
    assert select_asset([], 'Linux') is None


# -- read_current_version --------------------------------------------------

def test_read_current_version_ok(tmp_path):
    p = tmp_path / 'version.json'
    p.write_text(json.dumps({'version': '0.1.0', 'repo': 'x/y'}), encoding='utf-8')
    data = read_current_version(str(p))
    assert data['version'] == '0.1.0'
    assert data['repo'] == 'x/y'


def test_read_current_version_missing_returns_empty():
    assert read_current_version('/no/such/version.json') == {}


# -- SSL context -------------------------------------------------------------

def test_build_ssl_context_has_ca_certs():
    # Must trust at least one CA (OS store and/or certifi bundle), otherwise
    # every GitHub request would fail with CERTIFICATE_VERIFY_FAILED.
    ctx = _build_ssl_context()
    assert ctx.cert_store_stats()['x509_ca'] > 0


# -- Windows update script ---------------------------------------------------

def test_windows_update_script_waits_installs_and_relaunches():
    script = build_windows_update_script()
    assert script.startswith('@echo off')
    # Waits for the app process to be gone before installing over it.
    assert 'tasklist /FI "PID eq %NC_PID%"' in script
    # Silent install; no restart prompt.
    assert '"%NC_INSTALLER%" /SILENT /NORESTART /CLOSEAPPLICATIONS' in script
    # Relaunches the app (frozen exe, or interpreter + script in dev).
    assert 'start "" "%NC_APP_EXE%"' in script
    assert 'start "" "%NC_APP_EXE%" "%NC_APP_ARG%"' in script
    # Cleans up after itself.
    assert 'del "%~f0"' in script


def test_windows_update_script_is_pure_ascii():
    # The script is written with encoding='ascii'; paths travel via env vars
    # because cmd decodes .cmd files with the OEM codepage.
    build_windows_update_script().encode('ascii')
