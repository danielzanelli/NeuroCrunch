# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build specification for NeuroCrunch
Usage: pyinstaller neurocruncher.spec
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# The bundled analysis scripts in scripts/ are shipped as data files and loaded at
# runtime via exec(). PyInstaller's static analysis never scans them, so the libraries
# they import must be collected explicitly here — otherwise a frozen build raises
# ModuleNotFoundError on the first script run. Keep this list in sync with the imports
# used by bundled scripts and with requirements.txt.
_script_datas, _script_binaries, _script_hiddenimports = [], [], []
for _pkg in ('numpy', 'pandas', 'cv2', 'tifffile', 'matplotlib', 'read_roi', 'jsonschema'):
    _d, _b, _h = collect_all(_pkg)
    _script_datas += _d
    _script_binaries += _b
    _script_hiddenimports += _h

# QtWebEngine / QtPdf back the PDF viewer (with a QWebEngineView fallback) and are not
# picked up automatically by PyInstaller.
_qt_hiddenimports = [
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineCore',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
]

# Reference the app icon only if it exists so a missing icon doesn't fail the build.
_icon_path = os.path.join('assets', 'icons', 'icon.ico')
_icon = _icon_path if os.path.isfile(_icon_path) else None

a = Analysis(
    ['src/NeuroCrunch.py'],
    pathex=[],
    binaries=_script_binaries,
    datas=[
        ('assets', 'assets'),  # Include all assets
        ('scripts', 'scripts'),  # Include bundled official analysis scripts
        ('schemas', 'schemas'),  # Include plugin manifest JSON Schema
        ('version.json', '.'),  # Include version metadata for the updater
    ] + _script_datas,
    hiddenimports=[
        'pyqtgraph',
        'PySide6',
    ] + collect_submodules('pyqtgraph') + _qt_hiddenimports + _script_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The app targets PySide6. If any other Qt binding is present in the build
    # environment (pyqtgraph/matplotlib will happily import PyQt5 if it finds it),
    # PyInstaller aborts because it refuses to freeze multiple Qt bindings. Exclude
    # the alternatives so only PySide6 is collected.
    excludes=['PyQt5', 'PyQt6', 'PySide2'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NeuroCrunch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True if you want a console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NeuroCrunch'
)
