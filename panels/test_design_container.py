"""
Test Design container — two subviews behind a segmented toggle:

  [ Test Design ]  [ PR Analysis ]

Test Design is the original ManualTestsPanel (LLM-generated GIVEN/WHEN/THEN
cards). PR Analysis is the standalone PRAnalysisPanel that wraps the
imperial-ai-automation /pr-to-testcases skill.

Only Test Design participates in the Jira pipeline (set_job / approved).
PR Analysis is standalone and ignores job context.

Exposes:
  - set_job(job_id, jira_key)  — forwarded to the inner ManualTestsPanel
  - approved (Signal)          — re-emitted from ManualTestsPanel

so main_window can drive it exactly like the plain ManualTestsPanel it
replaces.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from api_client import APIClient
from panels.manual_tests import ManualTestsPanel
from panels.pr_analysis import PRAnalysisPanel


_TOGGLE_STYLE = """
QPushButton#toggleLeft, QPushButton#toggleRight {
    background-color: transparent;
    color: #4b5563;
    border: 1px solid #d1d5db;
    padding: 6px 20px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#toggleLeft:checked, QPushButton#toggleRight:checked {
    background-color: #4c1d95;
    color: #ffffff;
    border: 1px solid #4c1d95;
}
QPushButton#toggleLeft:hover:!checked, QPushButton#toggleRight:hover:!checked {
    background-color: #f3f4f6;
}
QPushButton#toggleLeft {
    border-top-left-radius: 6px;
    border-bottom-left-radius: 6px;
}
QPushButton#toggleRight {
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    border-left: none;
}
"""


class TestDesignContainer(QWidget):
    approved = Signal()

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 0)
        outer.setSpacing(12)

        # Toggle row — segmented control style.
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(0)

        self.btn_test_design = QPushButton("Test Design")
        self.btn_test_design.setObjectName("toggleLeft")
        self.btn_test_design.setCheckable(True)
        self.btn_test_design.setChecked(True)

        self.btn_pr_analysis = QPushButton("PR Analysis")
        self.btn_pr_analysis.setObjectName("toggleRight")
        self.btn_pr_analysis.setCheckable(True)

        self.setStyleSheet(_TOGGLE_STYLE)

        self._toggle_group = QButtonGroup(self)
        self._toggle_group.setExclusive(True)
        self._toggle_group.addButton(self.btn_test_design, 0)
        self._toggle_group.addButton(self.btn_pr_analysis, 1)
        self._toggle_group.idClicked.connect(self._on_toggle)

        toggle_row.addWidget(self.btn_test_design)
        toggle_row.addWidget(self.btn_pr_analysis)
        toggle_row.addStretch(1)
        outer.addLayout(toggle_row)

        # Stacked pages.
        self.stack = QStackedWidget()
        self.test_design = ManualTestsPanel(self.api)
        self.pr_analysis = PRAnalysisPanel()
        self.stack.addWidget(self.test_design)
        self.stack.addWidget(self.pr_analysis)
        outer.addWidget(self.stack, 1)

        # Forward the inner panel's approved signal so main_window can wire
        # advance-stage as if this were the raw ManualTestsPanel.
        self.test_design.approved.connect(self.approved.emit)

    # ------------------------------------------------------------------
    def _on_toggle(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    # main_window fan-out calls this — only the Test Design side cares
    # about job context; PR Analysis is standalone.
    def set_job(self, job_id: str, jira_key: str = "") -> None:
        self.test_design.set_job(job_id, jira_key)
