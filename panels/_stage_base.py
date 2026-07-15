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
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from api_client import APIClient, APIError
from workers.agent_run_thread import AgentRunThread


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
        # Phase 12.3 — reference to the in-flight AgentRunThread. Held so Qt
        # doesn't GC the thread mid-run (that crashes). Also used to reject
        # double-clicks on Run agent while a run is already in flight.
        self._agent_thread: Optional[AgentRunThread] = None
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

        # Phase 12.3 — indeterminate progress bar under the button row.
        # Hidden by default; shown while an AgentRunThread is in flight.
        # Qt's own paint loop animates it (as long as the event loop isn't
        # blocked — which is why the LLM call now runs on a worker thread).
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("runProgress")
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(0)   # indeterminate
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

    def _placeholder(self, text: str,
                     icon: str = "✨",
                     hint: str = "Click ▶ Run agent to invoke the LLM.") -> QWidget:
        """
        Phase 12.2 — prettified empty-state widget: an emoji icon, a bold
        title line, and a subtle hint underneath, all centred with generous
        vertical padding. Keeps the same single-string API so existing
        callers pass their message unchanged; only the visual output changes.
        Subclasses can supply a different icon/hint (e.g. "⏳" for the
        "Working…" state used while the agent runs — see Phase 12.3).
        """
        container = QWidget()
        v = QVBoxLayout(container)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(8)

        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("emptyStateIcon")
        icon_lbl.setAlignment(Qt.AlignCenter)

        title_lbl = QLabel(text)
        title_lbl.setObjectName("emptyStateTitle")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setWordWrap(True)

        hint_lbl = QLabel(hint)
        hint_lbl.setObjectName("emptyStateHint")
        hint_lbl.setAlignment(Qt.AlignCenter)
        hint_lbl.setWordWrap(True)

        v.addStretch(1)
        v.addWidget(icon_lbl)
        v.addWidget(title_lbl)
        v.addWidget(hint_lbl)
        v.addStretch(1)
        return container

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
    # Phase 12.3 — the previous _run() called api.run_stage synchronously on
    # the Qt event loop; the 30-120 s HTTPS call froze the UI. Now the call
    # runs on an AgentRunThread and the two _on_agent_* slots receive
    # signals with the response or an error. The progress bar animates
    # because the event loop is no longer blocked.
    def _run(self) -> None:
        if not self.job_id:
            QMessageBox.warning(self, "No job", "Start a pipeline from Worklist first.")
            return
        # Reject double-clicks while a run is already in flight.
        if self._agent_thread is not None and self._agent_thread.isRunning():
            return

        self._set_running(True)
        self._agent_thread = AgentRunThread(self.api, self.job_id, self.STAGE_KEY, parent=self)
        self._agent_thread.succeeded.connect(self._on_agent_succeeded)
        self._agent_thread.failed.connect(self._on_agent_failed)
        self._agent_thread.finished.connect(lambda: self._set_running(False))
        self._agent_thread.start()

    def _on_agent_succeeded(self, result: Any) -> None:
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

    def _on_agent_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Agent failed", message)

    def _set_running(self, running: bool) -> None:
        """
        Flip the panel between "run in progress" and "idle" states.
        Disables the button, swaps its text, toggles the progress bar,
        and shows a "Working…" placeholder in the scroll area while a
        run is in flight.
        """
        self.run_btn.setEnabled(not running)
        self.run_btn.setText("Running…" if running else "▶ Run agent")
        self.progress_bar.setVisible(running)
        if running:
            self._set_scroll_widget(
                self._placeholder(
                    "Working…",
                    icon="⏳",
                    hint="The LLM agent is thinking. This can take 30-120 s.",
                )
            )
        # When running=False, the succeeded/failed handler has already
        # rendered new output (or an error dialog was shown); don't
        # overwrite the scroll area here.

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
