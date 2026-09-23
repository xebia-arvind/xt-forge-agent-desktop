"""Silent macOS self-installer.

When XT-Forge is launched from a mounted DMG (e.g. `/Volumes/XT-Forge/
XT-Forge.app`), copy the bundle to `~/Applications/XT-Forge.app`, strip
the Gatekeeper quarantine flag, relaunch from the installed location,
and quit the DMG-mounted instance. This spares users on machines
without admin rights from the drag-to-`/Applications` prompt and the
three-command Terminal ritual they previously had to run by hand.

macOS only. On Windows/Linux `install_and_relaunch_if_needed()` is a
no-op. Every step degrades gracefully — if any subprocess fails we
fall through and let the DMG-mounted app keep running rather than
leaving the user without a working shell.

Called from `main.py` BEFORE `QApplication` is constructed so we never
flash a UI window that we're about to quit.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _app_bundle_path() -> Optional[Path]:
    """Return the .app bundle root when running from a PyInstaller
    macOS bundle, else None. The exe path inside such a bundle is
    always `<X.app>/Contents/MacOS/<name>`."""
    if sys.platform != "darwin":
        return None
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


def _running_from_dmg(app_path: Path) -> bool:
    """The DMG mounts under /Volumes/…, so a bundle path starting with
    /Volumes/ is a strong signal we're on the mounted image."""
    return str(app_path).startswith("/Volumes/")


def install_and_relaunch_if_needed() -> bool:
    """Return True if a self-install was kicked off (caller must
    `sys.exit(0)` immediately). Return False when running from the
    normal installed location — caller keeps booting the app.
    """
    app_path = _app_bundle_path()
    if app_path is None:
        return False  # not a packaged macOS build
    if not _running_from_dmg(app_path):
        return False  # already installed; boot normally

    dest_parent = Path.home() / "Applications"
    dest = dest_parent / app_path.name

    # Ensure ~/Applications exists (Finder creates it lazily, so many
    # user profiles won't have it yet).
    try:
        dest_parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    # Replace any prior install so a fresh DMG always wins.
    if dest.exists():
        rm_result = subprocess.run(
            ["rm", "-rf", str(dest)],
            check=False, capture_output=True,
        )
        if rm_result.returncode != 0:
            return False

    cp_result = subprocess.run(
        ["cp", "-R", str(app_path), str(dest_parent) + os.sep],
        check=False, capture_output=True,
    )
    if cp_result.returncode != 0 or not dest.exists():
        return False

    # Strip the Gatekeeper quarantine flag so future launches from
    # Launchpad / Spotlight don't hit the "unidentified developer"
    # dialog again. Best-effort — failures don't abort the flow.
    subprocess.run(
        ["xattr", "-dr", "com.apple.quarantine", str(dest)],
        check=False, capture_output=True,
    )

    # Launch the installed copy in a fresh process, then bail. `-n`
    # forces a new instance even if the OS already thinks the bundle
    # id is running (it does — this process IS one).
    open_result = subprocess.run(
        ["open", "-n", str(dest)],
        check=False, capture_output=True,
    )
    if open_result.returncode != 0:
        return False

    return True
