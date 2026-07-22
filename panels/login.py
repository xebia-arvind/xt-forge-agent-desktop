"""Login screen: email + password only. Phase 18 removed the workspace
UUID field — the backend auto-picks the tenant for single-client users,
and returns a picker list for multi-client users (see panels/pick_client.py).

Phase 20 — the visible layout is a two-column shell (hero image on the
left, form + XT-Forge logo on the right). Form logic itself is unchanged;
`_build_form()` returns the vertical stack of inputs the shell hosts."""
from __future__ import annotations

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


class LoginPanel(QWidget):
    """Emits `logged_in()` once we hold a valid session JWT — this may be
    directly after login (single-client) OR after the picker modal (multi-
    client). `needs_pick(list)` is emitted when the backend responds with
    a picker payload; the shell shows the modal and calls back."""

    logged_in = Signal()
    needs_pick = Signal(list)
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

        subtitle = QLabel(f"Backend: {self.api.backend_url}")
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

        change_link = QPushButton("Change backend URL")
        change_link.setObjectName("linkButton")
        change_link.setFlat(True)
        change_link.clicked.connect(lambda: self.server_change_requested.emit())
        layout.addWidget(change_link, alignment=Qt.AlignCenter)

        # Enter submits from either field.
        for inp in (self.email_input, self.password_input):
            inp.returnPressed.connect(self._submit)

        return form

    def _submit(self) -> None:
        email = self.email_input.text().strip()
        password = self.password_input.text()
        if not (email and password):
            self._show_error("Enter email and password.")
            return

        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Signing in…")
        body: Dict[str, Any] = {}
        try:
            body = self.api.login(email, password)
        except AuthError as exc:
            self._show_error(f"Sign-in failed: {exc.detail[:300]}")
            return
        except APIError as exc:
            self._show_error(f"Backend error: {exc}")
            return
        finally:
            self.submit_btn.setEnabled(True)
            self.submit_btn.setText("Sign in")

        app_settings.set_last_email(email)
        self.error_label.setVisible(False)

        # Phase 18 — branch on the response shape.
        if body.get("needs_client_pick"):
            self.needs_pick.emit(list(body.get("available_clients") or []))
            return

        # Single-client / auto-picked path: persist the session and land
        # in MainWindow.
        auth_store.save_session(
            access=self.api.state.access,
            refresh=self.api.state.refresh,
            email=email,
            client_name=self.api.state.client_name,
            client_secret=self.api.state.client_secret,
        )
        self.logged_in.emit()

    def _show_error(self, msg: str) -> None:
        self.error_label.setText(msg)
        self.error_label.setVisible(True)
