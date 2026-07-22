"""
Entry point.

Flow:
    1. Load QSettings. If no backend URL saved → show SetupPanel.
    2. Rehydrate keychain session into APIClient. If access token present →
       jump to MainWindow (calls may 401; APIClient will bounce to login).
    3. Otherwise → show LoginPanel.

Only one widget is visible at a time. Login/setup are their own top-level
widgets; the pipeline UI lives inside MainWindow.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QStackedWidget

import app_settings
import auth_store
from api_client import APIClient
from bootstrap import ensure_dependencies
from main_window import MainWindow
from panels.login import LoginPanel
from panels.setup import SetupPanel


def _load_stylesheet() -> str:
    here = Path(__file__).resolve().parent
    qss = here / "ui" / "style.qss"
    if qss.exists():
        try:
            return qss.read_text(encoding="utf-8")
        except OSError:
            pass
    return ""


class AppShell:
    """Owns the QStackedWidget that swaps setup / login / main window."""

    def __init__(self):
        self.stack = QStackedWidget()
        self.stack.setWindowTitle("XT-Forge Agent")
        self.stack.resize(1280, 800)

        self.api: APIClient = None  # type: ignore[assignment]
        self.setup_panel = SetupPanel()
        self.login_panel: LoginPanel = None  # type: ignore[assignment]
        self.main_window: MainWindow = None  # type: ignore[assignment]

        self.stack.addWidget(self.setup_panel)
        self.setup_panel.configured.connect(self._on_configured)

    def start(self) -> None:
        url = app_settings.get_backend_url()
        if not url:
            self.stack.setCurrentWidget(self.setup_panel)
        else:
            self._show_login(url)
        self.stack.show()

    def _on_configured(self, url: str) -> None:
        self._show_login(url)

    def _show_login(self, url: str) -> None:
        self.api = APIClient(url)
        # V1 behaviour: always require a fresh interactive login on launch.
        # Access tokens live 5min by default; rehydrating from the keychain
        # after quit-and-relaunch would routinely surface stale-token 401s.
        # Wipe any previously-cached tokens so nothing silently leaks between
        # sessions.
        auth_store.clear_session()

        panel = LoginPanel(self.api)
        panel.logged_in.connect(self._show_main)
        panel.server_change_requested.connect(self._back_to_setup)
        self._replace(panel)
        self.login_panel = panel

    def _show_main(self) -> None:
        mw = MainWindow(self.api)
        mw.logout_requested.connect(self._on_logout)
        self._replace(mw)
        self.main_window = mw

    def _back_to_setup(self) -> None:
        app_settings.set_backend_url("")
        self._replace(self.setup_panel)

    def _on_logout(self) -> None:
        # Force a fresh login screen.
        url = app_settings.get_backend_url() or "http://127.0.0.1:8000"
        self._show_login(url)

    def _replace(self, widget) -> None:
        # Remove any existing non-setup widget, add the new one, switch to it.
        # Setup panel is kept around so "Change backend URL" from login works.
        for i in reversed(range(self.stack.count())):
            w = self.stack.widget(i)
            if w is not self.setup_panel and w is not widget:
                self.stack.removeWidget(w)
                w.deleteLater()
        if self.stack.indexOf(widget) < 0:
            self.stack.addWidget(widget)
        self.stack.setCurrentWidget(widget)


def main() -> int:
    # High-DPI is on by default in Qt 6; no attribute toggling needed.
    app = QApplication(sys.argv)
    app.setApplicationName("XT-Forge Desktop")
    app.setOrganizationName("XTForge")

    qss = _load_stylesheet()
    if qss:
        app.setStyleSheet(qss)

    # Phase 17 — one-time first-launch bootstrap. Downloads Playwright
    # Chromium if it's not already on disk. Subsequent launches short-
    # circuit via a QSettings flag. If the download fails, ensure_deps
    # surfaces its own modal and we abort here — the user gets the SETUP
    # guide reference rather than a broken app screen.
    try:
        if not ensure_dependencies():
            return 1
    except Exception:  # noqa: BLE001 — never crash the shell on bootstrap.
        # Fall through to the app anyway; individual pipelines will fail
        # loudly if the browsers are actually missing, but the shell
        # (login, setup, jobs list) still works.
        pass

    shell = AppShell()
    shell.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
