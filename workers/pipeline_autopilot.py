"""
Autopilot worker — runs Feature → Manual Tests → Plan → Artifacts in
sequence, calling `run_stage` + `approve_stage` for each, off the Qt event
loop. Stops at Artifact Review; Execute + Jira push remain manual.

Phase 14. Uses `api.run_stage()` + `api.approve_stage()` from the existing
`APIClient`. Emits per-stage signals so the modal `_autopilot_dialog` can
update its checklist in real time.

The chain stops IMMEDIATELY on any failure and emits `failed(stage, msg)`.
Cancellation is checked between stages (not mid-HTTP).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThread, Signal

from api_client import APIClient, APIError


# Ordered pipeline. Artifacts is the FINAL stage the autopilot runs; its
# approve is NOT called — that's the operator's decision in the Review panel.
STAGES = ("feature", "manual-tests", "plan", "artifacts")

# Stages whose approve step IS called by autopilot. Artifacts is
# deliberately excluded (see the module docstring).
STAGES_WITH_APPROVE = ("feature", "manual-tests", "plan")


class PipelineAutopilot(QThread):
    """
    Owns the sequential state machine. One instance per Autopilot click.

    Signals:
        stage_started(name)     — about to run this stage
        stage_ran(name)         — /run/ succeeded, about to approve
        stage_approved(name)    — /approve/ succeeded (skipped for artifacts)
        failed(name, message)   — this stage's run or approve failed
        all_done(job_dict)      — every stage complete; job.stage == 'ARTIFACTS'

    Cancellation:
        Call `.cancel()` from the UI thread. The autopilot checks the flag
        BETWEEN stages; it can't kill an in-flight HTTP call. Emits
        `failed(current_stage, "Cancelled by operator")` when it observes
        the flag.
    """

    stage_started = Signal(str)
    stage_ran = Signal(str)
    stage_approved = Signal(str)
    failed = Signal(str, str)
    all_done = Signal(dict)

    def __init__(self, api: APIClient, job_id: str, parent=None):
        super().__init__(parent)
        self.api = api
        self.job_id = job_id
        self._cancel = False

    def cancel(self) -> None:
        """Request cancellation. Takes effect at the next stage boundary."""
        self._cancel = True

    def run(self) -> None:  # noqa: C901 (linear state machine, easier as one function)
        for stage in STAGES:
            if self._cancel:
                self.failed.emit(stage, "Cancelled by operator")
                return

            # --- run ------------------------------------------------------
            self.stage_started.emit(stage)
            try:
                self.api.run_stage(self.job_id, stage)
            except APIError as exc:
                self.failed.emit(stage, str(exc))
                return
            except Exception as exc:  # noqa: BLE001 — never crash the thread
                self.failed.emit(stage, f"Unexpected error during run: {exc}")
                return
            self.stage_ran.emit(stage)

            # --- approve (skipped for artifacts) --------------------------
            if stage in STAGES_WITH_APPROVE:
                if self._cancel:
                    self.failed.emit(stage, "Cancelled by operator")
                    return
                try:
                    self.api.approve_stage(self.job_id, stage)
                except APIError as exc:
                    self.failed.emit(stage, f"Approve failed: {exc}")
                    return
                except Exception as exc:  # noqa: BLE001
                    self.failed.emit(stage, f"Unexpected error during approve: {exc}")
                    return
                self.stage_approved.emit(stage)

        # All four stages done. Fetch the final job so the dialog can hand
        # it back to the panel that receives all_done.
        try:
            final_job = self.api.get_job(self.job_id)
        except APIError:
            final_job = {}
        self.all_done.emit(final_job or {})
