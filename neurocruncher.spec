# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build specification for NeuroCrunch
Usage: pyinstaller neurocruncher.spec
"""

import os
import sys
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

# QtPdf backs the PDF viewer and is not picked up automatically by PyInstaller.
# QtWebEngine (a ~290 MB dependency) was only a PDF fallback; it is intentionally
# NOT bundled — NeuroCrunch.py imports it optionally and falls back gracefully.
_qt_hiddenimports = [
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
]

# Reference the app icon only if it exists so a missing icon doesn't fail the build.
# Windows/Linux use .ico; macOS .app bundles want .icns. Both fall back to None.
_icon_path = os.path.join('assets', 'icons', 'app_icon.ico')
_icon = _icon_path if os.path.isfile(_icon_path) else None
_icns_path = os.path.join('assets', 'icons', 'icon.icns')
_icns = _icns_path if os.path.isfile(_icns_path) else None

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
    excludes=[
        # The app targets PySide6. If any other Qt binding is present in the build
        # environment (pyqtgraph/matplotlib will import PyQt5 if it finds it),
        # PyInstaller aborts because it refuses to freeze multiple Qt bindings.
        'PyQt5', 'PyQt6', 'PySide2',
        # Unused packages pulled in transitively — trims the bundle. scipy (~73 MB)
        # is not imported by the app or any bundled script (matriz_pearson uses
        # pandas.corr, not scipy). Re-add it here AND to collect_all if a future
        # script needs it.
        'scipy', 'IPython', 'jedi', 'parso', 'pytest', '_pytest',
        'sphinx', 'notebook', 'ipykernel', 'nbconvert', 'docutils',
        # Qt modules the app never uses (it uses Widgets/Gui/Core, Multimedia,
        # WebEngine, Pdf, OpenGL, and pyqtgraph). Do NOT exclude QtQuick/QtQml/
        # QtPositioning/QtWebChannel/QtNetwork — QtWebEngine depends on them.
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtQuick3D',
        'PySide6.QtSensors', 'PySide6.QtSerialPort', 'PySide6.QtSerialBus',
        'PySide6.QtNfc', 'PySide6.QtBluetooth', 'PySide6.QtDesigner',
        'PySide6.QtUiTools', 'PySide6.QtHelp', 'PySide6.QtTest',
        'PySide6.QtRemoteObjects',
        # QtWebEngine (~290 MB: Qt6WebEngineCore.dll + Chromium resources) — dropped;
        # QtPdf renders PDFs and NeuroCrunch imports WebEngine optionally.
        'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineQuick',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Trim Qt's translation catalogs to Spanish/English only (the full set is ~48 MB
# of .qm files for every language Qt ships). Keeps qtbase/qtwebengine/etc. for es/en.
def _keep_data(dest):
    p = dest.replace('\\', '/').lower()
    # Keep only Spanish/English Qt translation catalogs (~48 MB otherwise).
    if '/pyside6/translations/' in p and p.endswith('.qm'):
        return ('_es.qm' in p) or ('_en.qm' in p)
    # WebEngine is not bundled — drop its Chromium resource blobs (~100 MB:
    # qtwebengine_*.pak, icudtl.dat under PySide6/resources).
    if 'qtwebengine' in p:
        return False
    if '/pyside6/resources/' in p:
        return False
    return True

a.datas = [d for d in a.datas if _keep_data(d[0])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NeuroCrunch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)

if sys.platform == 'darwin':
    coll = BUNDLE(
        exe,
        name='NeuroCrunch.app',
        icon=_icns,
        bundle_identifier=None,
    )
else:
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
