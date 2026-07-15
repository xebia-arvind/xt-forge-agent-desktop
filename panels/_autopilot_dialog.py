"""
Modal autopilot progress dialog (Phase 14.4).

Shows a checklist of the four stages the PipelineAutopilot runs, updating
each row's status marker as signals arrive. Cancel button while the chain
is live; Close button appears on completion or failure.

Emits `finished_ok(job_dict)` and `finished_failed(stage, message)` back to
the caller (usually MainWindow via WorklistPanel) so it can navigate the
UI to the appropriate panel afterwards.
"""
from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workers.pipeline_autopilot import PipelineAutopilot, STAGES


# Pretty labels for the four autopiloted stages.
_STAGE_LABELS: Dict[str, str] = {
    "feature":       "Feature Author",
    "manual-tests":  "Manual Test Author",
    "plan":          "Plan Architect",
    "artifacts":     "Artifact Generator",
}

# Markers for each status.
_MARK_PENDING  = "⏳"
_MARK_RUNNING  = "▶"
_MARK_DONE     = "✅"
_MARK_FAILED   = "❌"


class _StageRow(QWidget):
    """One row in the checklist. Wraps marker + label + optional progress bar."""

    def __init__(self, stage_key: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.stage_key = stage_key
        self.status = "pending"

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(10)

        self.marker = QLabel(_MARK_PENDING)
        self.marker.setFixedWidth(24)
        self.marker.setAlignment(Qt.AlignCenter)
        row.addWidget(self.marker)

        self.label = QLabel(_STAGE_LABELS[stage_key])
        self.label.setStyleSheet("font-weight: 500;")
        row.addWidget(self.label, 1)

        # Indeterminate progress bar shown only while this row is running.
        self.spinner = QProgressBar()
        self.spinner.setMinimum(0)
        self.spinner.setMaximum(0)
        self.spinner.setFixedWidth(120)
        self.spinner.setTextVisible(False)
        self.spinner.setVisible(False)
        row.addWidget(self.spinner)

        self.detail = QLabel("")
        self.detail.setObjectName("emptyStateHint")
        self.detail.setVisible(False)
        # Below the row — small caption for error messages.

    def set_running(self) -> None:
        self.status = "running"
        self.marker.setText(_MARK_RUNNING)
        self.spinner.setVisible(True)

    def set_done(self) -> None:
        self.status = "done"
        self.marker.setText(_MARK_DONE)
        self.spinner.setVisible(False)

    def set_failed(self, message: str) -> None:
        self.status = "failed"
        self.marker.setText(_MARK_FAILED)
        self.spinner.setVisible(False)
        self.detail.setText(message)
        self.detail.setVisible(True)


class AutopilotDialog(QDialog):
    """
    Blocking modal that runs a PipelineAutopilot end-to-end. The caller
    creates it, connects to `finished_ok` / `finished_failed`, then
    `.exec()`s it.
    """

    finished_ok = Signal(dict)                # job dict when all four stages done
    finished_failed = Signal(str, str)        # (stage_key, message) on any failure

    def __init__(self, api, job_id: str, jira_key: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Autopilot for {jira_key or job_id[:8]}")
        self.setModal(True)
        self.setMinimumWidth(480)

        self.api = api
        self.job_id = job_id
        self.jira_key = jira_key

        self._rows: Dict[str, _StageRow] = {}
        self._final_state: Optional[str] = None    # "ok" | "failed"
        self._failure: tuple[str, str] = ("", "")
        self._final_job: dict = {}

        self._build_ui()
        self._start_autopilot()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 20)
        v.setSpacing(6)

        title = QLabel(f"🚀 Autopilot — {self.jira_key or self.job_id[:8]}")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        v.addWidget(title)

        subtitle = QLabel(
            "Running Feature → Manual Tests → Plan → Artifacts. "
            "Stops at Review — you'll take over from there."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #6b6470; font-size: 12px; margin-bottom: 8px;")
        v.addWidget(subtitle)

        for stage_key in STAGES:
            row = _StageRow(stage_key, self)
            v.addWidget(row)
            v.addWidget(row.detail)    # error message caption below the row
            self._rows[stage_key] = row

        v.addStretch(1)

        # Action row.
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        actions.addWidget(self.cancel_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("primary")
        self.close_btn.setVisible(False)
        self.close_btn.clicked.connect(self.accept)
        actions.addWidget(self.close_btn)
        v.addLayout(actions)

    def _start_autopilot(self) -> None:
        self._pilot = PipelineAutopilot(self.api, self.job_id, self)
        self._pilot.stage_started.connect(self._on_stage_started)
        self._pilot.stage_ran.connect(self._on_stage_ran)
        self._pilot.stage_approved.connect(self._on_stage_approved)
        self._pilot.failed.connect(self._on_failed)
        self._pilot.all_done.connect(self._on_all_done)
        self._pilot.start()

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------
    def _on_stage_started(self, stage: str) -> None:
        row = self._rows.get(stage)
        if row is not None:
            row.set_running()

    def _on_stage_ran(self, stage: str) -> None:
        # Approve is next for non-artifact stages; keep the row "running".
        # For "artifacts" (no approve step from autopilot), flip to done.
        row = self._rows.get(stage)
        if row is None:
            return
        if stage == "artifacts":
            row.set_done()

    def _on_stage_approved(self, stage: str) -> None:
        row = self._rows.get(stage)
        if row is not None:
            row.set_done()

    def _on_failed(self, stage: str, message: str) -> None:
        row = self._rows.get(stage)
        if row is not None:
            row.set_failed(message)
        self._final_state = "failed"
        self._failure = (stage, message)
        self._swap_to_close()

    def _on_all_done(self, job: dict) -> None:
        self._final_state = "ok"
        self._final_job = job or {}
        for row in self._rows.values():
            if row.status != "done":
                row.set_done()
        self._swap_to_close()

    def _swap_to_close(self) -> None:
        self.cancel_btn.setVisible(False)
        self.close_btn.setVisible(True)
        self.close_btn.setDefault(True)
        self.close_btn.setFocus()

    def _on_cancel(self) -> None:
        # Ask the autopilot to stop at the next boundary. Actual signal
        # (failed) arrives when the in-flight HTTP call returns.
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Cancelling…")
        self._pilot.cancel()

    def accept(self) -> None:  # noqa: D401
        # Emit the appropriate signal BEFORE closing so caller can navigate.
        if self._final_state == "ok":
            self.finished_ok.emit(self._final_job)
        elif self._final_state == "failed":
            self.finished_failed.emit(*self._failure)
        super().accept()

    def reject(self) -> None:
        # Escape / close-X: treat as cancel if still running.
        if self._final_state is None:
            self._on_cancel()
            # Wait for the autopilot to acknowledge via _on_failed; don't
            # actually close yet or we'll orphan the QThread.
            return
        super().reject()
