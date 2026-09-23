"""Post-login project picker for the xtforge.xebia.in identity.

Shown after both auth steps (xtforge.xebia.in + Django agent) succeed,
in place of the old Django tenant picker. Lists the projects returned
by `GET /api/projects` (with the `customerName` header set from the
xtforge_identity) and stores the choice on `api.xtforge_project` so
the header dropdown + downstream panels can read it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from api_client import APIClient


class XTForgeProjectPickerDialog(QDialog):
    """Blocks the flow until the user picks a project. Emits `picked()`
    once `api.xtforge_project` is populated."""

    picked = Signal()
    cancelled = Signal()

    def __init__(self, api: APIClient, projects: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.api = api
        self.projects = list(projects)
        self.setWindowTitle("Select a project")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setMinimumHeight(420)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel("Projects")
        title.setObjectName("h1")
        layout.addWidget(title)

        subtitle = QLabel("Select a project to continue")
        subtitle.setObjectName("hint")
        layout.addWidget(subtitle)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("projectList")
        self.list_widget.itemDoubleClicked.connect(lambda _=None: self._pick())
        self.list_widget.setStyleSheet(
            "QListWidget#projectList { border: 1px solid #e5e7eb; "
            "border-radius: 6px; padding: 4px; background: #ffffff; }"
            "QListWidget#projectList::item { padding: 10px 12px; }"
            "QListWidget#projectList::item:selected { "
            "background: #ede9fe; color: #4c1d95; }"
        )
        for p in self.projects:
            name = str(p.get("projectName") or "(unnamed)")
            desc = str(p.get("projectDescription") or "").strip()
            display = f"{name}  —  {desc}" if desc else name
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, p)
            self.list_widget.addItem(item)
        if self.projects:
            self.list_widget.setCurrentRow(0)
        layout.addWidget(self.list_widget, 1)

        # Details area — updates as the selection changes.
        self.details = QLabel("")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.RichText)
        self.details.setStyleSheet(
            "background: #f9fafb; border: 1px solid #e5e7eb; "
            "border-radius: 6px; padding: 10px; font-size: 12px;"
        )
        self.details.setVisible(bool(self.projects))
        layout.addWidget(self.details)
        self.list_widget.currentItemChanged.connect(self._render_details)
        self._render_details(self.list_widget.currentItem(), None)

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
        self.ok_btn.setEnabled(bool(self.projects))
        btn_row.addWidget(self.ok_btn)
        layout.addLayout(btn_row)

        if not self.projects:
            self.error_label.setText(
                "No projects are assigned to your account. Ask an admin "
                "to add you to one, then sign in again."
            )
            self.error_label.setVisible(True)

    def _render_details(self, current: Optional[QListWidgetItem], _prev) -> None:
        if current is None:
            self.details.setText("")
            return
        p = current.data(Qt.UserRole) or {}
        team = ", ".join(str(x) for x in (p.get("teamMembers") or []))
        rows = [
            ("Description", str(p.get("projectDescription") or "—")),
            ("Owner",       str(p.get("projectOwner") or "—")),
            ("Customer",    str(p.get("customerName") or "—")),
            ("Type",        str(p.get("projectType") or "—")),
            ("Team",        team or "—"),
        ]
        html = "<br>".join(
            f"<b>{label}:</b> {value}" for label, value in rows
        )
        self.details.setText(html)

    def _pick(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            self._show_error("Select a project from the list.")
            return
        project = item.data(Qt.UserRole) or {}
        self.api.set_xtforge_project(project)
        self.accept()
        self.picked.emit()

    def _cancel(self) -> None:
        self.reject()
        self.cancelled.emit()

    def _show_error(self, msg: str) -> None:
        self.error_label.setText(msg)
        self.error_label.setVisible(True)
