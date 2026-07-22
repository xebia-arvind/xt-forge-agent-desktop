# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for macOS. Run from `desktop-app/` root:

    pyinstaller packaging/pyinstaller_mac.spec

Produces `dist/XT-Forge.app`. Wrap into a `.dmg` via `packaging/build_dmg.sh`.
"""
from pathlib import Path

here = Path(SPECPATH).resolve().parent  # desktop-app/

block_cipher = None

a = Analysis(
    [str(here / "main.py")],
    pathex=[str(here)],
    binaries=[],
    datas=[
        (str(here / "ui" / "style.qss"), "ui"),
        # Phase 17 — ship the icon inside Contents/Resources/ so any
        # runtime code that wants to load it (dock badge, About dialog)
        # can resolve it via sys._MEIPASS.
        (str(here / "ui" / "xt-forge.icns"), "ui"),
    ],
    hiddenimports=[
        "keyring.backends.macOS",
    ],
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
    name="XT-Forge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="XT-Forge",
)

app = BUNDLE(
    coll,
    name="XT-Forge.app",
    # Phase 17 — Finder + Dock icon. Generated once from ui/xt-forge.ico
    # via `iconutil -c icns …`; see SETUP-mac.md for regen instructions.
    icon=str(here / "ui" / "xt-forge.icns"),
    bundle_identifier="com.xtforge.desktop",
    info_plist={
        "CFBundleName": "XT-Forge",
        "CFBundleDisplayName": "XT-Forge Agent",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
    },
)
