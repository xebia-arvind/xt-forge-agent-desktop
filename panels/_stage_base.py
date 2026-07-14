"""
Shared skeleton for the four "run agent → show output → approve" stages
(Feature, Manual Tests, Plan, Review). Execute has its own module because it
has to stream a live log via SSE — see `panels/execute.py`.

Each subclass overrides `render_output(payload)` to build a visual layout
(cards, bullet lists, tables, code blocks) instead of raw JSON.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from api_client import APIClient, APIError


class StagePanelBase(QWidget):
    """
    Subclass and set `TITLE`, `STAGE_KEY` (matches api_client.STAGES), and
    `OUTPUT_FIELD` (the JSON attribute on the job detail that holds this
    stage's raw output — e.g. `stage_feature_output`).

    Override `render_output(payload)` to build a visual widget for the agent's
    output. Return a QWidget that will replace the scroll-area content.
    """

    TITLE: str = "Stage"
    STAGE_KEY: str = ""            # feature | manual-tests | plan | artifacts | execute
    OUTPUT_FIELD: str = ""         # stage_feature_output | stage_manual_tests_output | ...

    approved = Signal()            # notify main window to advance the stacked view

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.job_id: Optional[str] = None
        self._last_payload: Any = None
        self._build_ui()

    # Subclasses override to point paintModelBadge at the right agent's
    # stage_history entries (e.g. "feature_author", "manual_test_author", …).
    AGENT_KEY: str = ""

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        self.header_label = QLabel(self.TITLE)
        self.header_label.setObjectName("h1")
        header_row.addWidget(self.header_label)
        header_row.addStretch(1)
        self.model_badge = QLabel("")
        self.model_badge.setObjectName("modelBadge")
        self.model_badge.setVisible(False)
        header_row.addWidget(self.model_badge)
        layout.addLayout(header_row)

        self.subheader = QLabel("Select a Jira ticket from Worklist first.")
        self.subheader.setObjectName("hint")
        layout.addWidget(self.subheader)

        # Scrollable content area — subclasses fill this via render_output().
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("stageScroll")
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._set_scroll_widget(self._placeholder("Run the agent to see its output."))
        layout.addWidget(self.scroll, 1)

        # Buttons — stored on the instance so subclasses (e.g. ReviewPanel's
        # Regenerate button) can insert additional actions alongside them.
        self.btn_row = QHBoxLayout()
        self.run_btn = QPushButton("▶ Run agent")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        self.btn_row.addWidget(self.run_btn)

        self.approve_btn = QPushButton("👍 Approve & advance")
        self.approve_btn.setObjectName("success")
        self.approve_btn.setEnabled(False)
        self.approve_btn.clicked.connect(self._approve)
        self.btn_row.addWidget(self.approve_btn)

        self.raw_btn = QPushButton("{ } Raw JSON")
        self.raw_btn.setCheckable(True)
        self.raw_btn.clicked.connect(self._toggle_raw)
        self.btn_row.addWidget(self.raw_btn)

        self.btn_row.addStretch(1)
        layout.addLayout(self.btn_row)

    def _placeholder(self, text: str) -> QWidget:
        w = QLabel(text)
        w.setObjectName("hint")
        w.setAlignment(Qt.AlignCenter)
        w.setWordWrap(True)
        return w

    def _set_scroll_widget(self, widget: QWidget) -> None:
        self.scroll.setWidget(widget)

    # ------------------------------------------------------------------
    def set_job(self, job_id: str, jira_key: str = "") -> None:
        self.job_id = job_id
        suffix = f" — {jira_key}" if jira_key else ""
        self.subheader.setText(f"Job {job_id}{suffix}")
        self._set_scroll_widget(self._placeholder("Run the agent to see its output."))
        self.approve_btn.setEnabled(False)
        self._last_payload = None
        self._try_hydrate()

    def _try_hydrate(self) -> None:
        if not self.job_id:
            return
        try:
            job = self.api.get_job(self.job_id)
        except APIError:
            return
        self._paint_model_badge(job)
        if not self.OUTPUT_FIELD:
            return
        payload = job.get(self.OUTPUT_FIELD)
        if payload:
            self._show(payload)

    def _paint_model_badge(self, job: dict) -> None:
        """
        Read the latest `llm_call` stage_history entry for this panel's agent
        and show `⚡ <model>` in the header. Hidden when nothing has run yet.
        """
        if not self.AGENT_KEY:
            self.model_badge.setVisible(False)
            return
        history = job.get("stage_history") or []
        latest = None
        for entry in reversed(history):
            if not isinstance(entry, dict):
                continue
            if entry.get("decision") == "llm_call" and entry.get("agent") == self.AGENT_KEY:
                latest = entry
                break
        if latest and latest.get("model"):
            self.model_badge.setText(f"⚡ {latest['model']}")
            self.model_badge.setVisible(True)
        else:
            self.model_badge.setVisible(False)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        if not self.job_id:
            QMessageBox.warning(self, "No job", "Start a pipeline from Worklist first.")
            return
        self.run_btn.setEnabled(False)
        self.run_btn.setText("Running…")
        try:
            result = self.api.run_stage(self.job_id, self.STAGE_KEY)
        except APIError as exc:
            QMessageBox.critical(self, "Agent failed", str(exc))
            return
        finally:
            self.run_btn.setEnabled(True)
            self.run_btn.setText("▶ Run agent")

        # Server returns {"stage": "...", "output": {...}} — unwrap.
        if isinstance(result, dict) and "output" in result and isinstance(result["output"], (dict, list)):
            payload = result["output"]
        elif isinstance(result, dict) and self.OUTPUT_FIELD and self.OUTPUT_FIELD in result:
            payload = result[self.OUTPUT_FIELD]
        else:
            payload = result
        self._show(payload)
        # Refresh the model badge with the freshly-recorded stage_history entry.
        try:
            job = self.api.get_job(self.job_id)
            self._paint_model_badge(job)
        except APIError:
            pass

    def _approve(self) -> None:
        if not self.job_id:
            return
        try:
            self.api.approve_stage(self.job_id, self.STAGE_KEY)
        except APIError as exc:
            QMessageBox.critical(self, "Approve failed", str(exc))
            return
        self.approved.emit()

    def _show(self, payload: Any) -> None:
        self._last_payload = payload
        if self.raw_btn.isChecked():
            self._set_scroll_widget(_json_widget(payload))
        else:
            self._set_scroll_widget(self.render_output(payload))
        self.approve_btn.setEnabled(True)

    def _toggle_raw(self) -> None:
        if self._last_payload is None:
            self.raw_btn.setChecked(False)
            return
        if self.raw_btn.isChecked():
            self._set_scroll_widget(_json_widget(self._last_payload))
        else:
            self._set_scroll_widget(self.render_output(self._last_payload))

    # ------------------------------------------------------------------
    # Override this in subclasses to build a visual widget.
    def render_output(self, payload: Any) -> QWidget:
        return _json_widget(payload)


def _json_widget(payload: Any) -> QWidget:
    """Fallback / raw view — indented JSON in a monospace text area."""
    from PySide6.QtWidgets import QPlainTextEdit
    w = QPlainTextEdit()
    w.setReadOnly(True)
    w.setObjectName("codeBlock")
    try:
        w.setPlainText(json.dumps(payload, indent=2))
    except (TypeError, ValueError):
        w.setPlainText(str(payload))
    return w
