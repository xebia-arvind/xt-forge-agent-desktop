"""Jira worklist — table of issues with 'Start pipeline' per row."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from api_client import APIClient, APIError

_DEFAULT_JQL = "assignee=currentUser() ORDER BY created DESC"


class WorklistPanel(QWidget):
    """Emits `pipeline_started(job_id, jira_key)` when Start pipeline succeeds."""

    pipeline_started = Signal(str, str)

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setObjectName("worklistPanel")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header = QLabel("📋 Jira Worklist")
        header.setObjectName("h1")
        layout.addWidget(header)

        # Search row
        search_row = QHBoxLayout()
        self.jql_input = QLineEdit()
        self.jql_input.setText(_DEFAULT_JQL)
        self.jql_input.returnPressed.connect(self.reload)
        search_row.addWidget(self.jql_input, 1)

        self.refresh_btn = QPushButton("Search")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.clicked.connect(self.reload)
        search_row.addWidget(self.refresh_btn)
        layout.addLayout(search_row)

        # Status + Jira config summary
        self.status_label = QLabel("")
        self.status_label.setObjectName("hint")
        layout.addWidget(self.status_label)

        # Issues table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Key", "Summary", "Status", "Priority", ""])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)

    def reload(self) -> None:
        self.status_label.setText("Loading Jira issues…")
        try:
            data = self.api.jira_search(self.jql_input.text().strip() or _DEFAULT_JQL, max_results=50)
        except APIError as exc:
            self.status_label.setText(f"⚠ {exc}")
            return

        issues: List[dict] = data.get("issues") or data.get("results") or []
        self.status_label.setText(f"Found {len(issues)} issue(s).")
        self._populate_table(issues)

    def _populate_table(self, issues: List[dict]) -> None:
        self.table.setRowCount(0)
        for row_idx, issue in enumerate(issues):
            key = str(issue.get("key") or "")
            fields = issue.get("fields") or {}
            summary = str(fields.get("summary") or "")
            status = str((fields.get("status") or {}).get("name") or "")
            priority = str((fields.get("priority") or {}).get("name") or "")

            self.table.insertRow(row_idx)
            self.table.setItem(row_idx, 0, QTableWidgetItem(key))
            self.table.setItem(row_idx, 1, QTableWidgetItem(summary))
            self.table.setItem(row_idx, 2, QTableWidgetItem(status))
            self.table.setItem(row_idx, 3, QTableWidgetItem(priority))

            btn = QPushButton("Start pipeline →")
            btn.setObjectName("primary")
            btn.clicked.connect(lambda _=False, k=key, s=summary: self._start(k, s))
            self.table.setCellWidget(row_idx, 4, btn)

        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(2)
        self.table.resizeColumnToContents(3)

    def _start(self, jira_key: str, summary: str) -> None:
        # Mirror the browser Worklist behaviour: POST to /pipeline-jobs/ with
        # just jira_issue_key + feature_name. The backend resolves the site
        # URL from the tenant's ui_knowledge / client config — no client-side
        # prompt needed, so operators don't have to remember/paste URLs.
        try:
            result = self.api.start_pipeline(
                jira_key,
                feature_name=summary or jira_key,
            )
        except APIError as exc:
            QMessageBox.critical(self, "Start pipeline failed", str(exc))
            return
        job_id = str(result.get("job_id") or result.get("id") or "")
        if not job_id:
            QMessageBox.warning(self, "Pipeline created", f"Backend response missing job_id:\n{result}")
            return
        self.pipeline_started.emit(job_id, jira_key)
