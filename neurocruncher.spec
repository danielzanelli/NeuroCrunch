# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build specification for NeuroCrunch
Usage: pyinstaller neurocruncher.spec
"""

block_cipher = None

a = Analysis(
    ['src/NeuroCrunch.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),  # Include all assets
        ('scripts', 'scripts'),  # Include bundled official analysis scripts
        ('version.json', '.'),  # Include version metadata for the updater
    ],
    hiddenimports=[
        'pyqtgraph',
        'PySide6',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
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
    icon='assets/icons/icon.ico',
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
