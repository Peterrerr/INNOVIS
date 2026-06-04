# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None

# ---------------------------------------------------------------------------
# Icon — .icns on macOS, .ico on Windows (auto-converted from icon.png)
# ---------------------------------------------------------------------------
_root = Path(SPECPATH)
if sys.platform == "darwin":
    _icon = str(_root / "assets" / "icon.icns")
elif sys.platform == "win32":
    _ico_path = _root / "assets" / "icon.ico"
    _png_path = _root / "assets" / "icon.png"
    if not _ico_path.exists() and _png_path.exists():
        try:
            from PIL import Image
            img = Image.open(_png_path)
            img.save(str(_ico_path), format="ICO",
                     sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
            print(f"[spec] Created {_ico_path}")
        except Exception as e:
            print(f"[spec] Could not create icon.ico: {e}")
    _icon = str(_ico_path) if _ico_path.exists() else None
else:
    _icon = None

# ---------------------------------------------------------------------------

from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

# Heavy/native packages need explicit submodule + DLL collection because
# PyInstaller's static analysis misses lazy imports (skimage) and bundled
# shared libs (pyzbar, pylibdmtx ship .dll alongside their Python wheel).
_extra_hiddenimports = []
for _pkg in ("skimage", "sklearn", "joblib"):
    try:
        _extra_hiddenimports.extend(collect_submodules(_pkg))
    except Exception:
        pass

_extra_binaries = []
for _pkg in ("pyzbar", "pylibdmtx"):
    try:
        _extra_binaries.extend(collect_dynamic_libs(_pkg))
    except Exception:
        pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_extra_binaries,
    datas=[
        ('assets', 'assets'),
        ('config', 'config'),
    ],
    hiddenimports=[
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'cv2',
        'numpy',
        'pyzbar.pyzbar',
        'pylibdmtx.pylibdmtx',
        'skimage.feature',
        'sklearn.svm',
        'sklearn.preprocessing',
        'joblib',
    ] + _extra_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='INNOVIS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    name='INNOVIS',
)

# macOS .app bundle — Windows/Linux skip this block
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name='INNOVIS.app',
        icon=_icon,
        bundle_identifier='com.innovis.machinevision',
        info_plist={
            'NSCameraUsageDescription': 'INNOVIS requires camera access for machine vision inspection.',
            'CFBundleShortVersionString': '1.0.0',
            'CFBundleVersion': '1.0.0',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.13.0',
        },
    )
