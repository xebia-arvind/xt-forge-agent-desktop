"""
Execute panel — runs the Executor agent and streams the Cucumber log via SSE.

Flow:
    1. Click Run → POST /test-generation/jobs/<id>/stage/execute/run/
       Response includes a runner_job_id (either directly or nested in the
       execute output). We use that to open a Server-Sent Events stream.
    2. `SSELogThread` streams /runners/jobs/<runner_id>/stream/ and emits
       Signal(str) per log line + Signal(dict) on the `done` event.
    3. After the stream ends with a success state, Approve enables and
       POSTs to /test-generation/jobs/<id>/stage/execute/approve/ which
       pushes the report to Jira.
"""
from __future__ import annotations

import json
from typing import Any, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from api_client import APIClient, APIError
from workers.sse_thread import SSELogThread


class ExecutePanel(QWidget):
    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.job_id: Optional[str] = None
        self._sse: Optional[SSELogThread] = None
        self._runner_job_id: Optional[int] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header = QLabel("▶ Execute")
        header.setObjectName("h1")
        header_row.addWidget(header)
        header_row.addStretch(1)
        # Phase 7.2 — Smoke-mode tag on the current run header. Shows when
        # stage_execute_output.smoke_mode == True (Phase 6.5.3 parity).
        self.smoke_tag = QLabel("smoke mode · no LLM")
        self.smoke_tag.setObjectName("modelBadge")
        self.smoke_tag.setStyleSheet(
            "background-color: #dbeafe; color: #1d4ed8; "
            "padding: 2px 8px; border-radius: 10px; font-size: 11px;"
        )
        self.smoke_tag.setVisible(False)
        header_row.addWidget(self.smoke_tag)
        self.model_badge = QLabel("")
        self.model_badge.setObjectName("modelBadge")
        self.model_badge.setVisible(False)
        header_row.addWidget(self.model_badge)
        layout.addLayout(header_row)

        self.subheader = QLabel("Select a Jira ticket from Worklist first.")
        self.subheader.setObjectName("hint")
        layout.addWidget(self.subheader)

        # Phase 7.2 — Smoke-mode failure banner (Phase 6.5.3 parity).
        # Amber-tinted frame that appears when stage_execute_output shows
        # smoke_mode_failed=True. Includes an inline "Heal & retry" button
        # that kicks a full LLM loop (server infers because the job's
        # current state is RED/HUMAN_REVIEW_NEEDED).
        self.smoke_banner = QFrame()
        self.smoke_banner.setObjectName("smokeBanner")
        self.smoke_banner.setStyleSheet(
            "QFrame#smokeBanner { background-color: #fef3c7; "
            "border-left: 4px solid #b45309; border-radius: 6px; padding: 8px; }"
        )
        smoke_layout = QVBoxLayout(self.smoke_banner)
        smoke_layout.setContentsMargins(12, 10, 12, 10)
        smoke_layout.setSpacing(6)
        self.smoke_headline = QLabel("⚠ Smoke run failed on iteration 1")
        smoke_font = QFont()
        smoke_font.setBold(True)
        smoke_font.setPointSize(13)
        self.smoke_headline.setFont(smoke_font)
        self.smoke_headline.setStyleSheet("color: #92400e;")
        smoke_layout.addWidget(self.smoke_headline)
        self.smoke_body = QLabel(
            "This job was previously GREEN, so we ran the existing test as-is "
            "(Azure-Pipeline-style, no LLM). The test failed — likely a real UI "
            "regression, not a stale locator."
        )
        self.smoke_body.setWordWrap(True)
        self.smoke_body.setStyleSheet("color: #78350f;")
        smoke_layout.addWidget(self.smoke_body)
        smoke_btn_row = QHBoxLayout()
        smoke_btn_row.setSpacing(6)
        self.smoke_heal_btn = QPushButton("▶ Heal & retry")
        self.smoke_heal_btn.setToolTip("Kick a full LLM-assisted repair loop.")
        self.smoke_heal_btn.clicked.connect(self._heal_retry)
        smoke_btn_row.addWidget(self.smoke_heal_btn)
        smoke_btn_row.addStretch(1)
        smoke_btn_holder = QWidget()
        smoke_btn_holder.setLayout(smoke_btn_row)
        smoke_layout.addWidget(smoke_btn_holder)
        self.smoke_banner.setVisible(False)
        layout.addWidget(self.smoke_banner)

        # Phase 7.2 — Previous runs summary (Phase 6.5.2 parity).
        # One-line summary of archived runs with a toggle to reveal a
        # multi-line breakdown. Kept lightweight — full per-iteration
        # detail lives in the tool-trace box below for the current run.
        self.prev_runs_toggle = QPushButton("📜 Previous runs (0)")
        self.prev_runs_toggle.setObjectName("linkButton")
        self.prev_runs_toggle.setCheckable(True)
        self.prev_runs_toggle.clicked.connect(self._toggle_prev_runs)
        self.prev_runs_toggle.setVisible(False)
        layout.addWidget(self.prev_runs_toggle)

        self.prev_runs_detail = QPlainTextEdit()
        self.prev_runs_detail.setReadOnly(True)
        self.prev_runs_detail.setObjectName("codeBlock")
        self.prev_runs_detail.setMaximumHeight(200)
        self.prev_runs_detail.setVisible(False)
        layout.addWidget(self.prev_runs_detail)

        # Tool-trace: populated after each red iteration completes, hidden until then.
        self.trace_box = QPlainTextEdit()
        self.trace_box.setReadOnly(True)
        self.trace_box.setObjectName("codeBlock")
        self.trace_box.setPlaceholderText(
            "Root-cause fixer tool-call trace appears here after an iteration completes."
        )
        self.trace_box.setMaximumHeight(200)
        self.trace_box.setVisible(False)
        layout.addWidget(self.trace_box)

        # Live log
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("terminal")
        self.log_view.setPlaceholderText("Cucumber output will stream here…")
        mono = QFont("JetBrains Mono, Menlo, Consolas, monospace", 10)
        self.log_view.setFont(mono)
        self.log_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.log_view, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("hint")
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("▶ Run Cucumber")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        btn_row.addWidget(self.run_btn)

        self.stop_btn = QPushButton("■ Stop tail")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_stream)
        btn_row.addWidget(self.stop_btn)

        self.approve_btn = QPushButton("📤 Approve & push to Jira")
        self.approve_btn.setObjectName("success")
        self.approve_btn.setEnabled(False)
        self.approve_btn.clicked.connect(self._approve)
        btn_row.addWidget(self.approve_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    def set_job(self, job_id: str, jira_key: str = "") -> None:
        self.job_id = job_id
        suffix = f" — {jira_key}" if jira_key else ""
        self.subheader.setText(f"Job {job_id}{suffix}")
        self.log_view.clear()
        self.approve_btn.setEnabled(False)
        self._runner_job_id = None
        self._stop_stream()
        self._refresh_llm_ui()

    def _refresh_llm_ui(self) -> None:
        """
        Read the current job detail and paint (a) the OpenAI model badge
        derived from the latest root-cause-fixer llm_call, and (b) the
        tool-call trace of the most recent iteration if one is present.
        """
        if not self.job_id:
            self.model_badge.setVisible(False)
            self.trace_box.setVisible(False)
            return
        try:
            job = self.api.get_job(self.job_id)
        except APIError:
            return

        # Model badge
        history = job.get("stage_history") or []
        latest = None
        for entry in reversed(history):
            if isinstance(entry, dict) and entry.get("decision") == "llm_call" \
               and entry.get("agent") == "root_cause_fixer":
                latest = entry
                break
        if latest and latest.get("model"):
            self.model_badge.setText(f"⚡ {latest['model']}")
            self.model_badge.setVisible(True)
        else:
            self.model_badge.setVisible(False)

        # Tool trace of the most recent iteration
        exec_out = job.get("stage_execute_output") or {}
        iterations = exec_out.get("iterations") or []
        trace = None
        trace_iter_scenarios: List[dict] = []
        for it in reversed(iterations):
            if not isinstance(it, dict):
                continue
            if it.get("tool_trace") or it.get("scenarios"):
                trace = it.get("tool_trace") or []
                trace_iter_scenarios = list(it.get("scenarios") or [])
                iter_no = it.get("iteration", "?")
                break
        if trace or trace_iter_scenarios:
            lines: List[str] = []
            if trace:
                lines.append(f"🔧 Tool trace — iteration {iter_no} ({len(trace)} calls)")
                for t in trace:
                    turn = t.get("turn", "?")
                    tool = t.get("tool", "?")
                    args_str = json.dumps(t.get("args") or {}, separators=(",", ":"))
                    lines.append(f"  turn {turn}: {tool}({args_str[:80]})")

            # Phase 5.5 — surface the UI regression report for each failed
            # scenario in this iteration. Shows the operator whether the
            # test broke because the UI actually changed.
            regression_lines: List[str] = []
            for s in trace_iter_scenarios:
                if s.get("status") != "failed":
                    continue
                rr = s.get("regression_report") or {}
                level = str(rr.get("ui_change_level") or "UNKNOWN")
                added = list(rr.get("added_selectors") or [])[:5]
                removed = list(rr.get("removed_selectors") or [])[:5]
                bits = [f"UI {level}"]
                if rr.get("reason"):
                    bits.append(str(rr["reason"]))
                if added:
                    bits.append(f"+{len(added)}: {', '.join(added)}")
                if removed:
                    bits.append(f"-{len(removed)}: {', '.join(removed)}")
                regression_lines.append(f"  ⚠ {s.get('name','?')[:60]}  →  {'  |  '.join(bits)}")
            if regression_lines:
                if lines:
                    lines.append("")
                lines.append(f"⚠ UI regression report — iteration {iter_no}")
                lines.extend(regression_lines)

            self.trace_box.setPlainText("\n".join(lines))
            self.trace_box.setVisible(True)
        else:
            self.trace_box.setVisible(False)

        # Phase 7.2 — Smoke-mode banner + tag + previous-runs summary.
        # (Phase 6.5 parity — same logic as Django's execute.html render.)
        self._paint_smoke_ui(exec_out)
        self._paint_previous_runs(exec_out)

    # ------------------------------------------------------------------
    # Phase 7.2 helpers
    # ------------------------------------------------------------------
    def _paint_smoke_ui(self, exec_out: dict) -> None:
        """Show the smoke-mode tag on the current run + the failure banner."""
        smoke_mode = bool(exec_out.get("smoke_mode"))
        smoke_failed = bool(exec_out.get("smoke_mode_failed"))
        # Current-run tag: visible on any smoke run (green or red).
        self.smoke_tag.setVisible(smoke_mode)
        # Banner: visible only when the smoke run FAILED (real regression signal).
        self.smoke_banner.setVisible(smoke_failed)

    def _paint_previous_runs(self, exec_out: dict) -> None:
        """
        Show a "Previous runs (N)" toggle above the current-run detail.
        Clicking expands a compact multi-line summary of each archived run.
        """
        prev = list(exec_out.get("previous_runs") or [])
        if not prev:
            self.prev_runs_toggle.setVisible(False)
            self.prev_runs_detail.setVisible(False)
            return
        self.prev_runs_toggle.setVisible(True)
        self.prev_runs_toggle.setText(f"📜 Previous runs ({len(prev)})")

        lines: List[str] = []
        for pr in reversed(prev):  # most-recent first
            run_idx = pr.get("run_index", "?")
            final_state = pr.get("final_state") or "—"
            iters = pr.get("iterations") or []
            finished = pr.get("finished_on") or ""
            smoke_tag = " · smoke" if pr.get("smoke_mode") else ""
            lines.append(
                f"Run #{run_idx}  {final_state}{smoke_tag}  ·  "
                f"{len(iters)} iteration{'s' if len(iters) != 1 else ''}  ·  "
                f"{finished[:19] if finished else '—'}"
            )
            # A one-line summary per iteration inside this run.
            for it in iters:
                status = "✓" if it.get("all_passed") else "✗"
                iter_no = it.get("iteration", "?")
                diag = str(it.get("diagnosis") or "")[:100]
                lines.append(f"    {status} iter #{iter_no}  {diag}")
        self.prev_runs_detail.setPlainText("\n".join(lines))
        # Keep whatever expanded/collapsed state the user set previously.
        self.prev_runs_detail.setVisible(self.prev_runs_toggle.isChecked())

    def _toggle_prev_runs(self) -> None:
        self.prev_runs_detail.setVisible(self.prev_runs_toggle.isChecked())

    def _heal_retry(self) -> None:
        """
        Phase 6.5.3 — Smoke-mode failure banner offers this button. Posts
        to the same /stage/execute/run/ endpoint; server infers full-heal
        mode because the current stage is RED/HUMAN_REVIEW_NEEDED.
        """
        if not self.job_id:
            return
        reply = QMessageBox.question(
            self,
            "Kick heal loop?",
            "Smoke run failed. Kick a full LLM-assisted repair loop? "
            "Current iterations will be archived to run history.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.smoke_heal_btn.setEnabled(False)
        self.smoke_heal_btn.setText("enqueuing…")
        try:
            self.api.run_stage(self.job_id, "execute")
        except APIError as exc:
            QMessageBox.critical(self, "Heal & retry failed", str(exc))
            self.smoke_heal_btn.setEnabled(True)
            self.smoke_heal_btn.setText("▶ Heal & retry")
            return
        self.status_label.setText("Heal loop enqueued. Polling for progress…")
        self.smoke_heal_btn.setText("▶ Heal & retry")
        self.smoke_heal_btn.setEnabled(True)
        # Refresh so the smoke banner clears once the executor starts.
        self._refresh_llm_ui()

    # ------------------------------------------------------------------
    def _run(self) -> None:
        if not self.job_id:
            QMessageBox.warning(self, "No job", "Start a pipeline from Worklist first.")
            return
        self.run_btn.setEnabled(False)
        self.run_btn.setText("Running…")
        self.log_view.clear()
        self.status_label.setText("Enqueuing Cucumber run…")
        try:
            result = self.api.run_stage(self.job_id, "execute")
        except APIError as exc:
            self.run_btn.setEnabled(True)
            self.run_btn.setText("▶ Run Cucumber")
            QMessageBox.critical(self, "Execute failed", str(exc))
            return
        finally:
            # The run may kick off async work; keep the button re-enabled
            # once the request itself returns.
            self.run_btn.setEnabled(True)
            self.run_btn.setText("▶ Run Cucumber")

        runner_id = _extract_runner_job_id(result)
        if runner_id is None:
            self.status_label.setText("No runner job id returned; stage output shown above.")
            self.log_view.setPlainText(_pretty(result))
            self.approve_btn.setEnabled(True)
            return

        self._runner_job_id = runner_id
        self.status_label.setText(f"Streaming runner job {runner_id}…")
        self._start_stream(runner_id)

    # ------------------------------------------------------------------
    def _start_stream(self, runner_id: int) -> None:
        self._stop_stream()  # tear down any prior stream
        url = self.api.runner_stream_url(runner_id)
        auth = self.api.bearer_header()
        thread = SSELogThread(url, auth, parent=self)
        thread.line.connect(self._on_line)
        thread.done.connect(self._on_done)
        thread.error.connect(self._on_stream_error)
        thread.start()
        self._sse = thread
        self.stop_btn.setEnabled(True)

    def _stop_stream(self) -> None:
        if self._sse is not None:
            self._sse.stop()
            self._sse.wait(500)
            self._sse = None
        self.stop_btn.setEnabled(False)

    def _on_line(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _on_done(self, payload: dict) -> None:
        state = payload.get("state", "DONE")
        rc = payload.get("returncode", "?")
        self.status_label.setText(f"Run finished — state={state}, returncode={rc}")
        self.stop_btn.setEnabled(False)
        # Enable approve regardless of state — the operator decides whether to
        # push to Jira; matches the browser panel's behaviour.
        self.approve_btn.setEnabled(True)
        # Refresh the model badge + tool-call trace now that the Executor has
        # persisted a fresh iteration (including any patch bundle from the
        # tool-using Root-Cause Fixer).
        self._refresh_llm_ui()

    def _on_stream_error(self, msg: str) -> None:
        self.status_label.setText(f"⚠ {msg}")
        self.stop_btn.setEnabled(False)

    # ------------------------------------------------------------------
    def _approve(self) -> None:
        if not self.job_id:
            return
        try:
            self.api.approve_stage(self.job_id, "execute")
        except APIError as exc:
            QMessageBox.critical(self, "Push to Jira failed", str(exc))
            return
        QMessageBox.information(self, "Pushed", "Report pushed to Jira.")


def _extract_runner_job_id(payload: Any) -> Optional[int]:
    """
    The Execute run endpoint may return the runner job id at several places
    depending on backend version — normalize the lookup here.
    """
    if not isinstance(payload, dict):
        return None
    for key in ("runner_job_id", "runner_job", "job_id"):
        val = payload.get(key)
        if isinstance(val, int):
            return val
        if isinstance(val, dict) and isinstance(val.get("id"), int):
            return val["id"]
    exec_out = payload.get("stage_execute_output")
    if isinstance(exec_out, dict):
        return _extract_runner_job_id(exec_out)
    return None


def _pretty(payload: Any) -> str:
    import json
    try:
        return json.dumps(payload, indent=2)
    except (TypeError, ValueError):
        return str(payload)
