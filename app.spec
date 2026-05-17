# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_data_files

# Collect data files from stable_baselines3 (version.txt, etc.)
sb3_datas = collect_data_files('stable_baselines3')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include config folder with all YAML files
        ('config', 'config'),
        # Include stable_baselines3 data files
        *sb3_datas,
    ],
    hiddenimports=[
        'stable_baselines3',
        'stable_baselines3.common.policies',
        'stable_baselines3.common.vec_env',
        'stable_baselines3.ppo',
        'torch',
        'MetaTrader5',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
