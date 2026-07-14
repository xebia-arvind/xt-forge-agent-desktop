# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Windows. Run from `desktop-app/` root:

    pyinstaller packaging/pyinstaller_win.spec

Produces `dist/XT-Forge/XT-Forge.exe`. Wrap into an installer via
`packaging/installer.iss` (Inno Setup 6).
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
        # Ship the icon in ui/ so both the .exe and the About dialog can use it.
        (str(here / "ui" / "xt-forge.ico"), "ui"),
    ],
    hiddenimports=[
        "keyring.backends.Windows",
        # Phase 7.4 — the bootstrap module invokes `python -m playwright
        # install chromium` on first launch. Playwright's pip package must
        # be bundled inside the packaged app so `sys.executable -m playwright`
        # works. PyInstaller doesn't auto-detect subprocess imports, so
        # list every module explicitly.
        "playwright",
        "playwright.sync_api",
        "playwright._impl",
        "playwright.__main__",
        # Bootstrap itself references PySide6.QtCore.QThread + Signal via
        # PySide6.QtCore, already collected by the top-level PySide6 import.
        "bootstrap",
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
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Phase 7.4 — Windows .exe icon. Silently ignored if the file is
    # absent so builds don't fail on branches that haven't checked
    # the icon in yet.
    icon=str(here / "ui" / "xt-forge.ico") if (here / "ui" / "xt-forge.ico").exists() else None,
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
