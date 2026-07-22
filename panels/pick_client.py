"""Phase 18 — post-login client picker modal.

Shown between LoginPanel and MainWindow when the backend responds with
`needs_client_pick: true` (i.e. the user has 2+ assigned tenants and did
not provide a client_secret). Single-client users never see this dialog.

Mirrors the browser panel's "Choose a client to continue" card verbatim.
"""
from __future__ import annotations

from typing import List, Dict, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

import auth_store
from api_client import APIClient, APIError, AuthError


class ClientPickerDialog(QDialog):
    """Blocks the flow until the operator selects a tenant. Emits
    `picked()` on success (JWT now on api.state) or `cancelled()` if
    the operator backs out to the login screen."""

    picked = Signal()
    cancelled = Signal()

    def __init__(self, api: APIClient, clients: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.api = api
        self.clients = list(clients)
        self.setWindowTitle("Choose a client")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel("Choose a client to continue")
        title.setObjectName("h1")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "Your login has access to more than one client. Pick which one "
            "you want to work in. You can switch at any time from the "
            "top-right of the dashboard."
        )
        subtitle.setObjectName("hint")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        self.combo = QComboBox()
        for c in self.clients:
            display = c.get("name") or c.get("slug") or c.get("id") or "—"
            self.combo.addItem(display, userData=str(c.get("id") or ""))
        layout.addWidget(self.combo)

        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setVisible(False)
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.cancel_btn)

        self.ok_btn = QPushButton("Continue →")
        self.ok_btn.setObjectName("primary")
        self.ok_btn.clicked.connect(self._pick)
        btn_row.addWidget(self.ok_btn)
        layout.addLayout(btn_row)

    def _pick(self) -> None:
        client_id = self.combo.currentData()
        if not client_id:
            self._show_error("Select a client from the list.")
            return
        self.ok_btn.setEnabled(False)
        self.ok_btn.setText("Loading…")
        try:
            self.api.pick_client(client_id)
        except AuthError as exc:
            self._show_error(f"Session expired: {exc.detail[:200]}")
            return
        except APIError as exc:
            self._show_error(f"Could not switch client: {exc}")
            return
        finally:
            self.ok_btn.setEnabled(True)
            self.ok_btn.setText("Continue →")

        # Persist the new session before signaling — MainWindow reads from
        # the keychain if it ever restarts mid-session, and we don't want
        # a stale token there.
        auth_store.save_session(
            access=self.api.state.access,
            refresh=self.api.state.refresh,
            email=self.api.state.email,
            client_name=self.api.state.client_name,
            client_secret=self.api.state.client_secret,
        )
        self.accept()
        self.picked.emit()

    def _cancel(self) -> None:
        self.reject()
        self.cancelled.emit()

    def _show_error(self, msg: str) -> None:
        self.error_label.setText(msg)
        self.error_label.setVisible(True)
