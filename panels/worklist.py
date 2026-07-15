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
from panels._autopilot_dialog import AutopilotDialog

_DEFAULT_JQL = "assignee=currentUser() ORDER BY created DESC"

# Map autopilot stage keys to MainWindow panel slugs (Phase 14.5).
_STAGE_TO_PANEL_SLUG = {
    "feature":       "feature",
    "manual-tests":  "manual_tests",
    "plan":          "plan",
    "artifacts":     "review",
}


class WorklistPanel(QWidget):
    """
    Emits:
        pipeline_started(job_id, jira_key)          — manual Start pipeline
        autopilot_finished(job_id, jira_key, slug)  — autopilot done; navigate
                                                       to the given panel slug.
                                                       On success slug='review'.
                                                       On failure slug is the
                                                       stage panel that broke.
    """

    pipeline_started = Signal(str, str)
    autopilot_finished = Signal(str, str, str)

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setObjectName("worklistPanel")
        # Track whether the first auto-load has fired. reload() can throw
        # transient APIErrors during app startup (JWT rehydration racing
        # the first Jira call); we still want a fresh attempt when the
        # panel becomes visible.
        self._initial_load_done = False
        self._build_ui()

    # Phase 12.1 — auto-load issues on first render (and refresh on every
    # subsequent panel show). Previously the operator had to click Search
    # to see anything.
    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        # Fire once at startup; then only when we don't yet have rows.
        # If the user wants a manual refresh they can still click Search.
        if not self._initial_load_done or self.table.rowCount() == 0:
            self._initial_load_done = True
            try:
                self.reload()
            except Exception:  # noqa: BLE001 — never crash the panel on load
                pass

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
        self.table.setHorizontalHeaderLabels(["Key", "Summary", "Status", "Priority", "Actions"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        # Actions column (idx 4) — Phase 14 puts two buttons here (Start
        # pipeline + Autopilot). Fixed width so their labels don't clip.
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 320)
        self.table.verticalHeader().setVisible(False)
        # Slightly taller rows so both buttons breathe.
        self.table.verticalHeader().setDefaultSectionSize(40)
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

            # Actions cell = two buttons side by side: manual Start (as
            # today) + Autopilot (Phase 14). Keeping both preserves the
            # "just start, I'll drive manually" workflow.
            actions = QWidget()
            actions_row = QHBoxLayout(actions)
            actions_row.setContentsMargins(4, 2, 4, 2)
            actions_row.setSpacing(6)

            start_btn = QPushButton("Start pipeline →")
            start_btn.setObjectName("primary")
            start_btn.setMinimumWidth(140)
            start_btn.clicked.connect(lambda _=False, k=key, s=summary: self._start(k, s))
            actions_row.addWidget(start_btn)

            auto_btn = QPushButton("🚀 Autopilot")
            auto_btn.setObjectName("success")
            auto_btn.setMinimumWidth(120)
            auto_btn.setToolTip(
                "Run Feature → Manual Tests → Plan → Artifacts automatically.\n"
                "Stops at Review; Execute + Jira push remain manual."
            )
            auto_btn.clicked.connect(lambda _=False, k=key, s=summary: self._start_autopilot(k, s))
            actions_row.addWidget(auto_btn)

            self.table.setCellWidget(row_idx, 4, actions)

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

    # Phase 14 — one-click Feature → Manual → Plan → Artifacts.
    def _start_autopilot(self, jira_key: str, summary: str) -> None:
        # Same create-pipeline-job POST as manual mode. Only difference is
        # what happens next: the AutopilotDialog runs the four stages in
        # sequence and emits finished_ok / finished_failed on completion.
        try:
            result = self.api.start_pipeline(
                jira_key,
                feature_name=summary or jira_key,
            )
        except APIError as exc:
            QMessageBox.critical(self, "Autopilot start failed", str(exc))
            return
        job_id = str(result.get("job_id") or result.get("id") or "")
        if not job_id:
            QMessageBox.warning(self, "Autopilot", f"Backend response missing job_id:\n{result}")
            return

        dialog = AutopilotDialog(self.api, job_id, jira_key=jira_key, parent=self)
        dialog.finished_ok.connect(
            lambda _job, jid=job_id, jk=jira_key: self.autopilot_finished.emit(jid, jk, "review")
        )
        dialog.finished_failed.connect(
            lambda stage, _msg, jid=job_id, jk=jira_key: self.autopilot_finished.emit(
                jid, jk, _STAGE_TO_PANEL_SLUG.get(stage, "feature")
            )
        )
        dialog.exec()
