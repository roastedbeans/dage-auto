# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Dage Auto standalone app
from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ['launcher.py'],
    pathex=[],
    datas=[
        ('aqw_auto.py', '.'),
        ('version.py', '.'),
        ('updater.py', '.'),
        *collect_data_files('certifi'),
    ],
    hiddenimports=[
        'aqw_auto',
        'updater',
        'version',
        'pyautogui',
        'pynput',
        'certifi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Dage Auto',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX causes random crashes on macOS (Ventura+)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No terminal window for desktop GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
