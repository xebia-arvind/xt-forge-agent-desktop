"""Login screen: email / password / workspace ID."""
from __future__ import annotations

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


class LoginPanel(QWidget):
    """Emits `logged_in()` after a successful /auth/login/ + session save."""

    logged_in = Signal()
    server_change_requested = Signal()

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setObjectName("loginPanel")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 60, 80, 60)
        layout.setSpacing(12)
        layout.addStretch(1)

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

        self.workspace_input = QLineEdit()
        self.workspace_input.setPlaceholderText("Workspace ID (client secret UUID)")
        self.workspace_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.workspace_input)

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
        change_link.setObjectName("link")
        change_link.setFlat(True)
        change_link.clicked.connect(lambda: self.server_change_requested.emit())
        layout.addWidget(change_link, alignment=Qt.AlignCenter)

        layout.addStretch(2)

        # Enter submits from any field
        for inp in (self.email_input, self.password_input, self.workspace_input):
            inp.returnPressed.connect(self._submit)

    def _submit(self) -> None:
        email = self.email_input.text().strip()
        password = self.password_input.text()
        workspace = self.workspace_input.text().strip()
        if not (email and password and workspace):
            self._show_error("Enter email, password, and workspace ID.")
            return

        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Signing in…")
        try:
            self.api.login(email, password, workspace)
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
        auth_store.save_session(
            access=self.api.state.access,
            refresh=self.api.state.refresh,
            email=email,
            client_name=self.api.state.client_name,
            client_secret=workspace,
        )
        self.error_label.setVisible(False)
        self.logged_in.emit()

    def _show_error(self, msg: str) -> None:
        self.error_label.setText(msg)
        self.error_label.setVisible(True)
