# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['frame.py'],
    pathex=[],
    binaries=[],
    datas=[('c:\\Users\\nguye\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\stable_baselines3\\version.txt', 'stable_baselines3'), ('close.png', '.')],
    hiddenimports=[
        'pandas._libs.tslibs.base',
        'pandas._libs.tslibs.nattype',
        'pandas._libs.tslibs.np_datetime',
        'pandas._libs.tslibs.timedeltas',
        'pandas._libs.tslibs.timestamps',
        'pandas._libs.skiplist',
        'pandas._libs.window.aggregations',
        'pandas.core.window.aggregations',
        'numpy.core._dtype_ctypes',
        'bottleneck',
        'numexpr',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=True,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [('v', None, 'OPTION')],
    name='frame',
    debug=True,
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
