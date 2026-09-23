"""
Manual Executor panel (Phase 16 parity).

Ports the browser Execute panel's "Manual" tab. Runs Cucumber once (no
auto-heal), streams the log via SSE, exposes editable artifacts + save,
a shared "Fix with LLM" box, and Push-to-Jira after a GREEN run.

Talks to four Django endpoints — see api_client.manual_*.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from api_client import APIClient, APIError
from ui.highlighters import highlighter_for
from workers.sse_thread import SSELogThread


class _ArtifactCard(QFrame):
    """
    One editable-artifact card. Header shows type + relative_path +
    validation badge; body is a monospace QPlainTextEdit; footer has a
    Save button that POSTs to /artifacts/update/.
    """

    def __init__(self, api: APIClient, job_id: str, artifact: dict, parent=None):
        super().__init__(parent)
        self.api = api
        self.job_id = job_id
        self.rel_path = str(artifact.get("relative_path") or "")
        self.setObjectName("artifactCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame#artifactCard { border: 1px solid #d1d5db; border-radius: 6px; "
            "padding: 8px; background-color: #ffffff; }"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        header = QHBoxLayout()
        atype = str(artifact.get("artifact_type") or "")
        title = QLabel(f"<b>{atype}</b> · <code>{self.rel_path}</code>")
        title.setTextFormat(Qt.RichText)
        header.addWidget(title, 1)

        status = str(artifact.get("validation_status") or "")
        badge = QLabel(status or "—")
        badge_color = "#065f46" if status == "VALID" else "#991b1b"
        badge_bg = "#d1fae5" if status == "VALID" else "#fee2e2"
        badge.setStyleSheet(
            f"background-color: {badge_bg}; color: {badge_color}; "
            "padding: 2px 8px; border-radius: 10px; font-size: 11px;"
        )
        header.addWidget(badge)
        v.addLayout(header)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(
            str(artifact.get("content_final") or artifact.get("content_draft") or "")
        )
        mono = QFont("JetBrains Mono, Menlo, Consolas, monospace", 10)
        self.editor.setFont(mono)
        self.editor.setMinimumHeight(160)
        self.editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # VS Code Dark+ background + syntax highlighting for .ts/.feature.
        # Matches the Review panel's artifact viewer (Phase 21).
        self.editor.setStyleSheet(
            "QPlainTextEdit { background-color: #1e1e1e; color: #d4d4d4; "
            "border: 1px solid #333333; border-radius: 4px; padding: 6px; }"
        )
        hl = highlighter_for(self.rel_path, self.editor.document())
        if hl is not None:
            self.editor._highlighter = hl  # keep-alive so Qt doesn't GC it
        v.addWidget(self.editor)

        footer = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save")
        self.save_btn.clicked.connect(self._save)
        footer.addWidget(self.save_btn)

        self.save_status = QLabel("")
        self.save_status.setStyleSheet("color: #6b7280; font-size: 11px;")
        footer.addWidget(self.save_status)
        footer.addStretch(1)
        v.addLayout(footer)

    def _save(self) -> None:
        content = self.editor.toPlainText()
        self.save_status.setText("saving…")
        self.save_btn.setEnabled(False)
        try:
            self.api.artifact_update(self.job_id, self.rel_path, content)
        except APIError as exc:
            self.save_status.setStyleSheet("color: #991b1b; font-size: 11px;")
            self.save_status.setText(f"failed: {exc}")
            self.save_btn.setEnabled(True)
            return
        self.save_status.setStyleSheet("color: #065f46; font-size: 11px;")
        self.save_status.setText("saved ✓")
        self.save_btn.setEnabled(True)


class ManualExecutePanel(QWidget):
    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.job_id: Optional[str] = None
        self._sse: Optional[SSELogThread] = None
        self._runner_job_id: Optional[int] = None
        self._artifact_cards: List[_ArtifactCard] = []
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)

        # Header
        header = QLabel("🔧 Manual Executor")
        header.setObjectName("h1")
        outer.addWidget(header)

        self.subheader = QLabel("Select a Ticket from Worklist first.")
        self.subheader.setObjectName("hint")
        self.subheader.setWordWrap(True)
        outer.addWidget(self.subheader)

        blurb = QLabel(
            "Runs Cucumber once against the materialized artifacts. No auto-heal — "
            "edit + re-run yourself. Reserved for debugging beside the autonomous runner."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color: #6b7280; font-size: 12px;")
        outer.addWidget(blurb)

        # Everything below scrolls (artifacts panel gets tall).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body_holder = QWidget()
        body = QVBoxLayout(body_holder)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        scroll.setWidget(body_holder)
        outer.addWidget(scroll, 1)

        # Run row.
        # Headless / Headed radios are kept in the widget tree (checked
        # state defaults to Headless=True) but hidden — every manual run
        # goes through headless mode. Restoring the toggle is a one-line
        # `setVisible(True)` on both radios.
        run_row = QHBoxLayout()
        self.headless_radio = QRadioButton("Headless")
        self.headless_radio.setChecked(True)
        self.headless_radio.setVisible(False)
        run_row.addWidget(self.headless_radio)
        self.headed_radio = QRadioButton("Headed (visible browser)")
        self.headed_radio.setVisible(False)
        run_row.addWidget(self.headed_radio)

        self.run_btn = QPushButton("▶ Run once (manual)")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        run_row.addWidget(self.run_btn)

        self.stop_btn = QPushButton("■ Stop tail")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_stream)
        run_row.addWidget(self.stop_btn)

        self.push_btn = QPushButton("🚀 Push")
        self.push_btn.setObjectName("success")
        self.push_btn.setEnabled(False)
        self.push_btn.setToolTip("Enabled after a GREEN manual run.")
        self.push_btn.clicked.connect(self._push)
        run_row.addWidget(self.push_btn)
        run_row.addStretch(1)
        body.addLayout(run_row)

        self.run_status = QLabel("idle")
        self.run_status.setStyleSheet(
            "background-color: #dbeafe; color: #1d4ed8; padding: 2px 8px; "
            "border-radius: 10px; font-size: 11px;"
        )
        self.run_status.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        body.addWidget(self.run_status)

        # Live log
        log_label = QLabel("Live log")
        log_label.setStyleSheet("font-weight: 600;")
        body.addWidget(log_label)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("terminal")
        self.log_view.setPlaceholderText("(no runs yet — click ▶ Run once)")
        mono = QFont("JetBrains Mono, Menlo, Consolas, monospace", 10)
        self.log_view.setFont(mono)
        self.log_view.setMinimumHeight(200)
        body.addWidget(self.log_view)

        # Fix with LLM box
        fix_frame = QFrame()
        fix_frame.setStyleSheet(
            "QFrame { border: 1px solid #d1d5db; border-radius: 6px; "
            "background-color: #fafafa; padding: 8px; }"
        )
        fix_layout = QVBoxLayout(fix_frame)
        fix_layout.setContentsMargins(10, 10, 10, 10)
        fix_layout.setSpacing(6)

        fix_title = QLabel("🩹 Fix with LLM")
        fix_title.setStyleSheet("font-weight: 700; border: none; background: transparent;")
        fix_layout.addWidget(fix_title)

        fix_blurb = QLabel(
            "Paste the error line(s) and, optionally, any HTML / DOM snippet to help "
            "the LLM pick the right selector. It sees every artifact and rewrites "
            "whichever files it needs."
        )
        fix_blurb.setWordWrap(True)
        fix_blurb.setStyleSheet(
            "color: #6b7280; font-size: 11px; border: none; background: transparent;"
        )
        fix_layout.addWidget(fix_blurb)

        fix_layout.addWidget(self._fix_label("Error / diagnosis:"))
        self.fix_error = QTextEdit()
        self.fix_error.setPlaceholderText("Paste the error line(s) from the live log above…")
        self.fix_error.setFont(mono)
        self.fix_error.setFixedHeight(90)
        fix_layout.addWidget(self.fix_error)

        fix_layout.addWidget(self._fix_label("Instructions / HTML snippet (optional):"))
        self.fix_hint = QTextEdit()
        self.fix_hint.setPlaceholderText(
            "e.g. Real DOM: <button id='onetrust-accept-btn-handler'>Accept</button>\n"
            "or free-form instructions like 'use data-testid on the year selector'."
        )
        self.fix_hint.setFont(mono)
        self.fix_hint.setFixedHeight(90)
        fix_layout.addWidget(self.fix_hint)

        fix_btn_row = QHBoxLayout()
        self.fix_btn = QPushButton("🩹 Fix with LLM")
        self.fix_btn.clicked.connect(self._fix)
        fix_btn_row.addWidget(self.fix_btn)

        self.fix_status = QLabel("")
        self.fix_status.setStyleSheet(
            "color: #6b7280; font-size: 11px; border: none; background: transparent;"
        )
        fix_btn_row.addWidget(self.fix_status)
        fix_btn_row.addStretch(1)
        fix_layout.addLayout(fix_btn_row)

        self.fix_diag = QPlainTextEdit()
        self.fix_diag.setReadOnly(True)
        self.fix_diag.setObjectName("codeBlock")
        self.fix_diag.setPlaceholderText("Last LLM diagnosis appears here after a fix.")
        self.fix_diag.setMaximumHeight(140)
        self.fix_diag.setVisible(False)
        fix_layout.addWidget(self.fix_diag)

        body.addWidget(fix_frame)

        # Editable artifacts
        arts_label = QLabel("Editable artifacts")
        arts_label.setStyleSheet("font-weight: 600;")
        body.addWidget(arts_label)

        self.arts_container = QWidget()
        self.arts_layout = QVBoxLayout(self.arts_container)
        self.arts_layout.setContentsMargins(0, 0, 0, 0)
        self.arts_layout.setSpacing(8)
        self.arts_placeholder = QLabel("Pick a job above to load its artifacts.")
        self.arts_placeholder.setStyleSheet("color: #6b7280; font-size: 12px;")
        self.arts_layout.addWidget(self.arts_placeholder)
        body.addWidget(self.arts_container)

        body.addStretch(1)

    def _fix_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(
            "color: #6b7280; font-size: 11px; border: none; background: transparent;"
        )
        return lab

    # ------------------------------------------------------------------
    def set_job(self, job_id: str, jira_key: str = "") -> None:
        self.job_id = job_id
        suffix = f" — {jira_key}" if jira_key else ""
        if job_id:
            self.subheader.setText(f"Job {job_id}{suffix}")
        else:
            self.subheader.setText("Select a Ticket from Worklist first.")
        self.log_view.clear()
        self._stop_stream()
        self._runner_job_id = None
        self._set_status("idle", "info")
        self.push_btn.setEnabled(False)
        self._reload_artifacts()

    # ------------------------------------------------------------------
    def _reload_artifacts(self) -> None:
        # Clear existing cards.
        for card in self._artifact_cards:
            card.setParent(None)
            card.deleteLater()
        self._artifact_cards = []
        self.arts_placeholder.setVisible(False)

        if not self.job_id:
            self.arts_placeholder.setText("Pick a job above to load its artifacts.")
            self.arts_placeholder.setVisible(True)
            return

        try:
            job = self.api.get_job(self.job_id)
        except APIError as exc:
            self.arts_placeholder.setText(f"Failed to load job: {exc}")
            self.arts_placeholder.setVisible(True)
            return

        artifacts = list(job.get("artifacts") or [])
        if not artifacts:
            self.arts_placeholder.setText("No artifacts on this job yet.")
            self.arts_placeholder.setVisible(True)
            return

        for art in artifacts:
            card = _ArtifactCard(self.api, self.job_id, art)
            self.arts_layout.addWidget(card)
            self._artifact_cards.append(card)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        if not self.job_id:
            QMessageBox.warning(self, "No job", "Pick a Jira ticket from Worklist first.")
            return
        headed = self.headed_radio.isChecked()
        self.log_view.clear()
        self._set_status("enqueuing…", "info")
        self.run_btn.setEnabled(False)
        try:
            payload = self.api.manual_cucumber_run(self.job_id, headed=headed)
        except APIError as exc:
            self._set_status("run failed", "bad")
            QMessageBox.critical(self, "Manual run failed", str(exc))
            self.run_btn.setEnabled(True)
            return

        runner_id = payload.get("runner_job_id")
        if not isinstance(runner_id, int):
            self._set_status("no runner id", "bad")
            self.run_btn.setEnabled(True)
            self.log_view.setPlainText(json.dumps(payload, indent=2))
            return

        self._runner_job_id = runner_id
        self._set_status(f"streaming runner {runner_id}…", "info")
        self._start_stream(runner_id)

    # ------------------------------------------------------------------
    def _start_stream(self, runner_id: int) -> None:
        self._stop_stream()
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
        self._set_status(f"cucumber done · state={state} rc={rc} · finalizing…", "info")
        self.stop_btn.setEnabled(False)
        self.run_btn.setEnabled(True)

        if self._runner_job_id is None or not self.job_id:
            return
        try:
            final = self.api.manual_cucumber_finalize(self.job_id, self._runner_job_id)
        except APIError as exc:
            self._set_status(f"finalize failed: {exc}", "bad")
            return
        all_passed = bool(final.get("all_passed"))
        final_state = str(final.get("final_state") or "")
        iteration = final.get("iteration")
        if all_passed:
            self._set_status(
                f"GREEN · iteration {iteration} · push unlocked",
                "ok",
            )
            self.push_btn.setEnabled(True)
        else:
            self._set_status(
                f"RED · iteration {iteration} · edit or fix and re-run",
                "bad",
            )
        # Refresh artifacts so any DB-side changes (rare on manual runs) show.
        self._reload_artifacts()

    def _on_stream_error(self, msg: str) -> None:
        self._set_status(f"⚠ {msg}", "bad")
        self.stop_btn.setEnabled(False)
        self.run_btn.setEnabled(True)

    # ------------------------------------------------------------------
    def _push(self) -> None:
        if not self.job_id:
            return
        self.push_btn.setEnabled(False)
        self._set_status("pushing to Jira…", "info")
        try:
            resp = self.api.approve_stage(self.job_id, "execute")
        except APIError as exc:
            QMessageBox.critical(self, "Push to Jira failed", str(exc))
            self._set_status("push failed", "bad")
            self.push_btn.setEnabled(True)
            return
        headline = str(resp.get("headline") or "")
        issue = str(resp.get("jira_issue_key") or "")
        self._set_status(f"pushed · {issue}", "ok")
        QMessageBox.information(
            self,
            "Pushed",
            f"Comment posted to {issue}." + (f"\nHeadline: {headline}" if headline else ""),
        )

    # ------------------------------------------------------------------
    def _fix(self) -> None:
        if not self.job_id:
            QMessageBox.warning(self, "No job", "Pick a Jira ticket from Worklist first.")
            return
        error_message = self.fix_error.toPlainText().strip()
        if not error_message:
            QMessageBox.warning(
                self,
                "Missing error",
                "Paste the error line(s) into the 'Error / diagnosis' box first.",
            )
            return
        hint = self.fix_hint.toPlainText().strip()
        combined = error_message + (f"\n\nOperator hint:\n{hint}" if hint else "")

        self.fix_btn.setEnabled(False)
        self.fix_status.setText("thinking (LLM)…")
        self.fix_status.setStyleSheet(
            "color: #1d4ed8; font-size: 11px; border: none; background: transparent;"
        )
        try:
            resp = self.api.manual_artifact_fix(self.job_id, combined)
        except APIError as exc:
            self.fix_status.setStyleSheet(
                "color: #991b1b; font-size: 11px; border: none; background: transparent;"
            )
            self.fix_status.setText(f"failed: {exc}")
            self.fix_btn.setEnabled(True)
            return

        applied = list(resp.get("patches_applied") or [])
        offered = int(resp.get("patches_offered") or 0)
        diagnosis = str(resp.get("diagnosis") or "")

        if applied:
            self.fix_status.setStyleSheet(
                "color: #065f46; font-size: 11px; border: none; background: transparent;"
            )
            self.fix_status.setText(
                f"patched {len(applied)} file(s): {', '.join(applied[:3])}"
                + ("…" if len(applied) > 3 else "")
            )
            self.fix_diag.setVisible(False)
        else:
            self.fix_status.setStyleSheet(
                "color: #b45309; font-size: 11px; border: none; background: transparent;"
            )
            self.fix_status.setText(
                f"no patches applied ({offered} offered). See diagnosis below."
            )
            self.fix_diag.setVisible(True)

        # Always populate diagnosis so it's inspectable.
        trace = resp.get("tool_trace") or []
        trace_lines = "\n".join(
            f"  turn {t.get('turn','?')}: {t.get('tool','?')}({json.dumps(t.get('args') or {}, separators=(',', ':'))[:80]})"
            for t in trace
            if isinstance(t, dict)
        )
        parts = []
        if diagnosis:
            parts.append(f"Diagnosis:\n{diagnosis}")
        if trace_lines:
            parts.append(f"Tool trace ({len(trace)} calls):\n{trace_lines}")
        self.fix_diag.setPlainText("\n\n".join(parts) if parts else "(no output)")

        self.fix_btn.setEnabled(True)
        # If any files were patched, reload the artifact cards so the operator
        # sees the new content.
        if applied:
            self._reload_artifacts()

    # ------------------------------------------------------------------
    def _set_status(self, text: str, kind: str) -> None:
        colors = {
            "ok":   ("#d1fae5", "#065f46"),
            "bad":  ("#fee2e2", "#991b1b"),
            "info": ("#dbeafe", "#1d4ed8"),
        }
        bg, fg = colors.get(kind, colors["info"])
        self.run_status.setText(text)
        self.run_status.setStyleSheet(
            f"background-color: {bg}; color: {fg}; padding: 2px 8px; "
            "border-radius: 10px; font-size: 11px;"
        )
