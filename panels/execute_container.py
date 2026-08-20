"""
Execute container — matches the browser Execute panel.

Historically had two tabs (Autonomous + Manual). The Autonomous tab is
currently HIDDEN per operator request (Aug 2026) to mirror the Django
dashboard's `AUTOPILOT_TAB_HIDDEN` decision, but the code is preserved
for easy revival — see AUTOPILOT_TAB_HIDDEN below.

Exposes `set_job(job_id, jira_key)` so main_window can drive it exactly
like it did the plain ExecutePanel.
"""
from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from api_client import APIClient
from panels.execute import ExecutePanel
from panels.manual_execute import ManualExecutePanel

# AUTOPILOT_TAB_HIDDEN — flip to True to bring back the Autonomous tab.
# When False, only the Manual Executor is shown (no tab strip at all).
_SHOW_AUTONOMOUS_TAB = False


class ExecuteContainer(QWidget):
    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Both panels are constructed unconditionally so future re-enable
        # is a single flag flip — no risk of hidden JS-style regressions.
        self.autonomous = ExecutePanel(self.api)
        self.manual = ManualExecutePanel(self.api)

        if _SHOW_AUTONOMOUS_TAB:
            self.tabs = QTabWidget()
            self.tabs.addTab(self.autonomous, "🤖 Autonomous")
            self.tabs.addTab(self.manual,     "🔧 Manual")
            outer.addWidget(self.tabs)
        else:
            # Autonomous instance still exists (so set_job doesn't skip it
            # and its state stays in sync), just not added to the layout.
            outer.addWidget(self.manual)

    # main_window calls this on every navigation / job change.
    def set_job(self, job_id: str, jira_key: str = "") -> None:
        self.autonomous.set_job(job_id, jira_key)
        self.manual.set_job(job_id, jira_key)
