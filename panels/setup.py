"""First-launch backend URL entry."""
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


class SetupPanel(QWidget):
    """Backend URL config screen. Emits `configured(url)` on save."""

    configured = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("setupPanel")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 60, 80, 60)
        layout.setSpacing(14)
        layout.addStretch(1)

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

        layout.addStretch(2)

    def _save(self) -> None:
        url = self.url_input.text().strip().rstrip("/")
        if not url.startswith("http://") and not url.startswith("https://"):
            self.error_label.setText("URL must start with http:// or https://")
            self.error_label.setVisible(True)
            return
        app_settings.set_backend_url(url)
        self.configured.emit(url)
