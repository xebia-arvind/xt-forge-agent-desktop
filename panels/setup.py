"""First-launch backend URL entry.

Phase 20 — same two-column shell as LoginPanel (hero image on the left,
form + XT-Forge logo on the right). Form logic itself is unchanged; the
whole vertical stack is built in `_build_form()` and handed to the shell."""
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
from panels._two_column import build_two_column


class SetupPanel(QWidget):
    """Backend URL config screen. Emits `configured(url)` on save."""

    configured = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("setupPanel")
        self._build_ui()

    def _build_ui(self) -> None:
        # Outer layout hosts a single child — the two-column shell.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(build_two_column(self._build_form()))

    def _build_form(self) -> QWidget:
        """The vertical stack of URL input + save button that lives inside
        the two-column shell's right column."""
        form = QWidget()
        layout = QVBoxLayout(form)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = QLabel("Configure XT-Forge backend")
        title.setObjectName("h1")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        hint = QLabel(
            "Enter the URL of your XT-Forge Django server. Example:\n"
            "  http://127.0.0.1:8000 (local dev)\n"
            "  https://xtforge.company.com (production)"
        )
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("http://127.0.0.1:8000")
        self.url_input.setText(app_settings.get_backend_url() or "http://127.0.0.1:8000")
        layout.addWidget(self.url_input)

        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.save_btn = QPushButton("Continue →")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self._save)
        layout.addWidget(self.save_btn)

        # Enter submits.
        self.url_input.returnPressed.connect(self._save)

        return form

    def _save(self) -> None:
        url = self.url_input.text().strip().rstrip("/")
        if not url.startswith("http://") and not url.startswith("https://"):
            self.error_label.setText("URL must start with http:// or https://")
            self.error_label.setVisible(True)
            return
        app_settings.set_backend_url(url)
        self.configured.emit(url)
