"""Login screen: email + password only. Phase 18 removed the workspace
UUID field — the backend auto-picks the tenant for single-client users,
and returns a picker list for multi-client users (see panels/pick_client.py).

Phase 20 — the visible layout is a two-column shell (hero image on the
left, form + XT-Forge logo on the right). Form logic itself is unchanged;
`_build_form()` returns the vertical stack of inputs the shell hosts.

Dual-login: the form now takes xtforge.xebia.in credentials. On success,
a second silent login runs against the Django agent backend with
hard-coded credentials (overridable via env). Both must succeed to
land on the main window."""
from __future__ import annotations

import os
from typing import Any, Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import app_settings
import auth_store
from api_client import APIClient, AuthError, APIError
from panels._two_column import build_two_column


# Hard-coded Django agent credentials for the second (silent) login step.
# Env-var overrides let a shipped build swap the pair without recompiling
# and keep the source file committable without an operational password.
_AGENT_USER = os.environ.get("XTFORGE_AGENT_USER", "arvind.kumar1@xebia.com")
_AGENT_PASS = os.environ.get("XTFORGE_AGENT_PASS", "admin")


class LoginPanel(QWidget):
    """Emits `logged_in()` once we hold a valid session JWT — this may be
    directly after login (single-client) OR after the picker modal (multi-
    client). `needs_pick(list)` is emitted when the backend responds with
    a picker payload; the shell shows the modal and calls back."""

    logged_in = Signal()
    needs_pick = Signal(list)
    needs_project_pick = Signal(list)
    server_change_requested = Signal()

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setObjectName("loginPanel")
        self._build_ui()

    def _build_ui(self) -> None:
        # Outer layout hosts a single child — the two-column shell.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(build_two_column(self._build_form()))

    def _build_form(self) -> QWidget:
        """The vertical stack of inputs + submit that lives inside the
        two-column shell's right column."""
        form = QWidget()
        layout = QVBoxLayout(form)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Sign in to XT-Forge")
        title.setObjectName("h1")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Use your XT-Forge credentials.")
        subtitle.setObjectName("hint")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Email")
        self.email_input.setText(app_settings.get_last_email())
        layout.addWidget(self.email_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)

        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setVisible(False)
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self.submit_btn = QPushButton("Sign in")
        self.submit_btn.setObjectName("primary")
        self.submit_btn.clicked.connect(self._submit)
        layout.addWidget(self.submit_btn)

        # "Change backend URL" is hidden — backend is baked in via
        # main.AGENT_BACKEND_URL. Widget stays in the tree with signal
        # wiring intact so a future setVisible(True) can re-enable it.
        change_link = QPushButton("Change backend URL")
        change_link.setObjectName("linkButton")
        change_link.setFlat(True)
        change_link.clicked.connect(lambda: self.server_change_requested.emit())
        change_link.setVisible(False)
        layout.addWidget(change_link, alignment=Qt.AlignCenter)

        # Enter submits from either field.
        for inp in (self.email_input, self.password_input):
            inp.returnPressed.connect(self._submit)

        return form

    def _submit(self) -> None:
        username = self.email_input.text().strip()
        password = self.password_input.text()
        if not (username and password):
            self._show_error("Enter email and password.")
            return

        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Signing in…")
        try:
            # Step A — user-facing auth against xtforge.xebia.in.
            try:
                self.api.xtforge_login(username, password)
            except AuthError as exc:
                self._show_error(f"Sign-in failed: {exc.detail[:300]}")
                return
            except APIError as exc:
                self._show_error(f"Sign-in failed: {exc}")
                return

            # Step B — silent internal auth against the Django agent
            # backend. Uses hard-coded (env-overridable) credentials.
            body: Dict[str, Any] = {}
            try:
                body = self.api.login(_AGENT_USER, _AGENT_PASS)
            except AuthError as exc:
                self._show_error(
                    f"Backend session couldn't be established: {exc.detail[:300]}"
                )
                return
            except APIError as exc:
                self._show_error(
                    f"Backend session couldn't be established: {exc}"
                )
                return
        finally:
            self.submit_btn.setEnabled(True)
            self.submit_btn.setText("Sign in")

        # Both logins succeeded from here on.
        app_settings.set_last_email(username)
        self.error_label.setVisible(False)

        # Phase 18 — Django tenant picker. With hard-coded creds this
        # branch is effectively dead, but we keep it wired for future.
        if body.get("needs_client_pick"):
            self.needs_pick.emit(list(body.get("available_clients") or []))
            return

        # Persist the Django session before the project picker step so a
        # keychain re-hydrate can't drop the JWT if the operator dismisses
        # the picker.
        auth_store.save_session(
            access=self.api.state.access,
            refresh=self.api.state.refresh,
            email=self.api.state.email,
            client_name=self.api.state.client_name,
            client_secret=self.api.state.client_secret,
        )

        # Step C — fetch the xtforge.xebia.in projects and hand them off
        # to the shell so it can show the picker modal. The shell emits
        # logged_in after the user picks.
        try:
            projects = self.api.list_xtforge_projects()
        except (AuthError, APIError) as exc:
            self._show_error(f"Could not load projects: {exc}")
            return
        self.needs_project_pick.emit(list(projects))

    def _show_error(self, msg: str) -> None:
        self.error_label.setText(msg)
        self.error_label.setVisible(True)
