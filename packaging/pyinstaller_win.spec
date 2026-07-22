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


def _optional_asset(rel_path: str, dest: str):
    """Only include an asset in datas if it exists on disk. Lets CI
    build a functional installer even before the design team has
    committed the login hero / logo PNGs (Phase 20)."""
    p = here / rel_path
    return (str(p), dest) if p.exists() else None

a = Analysis(
    [str(here / "main.py")],
    pathex=[str(here)],
    binaries=[],
    datas=[
        (str(here / "ui" / "style.qss"), "ui"),
        # Ship the icon in ui/ so both the .exe and the About dialog can use it.
        (str(here / "ui" / "xt-forge.ico"), "ui"),
        # Phase 19 — Bootstrap Icons font. Registered at startup by
        # bootstrap.py::_register_icon_font(). ui/icons.py's bi_icon()
        # helper renders glyphs from this font.
        (str(here / "ui" / "fonts" / "bootstrap-icons.woff2"), "ui/fonts"),
    ]
    # Phase 20 — hero image + XT-Forge wordmark for the two-column
    # login/setup shell (panels/_two_column.py). Optional at build
    # time: the shell degrades to blank labels if either is missing.
    + [e for e in (
        _optional_asset("ui/images/login-hero.png",    "ui/images"),
        _optional_asset("ui/images/xt-forge-logo.png", "ui/images"),
    ) if e],
    hiddenimports=[
        "keyring.backends.Windows",
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
