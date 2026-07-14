"""
First-launch dependency bootstrap.

The Windows installer (`packaging/installer.iss`) drops a single `.exe`
that contains the Python runtime + PySide6 + every pip dependency the
desktop needs. What the installer CANNOT ship are the ~150 MB Playwright
browser binaries — they're per-user and Playwright downloads them from
the CDN at first use. This module handles that first-time download with
a progress dialog so end users don't have to open a terminal.

Called once from `main.py` before `AppShell.start()`. Reads/writes a
QSettings flag (`bootstrap.completed_v1`) so subsequent launches skip
the whole check — the browsers stay installed until the user manually
clears `%LOCALAPPDATA%\\ms-playwright\\`.

Design goals:

  * Best-effort. If the bootstrap fails (no network, permission error),
    log clearly and let the app boot anyway. Users can retry from
    within the app or ship the tests without headed-mode support.
  * Non-blocking UI. The download runs in a `QThread`; the main thread
    keeps the progress dialog responsive.
  * Idempotent. Safe to run multiple times; Playwright's own install
    logic is a no-op when browsers already exist.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog

import app_settings

logger = logging.getLogger("bootstrap")


# ---------------------------------------------------------------------------
# Detection — where do Playwright browsers live?
# ---------------------------------------------------------------------------
def _playwright_browsers_dir() -> Path:
    """
    Return the OS-specific directory where Playwright's `install chromium`
    lands its browser binaries. Matches the paths in Playwright's own
    `_registry.js` fallback logic.
    """
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _browsers_installed() -> bool:
    """
    Best-effort detection. We look for any `chromium-*` directory inside
    the OS-specific browsers path — Playwright creates one per version.
    """
    root = _playwright_browsers_dir()
    if not root.exists():
        return False
    for entry in root.iterdir():
        if entry.name.startswith("chromium") and entry.is_dir():
            # Cheap sanity check: at least one binary or subdir inside.
            if any(entry.iterdir()):
                return True
    return False


# ---------------------------------------------------------------------------
# Worker thread — runs `playwright install chromium` and streams stdout.
# ---------------------------------------------------------------------------
class _PlaywrightInstallWorker(QObject):
    progress = Signal(str)
    finished = Signal(bool, str)   # ok, message

    def run(self) -> None:
        try:
            # Prefer the same Python interpreter the app is running on. In
            # PyInstaller-bundled builds, `sys.executable` is the packaged
            # runtime; the `playwright` pip package was bundled at build time.
            argv = [sys.executable, "-m", "playwright", "install", "chromium"]
            logger.info("Running Playwright install: %s", " ".join(argv))
            self.progress.emit("Downloading Chromium (≈150 MB, one-time)…")
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    logger.info("[playwright] %s", line)
                    self.progress.emit(line[-120:])
            rc = proc.wait(timeout=300)
            if rc == 0:
                self.finished.emit(True, "Playwright browsers installed.")
            else:
                self.finished.emit(
                    False,
                    f"Playwright install exited with code {rc}. "
                    f"Check network and try again from the Setup panel.",
                )
        except FileNotFoundError as exc:
            self.finished.emit(
                False,
                (
                    f"Could not find the Playwright module: {exc}. "
                    "The installer may be corrupted — reinstall XT-Forge "
                    "or run `python -m playwright install chromium` manually."
                ),
            )
        except subprocess.TimeoutExpired:
            self.finished.emit(
                False,
                "Playwright install timed out after 5 minutes. Check your "
                "network connection and retry.",
            )
        except Exception as exc:  # noqa: BLE001 — never let bootstrap crash the app
            logger.exception("Bootstrap crashed: %s", exc)
            self.finished.emit(False, f"Bootstrap error: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
_BOOTSTRAP_FLAG = "bootstrap/playwright_v1_done"


def _mark_completed() -> None:
    settings = app_settings._settings()  # noqa: SLF001 — internal QSettings handle
    settings.setValue(_BOOTSTRAP_FLAG, True)
    settings.sync()


def _is_completed() -> bool:
    settings = app_settings._settings()  # noqa: SLF001
    return bool(settings.value(_BOOTSTRAP_FLAG, False, type=bool))


def ensure_dependencies(parent=None) -> None:
    """
    Called from main() before the app enters its normal boot path.

    Behaviour:
      * On the FIRST launch OR when the browsers directory is missing,
        show a progress dialog and run `playwright install chromium`.
      * On subsequent launches (flag set + browsers detected), skip.
      * On any failure, show a warning and let the app continue booting.
        The user can retry from Setup panel later.

    Skip conditions (no dialog shown):
      * Running unbundled (dev mode via `python main.py`) — Playwright is
        only a runtime dep of the packaged .exe. The desktop client itself
        is a plain HTTP client; the browser is used server-side.
      * The `playwright` pip package isn't importable — same reason. Only
        the PyInstaller build includes it. Setting XT_FORCE_BOOTSTRAP=1
        overrides both guards for testing.
    """
    force = os.environ.get("XT_FORCE_BOOTSTRAP") == "1"
    if not force:
        if not getattr(sys, "frozen", False):
            logger.info("Running unbundled — skipping Playwright bootstrap.")
            return
        try:
            import playwright  # noqa: F401
        except ImportError:
            logger.info("playwright package not bundled — skipping bootstrap.")
            return

    if _is_completed() and _browsers_installed():
        logger.info("Bootstrap already complete; skipping.")
        return

    dlg = QProgressDialog(
        "Setting up XT-Forge for first use…\n\n"
        "This is a one-time download of the Chromium browser Playwright uses "
        "to render tests (~150 MB). It only runs on the first launch.",
        None,   # no cancel button — killing mid-download leaves a broken cache
        0, 0,   # indeterminate spinner
        parent,
    )
    dlg.setWindowTitle("XT-Forge — first-launch setup")
    dlg.setMinimumWidth(520)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)

    thread = QThread()
    worker = _PlaywrightInstallWorker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress.connect(dlg.setLabelText)

    result_holder: dict = {"ok": False, "message": ""}

    def _on_finished(ok: bool, message: str) -> None:
        result_holder["ok"] = ok
        result_holder["message"] = message
        thread.quit()

    worker.finished.connect(_on_finished)
    thread.start()
    dlg.exec()             # blocks until dlg closes; we close on finished below
    # The dialog is modeless-ish because we blocked. If we reached here, the
    # thread finished OR the OS killed the dialog. Wait for the thread to
    # exit cleanly.
    thread.wait(1000)

    dlg.close()

    if result_holder["ok"]:
        _mark_completed()
        logger.info("Bootstrap succeeded.")
    else:
        # Non-fatal — surface a warning and continue.
        QMessageBox.warning(
            parent,
            "Playwright setup did not complete",
            (
                result_holder["message"]
                or "Playwright browsers could not be installed. "
                "Test execution that requires a real browser will fail until "
                "this succeeds. Retry from Setup, or run "
                "`python -m playwright install chromium` in a terminal."
            ),
        )
