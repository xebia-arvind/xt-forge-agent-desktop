"""
PR Analysis panel — thin PySide6 wrapper around the imperial-ai-automation
shell wrapper `scripts/pr-to-testcases.sh`.

The wrapper owns the whole run (claude call, markdown capture, HTML render,
open-in-browser). This panel just:

  1. Launches the wrapper as a QProcess so Qt keeps handling UI events.
  2. Shows a friendly status card (Idle / Running / Success / Failed).
  3. Detects success by checking the deterministic HTML output path on
     disk once the process exits — no log parsing race.
  4. On success, surfaces a clickable file://... link to the rendered HTML.

No HTML generation happens here. No API calls to the XT-Forge Django
backend — this screen is standalone and does not participate in the
Jira-driven pipeline (Feature → Execute).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# The default imperial-ai-automation checkout path. Overridable at launch
# time via IMPERIAL_AUTOMATION_DIR so power users can point at a different
# checkout without touching this file.
_DEFAULT_IMPERIAL_DIR = Path(
    os.environ.get(
        "IMPERIAL_AUTOMATION_DIR",
        "/Users/niraj.chaudhary/Desktop/ImperialAIAutomation",
    )
)

_STATUS_FAILED_RE = re.compile(r"^STATUS: FAILED \((.*)\)$", re.MULTILINE)


class PRAnalysisPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: Optional[QProcess] = None
        self._pr_id: str = ""
        self._elapsed_sec: int = 0
        self._collected_output: str = ""
        self._expected_html_path: Optional[Path] = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_elapsed)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        header = QLabel("PR Analysis")
        header.setObjectName("h1")
        outer.addWidget(header)

        hint = QLabel(
            "Enter a PR ID, pick a model, and click Run Analysis. "
            "A test-case report will be generated as HTML."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # Input row: PR ID + model + Run + Cancel
        input_row = QHBoxLayout()

        pr_label = QLabel("PR ID")
        pr_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        input_row.addWidget(pr_label)

        self.pr_input = QLineEdit()
        self.pr_input.setPlaceholderText("e.g. 40613")
        self.pr_input.setMaximumWidth(160)
        pr_regex = QRegularExpression(r"^[A-Za-z0-9\-]+$")
        self.pr_input.setValidator(QRegularExpressionValidator(pr_regex, self))
        self.pr_input.textChanged.connect(self._update_run_enabled)
        self.pr_input.returnPressed.connect(self._maybe_run)
        input_row.addWidget(self.pr_input)

        model_label = QLabel("Model")
        model_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        input_row.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.addItem("Opus 5", userData="claude-opus-5")
        self.model_combo.addItem("Sonnet 5", userData="claude-sonnet-5")
        self.model_combo.addItem("Haiku 4.5", userData="claude-haiku-4-5-20251001")
        self.model_combo.setCurrentIndex(0)
        input_row.addWidget(self.model_combo)

        self.run_btn = QPushButton("Run Analysis")
        self.run_btn.setObjectName("primary")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._maybe_run)
        input_row.addWidget(self.run_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        input_row.addWidget(self.cancel_btn)

        input_row.addStretch(1)
        outer.addLayout(input_row)

        # ------------------------------------------------------------------
        # Status card — the whole UX below the input row.
        self.card = QFrame()
        self.card.setObjectName("statusCard")
        self.card.setFrameShape(QFrame.StyledPanel)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(6)

        self.card_title = QLabel("Ready")
        self.card_title.setStyleSheet(
            "font-size: 17px; font-weight: 700; background: transparent; border: none;"
        )
        self.card_title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        card_layout.addWidget(self.card_title)

        self.card_body = QLabel(
            "Enter a PR ID above and click Run Analysis to generate a "
            "test-case report."
        )
        self.card_body.setWordWrap(True)
        self.card_body.setStyleSheet(
            "font-size: 13px; color: #4b5563; background: transparent; border: none;"
        )
        self.card_body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        card_layout.addWidget(self.card_body)

        self.card_link = QLabel("")
        self.card_link.setTextFormat(Qt.RichText)
        self.card_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.card_link.setOpenExternalLinks(True)
        self.card_link.setVisible(False)
        self.card_link.setStyleSheet(
            "font-size: 13px; font-weight: 600; background: transparent; border: none;"
        )
        self.card_link.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        card_layout.addWidget(self.card_link)

        self.card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        outer.addWidget(self.card)
        outer.addStretch(1)

        self._set_state("idle")

    # ------------------------------------------------------------------
    def _update_run_enabled(self) -> None:
        active = self._proc is not None
        has_text = bool(self.pr_input.text().strip())
        self.run_btn.setEnabled(has_text and not active)

    def _maybe_run(self) -> None:
        if not self.run_btn.isEnabled():
            return
        self._run()

    # ------------------------------------------------------------------
    def _run(self) -> None:
        pr_id = self.pr_input.text().strip()
        if not pr_id:
            return

        model_id = str(self.model_combo.currentData() or "")
        script_path = _DEFAULT_IMPERIAL_DIR / "scripts" / "pr-to-testcases.sh"
        if not script_path.exists():
            self._set_state(
                "failed",
                reason=(
                    f"Wrapper script not found:\n{script_path}\n\n"
                    "Set IMPERIAL_AUTOMATION_DIR to point at the "
                    "imperial-ai-automation checkout."
                ),
            )
            return

        self._pr_id = pr_id
        self._elapsed_sec = 0
        self._collected_output = ""
        self._expected_html_path = (
            _DEFAULT_IMPERIAL_DIR / "docs" / "test-cases" / f"PR-{pr_id}.html"
        )
        # Remove any prior HTML so a stale file can't be mistaken for a
        # fresh success.
        if self._expected_html_path.exists():
            try:
                self._expected_html_path.unlink()
            except OSError:
                pass

        env = QProcessEnvironment.systemEnvironment()
        env.insert("IMPERIAL_AUTOMATION_DIR", str(_DEFAULT_IMPERIAL_DIR))

        proc = QProcess(self)
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(str(_DEFAULT_IMPERIAL_DIR))
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(self._collect_output)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)

        program = "/bin/zsh"
        arguments = [str(script_path), pr_id, "--model", model_id]

        self._proc = proc
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.pr_input.setEnabled(False)
        self.model_combo.setEnabled(False)
        self._set_state("running")
        self._timer.start()
        proc.start(program, arguments)

    def _cancel(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        proc.terminate()
        if not proc.waitForFinished(3000):
            proc.kill()
            proc.waitForFinished(1000)

    # ------------------------------------------------------------------
    def _collect_output(self) -> None:
        if self._proc is None:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        if data:
            self._collected_output += data

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        # Drain any final bytes that may have arrived after the last
        # readyReadStandardOutput signal.
        self._collect_output()

        self._timer.stop()
        self.cancel_btn.setEnabled(False)
        self.pr_input.setEnabled(True)
        self.model_combo.setEnabled(True)
        self._proc = None
        self._update_run_enabled()

        # Truth source: the HTML file on disk. If it exists and the process
        # exited cleanly, this is a success — no dependency on stdout being
        # parseable.
        html_path = self._expected_html_path
        if exit_code == 0 and html_path is not None and html_path.exists():
            self._set_state("success", html_path=html_path)
            return

        # Otherwise, try to surface a helpful reason.
        failed_match = _STATUS_FAILED_RE.search(self._collected_output)
        if failed_match:
            reason = failed_match.group(1)
        elif exit_code != 0:
            reason = f"process exit {exit_code}"
        else:
            reason = "the wrapper finished but no HTML report was produced"
        self._set_state("failed", reason=reason)

    def _on_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.FailedToStart:
            self._timer.stop()
            self.cancel_btn.setEnabled(False)
            self.pr_input.setEnabled(True)
            self.model_combo.setEnabled(True)
            self._proc = None
            self._update_run_enabled()
            self._set_state("failed", reason="could not start /bin/zsh")

    # ------------------------------------------------------------------
    def _tick_elapsed(self) -> None:
        self._elapsed_sec += 1
        self._render_running_body()

    def _render_running_body(self) -> None:
        mm, ss = divmod(self._elapsed_sec, 60)
        self.card_body.setText(
            f"This usually takes 1–3 minutes. Elapsed {mm:02d}:{ss:02d}"
        )

    # ------------------------------------------------------------------
    def _set_state(
        self,
        state: str,
        reason: str = "",
        html_path: Optional[Path] = None,
    ) -> None:
        # Card visual per state — border + background tint communicate
        # status at a glance without any emoji.
        palettes = {
            "idle":    ("#e5e7eb", "#f9fafb", "#111827"),
            "running": ("#93c5fd", "#eff6ff", "#1d4ed8"),
            "success": ("#6ee7b7", "#ecfdf5", "#065f46"),
            "failed":  ("#fca5a5", "#fef2f2", "#991b1b"),
        }
        border, bg, fg = palettes.get(state, palettes["idle"])
        self.card.setStyleSheet(
            f"QFrame#statusCard {{ border: 1px solid {border}; "
            f"background-color: {bg}; border-radius: 10px; }}"
        )
        self.card_title.setStyleSheet(
            f"color: {fg}; font-size: 18px; font-weight: 700; "
            "background: transparent; border: none;"
        )

        if state == "idle":
            self.card_title.setText("Ready")
            self.card_body.setText(
                "Enter a PR ID above and click Run Analysis to generate a "
                "test-case report."
            )
            self.card_body.setVisible(True)
            self.card_link.setVisible(False)
            return

        if state == "running":
            self.card_title.setText(f"Analyzing PR #{self._pr_id}…")
            self._render_running_body()
            self.card_body.setVisible(True)
            self.card_link.setVisible(False)
            return

        if state == "success" and html_path is not None:
            self.card_title.setText(f"Analysis complete — PR #{self._pr_id}")
            self.card_body.setText(
                "The test-case report was generated successfully."
            )
            self.card_body.setVisible(True)
            self.card_link.setText(
                f'<a href="file://{html_path}" style="color: #065f46;">'
                f"Open PR-{self._pr_id}.html in browser</a>"
            )
            self.card_link.setVisible(True)
            return

        if state == "failed":
            self.card_title.setText(f"Analysis failed — PR #{self._pr_id}")
            self.card_body.setText(
                reason or "The wrapper reported a failure."
            )
            self.card_body.setVisible(True)
            self.card_link.setVisible(False)
            return
