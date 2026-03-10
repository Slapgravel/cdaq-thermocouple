# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas = []
binaries = []
hiddenimports = []

# Collect all dependencies - added nitypes
for package in ['PyQt6', 'pyqtgraph', 'numpy', 'nidaqmx', 'nitypes']:
    try:
        tmp_ret = collect_all(package)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception as e:
        print(f"Warning: Could not collect {package}: {e}")

# Explicitly copy metadata for packages that need it
for package in ['nidaqmx', 'nitypes']:
    try:
        datas += copy_metadata(package)
    except Exception as e:
        print(f"Warning: Could not copy metadata for {package}: {e}")

# Add commonly missed hidden imports
hiddenimports += [
    # PyQt6
    'PyQt6.sip',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtSvg',
    
    # pyqtgraph
    'pyqtgraph',
    'pyqtgraph.graphicsItems',
    'pyqtgraph.widgets',
    
    # nidaqmx + nitypes
    'nidaqmx',
    'nidaqmx.constants',
    'nidaqmx.task',
    'nidaqmx.system',
    'nidaqmx.stream_readers',
    'nidaqmx.stream_writers',
    'nidaqmx._task_modules',
    'nidaqmx._task_modules.channels',
    'nidaqmx._task_modules.timing',
    'nidaqmx._task_modules.in_stream',
    'nidaqmx.scale',
    'nidaqmx.utils',
    'nidaqmx._base_interpreter',
    'nitypes',
    'nitypes.waveform',
    
    # importlib metadata
    'importlib.metadata',
    
    # Standard library
    'csv',
    'collections',
]

# Collect submodules
for package in ['nidaqmx', 'nitypes', 'pyqtgraph', 'PyQt6']:
    try:
        hiddenimports += collect_submodules(package)
    except Exception as e:
        print(f"Warning: Could not collect submodules for {package}: {e}")

# Remove duplicates
hiddenimports = list(set(hiddenimports))

a = Analysis(
    ['thermocouple_logger.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='ThermocoupleLogger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ThermocoupleLogger',
)