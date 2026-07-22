"""
Phase 17 — shared first-launch bootstrap for the packaged desktop app.

Runs once per install: checks whether Playwright's Chromium browser is
already downloaded on this user's machine and, if not, spawns
`python -m playwright install chromium` while showing a modal
QProgressDialog. Subsequent launches short-circuit via a QSettings flag,
so there's no per-launch latency cost.

Called from `main.py` right after QApplication is created and before
MainWindow is constructed. Platform-agnostic — same code path works on
Windows and macOS; the cache directory is the only OS-specific piece.

Non-goals:
    * No node/npm bootstrap — desktop is a thin client.
    * No auto-update of an existing install.
    * No per-run health check — QSettings.bootstrap_completed is trusted
      once set; user can reset via SETUP guide if they wipe browsers.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QProgressDialog,
    QWidget,
)


_QSETTINGS_KEY = "bootstrap/completed"


def _playwright_cache_dir() -> Path:
    """User-scoped Playwright browsers cache. Mirrors Playwright's own
    default layout so an existing install (from a dev's pip Playwright)
    counts and we don't re-download."""
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "ms-playwright"
    # Linux fallback — not a supported install target, but useful for devs.
    return Path.home() / ".cache" / "ms-playwright"


def _chromium_installed() -> bool:
    cache = _playwright_cache_dir()
    if not cache.is_dir():
        return False
    for child in cache.iterdir():
        if child.is_dir() and child.name.startswith("chromium"):
            return True
    return False


def _install_chromium_blocking(parent: Optional[QWidget]) -> tuple[bool, str]:
    """Spawn `python -m playwright install chromium`. Blocks the caller
    (but the QProgressDialog keeps the UI responsive because we pump
    QApplication.processEvents while streaming stderr line-by-line).

    Returns (ok, message). On failure, `message` is stderr for the user
    to paste into a bug report or SETUP guide."""
    dialog = QProgressDialog(
        "Setting up XT-Forge (one-time, ~1 minute)…\n"
        "Downloading Playwright Chromium browser.",
        None,  # no Cancel — we don't support mid-download abort cleanly.
        0, 0,
        parent,
    )
    dialog.setWindowTitle("First launch")
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.show()
    QApplication.processEvents()

    proc = subprocess.Popen(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        if len(tail) > 200:
            tail.pop(0)
        dialog.setLabelText(
            "Setting up XT-Forge (one-time, ~1 minute)…\n"
            f"{line[:120]}"
        )
        QApplication.processEvents()

    rc = proc.wait()
    dialog.close()

    if rc == 0:
        return True, ""
    return False, "\n".join(tail[-25:]) or f"playwright install exited with rc={rc}"


def _register_icon_font() -> None:
    """Phase 19 — register Bootstrap Icons so `QFont('bootstrap-icons')`
    resolves and `ui/icons.py::bi_icon()` renders. Idempotent — Qt
    de-dupes across repeated calls. Resolves the woff2 path whether we're
    running from source (desktop-app/ui/fonts/) or from a PyInstaller
    bundle (sys._MEIPASS/ui/fonts/)."""
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:
        return
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else Path(__file__).resolve().parent
    font_path = base / "ui" / "fonts" / "bootstrap-icons.woff2"
    if font_path.exists():
        try:
            QFontDatabase.addApplicationFont(str(font_path))
        except Exception:
            pass


def ensure_dependencies(parent: Optional[QWidget] = None) -> bool:
    """Idempotent: safe to call on every launch. Returns True when the
    app is ready to boot MainWindow, False when the operator dismissed
    an unrecoverable error (caller should QApplication.quit)."""
    # Phase 19 — register the icon font on every launch. Cheap +
    # unrelated to the Playwright bootstrap flow, so it runs first.
    _register_icon_font()

    settings = QSettings()  # honors QApplication org+app name
    if settings.value(_QSETTINGS_KEY, False, type=bool):
        return True

    # Fast path: browsers already present from a prior manual install.
    if _chromium_installed():
        settings.setValue(_QSETTINGS_KEY, True)
        return True

    ok, err = _install_chromium_blocking(parent)
    if ok:
        settings.setValue(_QSETTINGS_KEY, True)
        return True

    # Failure — show the operator the last few log lines + steer them
    # toward the platform's SETUP guide.
    guide = "SETUP-mac.md" if sys.platform == "darwin" else "SETUP.md"
    QMessageBox.critical(
        parent,
        "XT-Forge setup failed",
        "Could not download the Playwright Chromium browser.\n\n"
        f"See {guide} → \"Playwright install failed\" for the manual "
        "install command, or contact your admin.\n\n"
        f"Last output:\n{err}",
    )
    return False
