"""
Top-level QMainWindow — top bar, left sidebar, stacked content area.

Phase 7.3 — Mirrors the Phase 6.4 Django sidebar exactly:
  ANALYTICS  → Jobs (default landing)
  WORKFLOW   → Worklist
  PIPELINE   → Feature, Manual Tests, Plan, Review, Execute

Config, Generate, and Healer are intentionally not present — same as Django.
"""
from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import auth_store
from api_client import APIClient
from panels.execute import ExecutePanel
from panels.feature import FeaturePanel
from panels.jobs import JobsPanel
from panels.manual_tests import ManualTestsPanel
from panels.plan import PlanPanel
from panels.review import ReviewPanel
from panels.worklist import WorklistPanel


NAV_ITEMS = [
    ("jobs",         "📈  Jobs",         "analytics"),
    ("worklist",     "🗂  Worklist",     "workflow"),
    ("feature",      "🧬  Feature",      "pipeline"),
    ("manual_tests", "📝  Manual Tests", "pipeline"),
    ("plan",         "🗺️  Plan",         "pipeline"),
    ("review",       "🔍  Review",       "pipeline"),
    ("execute",      "▶  Execute",       "pipeline"),
]


class MainWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("XT-Forge Agent")
        self.resize(1280, 800)
        self.current_job_id: str = ""
        self.current_jira_key: str = ""
        self._panels: Dict[str, QWidget] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        top_bar = QWidget()
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(52)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(20, 8, 20, 8)

        title = QLabel("🛡️  XT-Forge")
        title.setObjectName("brand")
        top_layout.addWidget(title)
        top_layout.addStretch(1)

        client_label_prefix = QLabel("Client:")
        client_label_prefix.setObjectName("hint")
        top_layout.addWidget(client_label_prefix)

        self.client_label = QLabel(self.api.state.client_name or "—")
        self.client_label.setObjectName("clientPill")
        top_layout.addWidget(self.client_label)

        self.email_label = QLabel(self.api.state.email or "")
        self.email_label.setObjectName("emailPill")
        top_layout.addWidget(self.email_label)

        self.logout_btn = QPushButton("Sign out")
        self.logout_btn.setObjectName("linkButton")
        self.logout_btn.clicked.connect(self._logout)
        top_layout.addWidget(self.logout_btn)

        root.addWidget(top_bar)

        # Sidebar + content
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(220)

        # Phase 7.3 — Analytics on top, Jobs as the landing row.
        self._add_nav_header("ANALYTICS")
        for slug, label, kind in NAV_ITEMS:
            if kind == "analytics":
                self._add_nav_item(slug, label)
        self._add_nav_header("WORKFLOW")
        for slug, label, kind in NAV_ITEMS:
            if kind == "workflow":
                self._add_nav_item(slug, label)
        self._add_nav_header("PIPELINE")
        for slug, label, kind in NAV_ITEMS:
            if kind == "pipeline":
                self._add_nav_item(slug, label)

        self.sidebar.currentRowChanged.connect(self._nav_changed)
        body_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("contentStack")
        body_layout.addWidget(self.stack, 1)

        root.addWidget(body, 1)

        # Instantiate panels
        self._panels["jobs"] = JobsPanel(self.api)
        self._panels["worklist"] = WorklistPanel(self.api)
        self._panels["feature"] = FeaturePanel(self.api)
        self._panels["manual_tests"] = ManualTestsPanel(self.api)
        self._panels["plan"] = PlanPanel(self.api)
        self._panels["review"] = ReviewPanel(self.api)
        self._panels["execute"] = ExecutePanel(self.api)

        # Stack order mirrors nav order — Jobs first so it's the default view.
        for slug in ("jobs", "worklist", "feature", "manual_tests", "plan", "review", "execute"):
            self.stack.addWidget(self._panels[slug])

        # Wire the worklist → pipeline transition
        self._panels["worklist"].pipeline_started.connect(self._on_pipeline_started)
        # Phase 14 — reuse the existing job-opened handler when the autopilot
        # dialog finishes (either successfully on artifact review, or on
        # a mid-chain failure that navigated back to that stage's panel).
        if hasattr(self._panels["worklist"], "autopilot_finished"):
            self._panels["worklist"].autopilot_finished.connect(
                self._on_job_opened_from_dashboard
            )
        for slug in ("feature", "manual_tests", "plan", "review"):
            self._panels[slug].approved.connect(self._advance_stage)

        # Jobs panel can deep-link into other stage panels (its "🔎 Open" button).
        if hasattr(self._panels["jobs"], "job_opened"):
            self._panels["jobs"].job_opened.connect(self._on_job_opened_from_dashboard)

        # Initial state — Jobs is the landing panel (row 1 = first selectable
        # row after the ANALYTICS header at row 0).
        self.sidebar.setCurrentRow(1)
        self._panels["jobs"].reload() if hasattr(self._panels["jobs"], "reload") else None

    # ------------------------------------------------------------------
    def _add_nav_header(self, text: str) -> None:
        header = QListWidgetItem(text)
        header.setFlags(Qt.NoItemFlags)   # not selectable
        header.setData(Qt.UserRole, None)
        header.setForeground(Qt.gray)
        self.sidebar.addItem(header)

    def _add_nav_item(self, slug: str, label: str) -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, slug)
        self.sidebar.addItem(item)

    def _nav_changed(self, row: int) -> None:
        item = self.sidebar.item(row)
        if item is None:
            return
        slug = item.data(Qt.UserRole)
        if not slug:
            return
        target = self._panels.get(slug)
        if target is not None:
            self.stack.setCurrentWidget(target)

    # ------------------------------------------------------------------
    def _on_pipeline_started(self, job_id: str, jira_key: str) -> None:
        self.current_job_id = job_id
        self.current_jira_key = jira_key
        for slug in ("feature", "manual_tests", "plan", "review", "execute"):
            panel = self._panels[slug]
            if hasattr(panel, "set_job"):
                panel.set_job(job_id, jira_key)
        # Jump to Feature
        self._select_slug("feature")

    def _advance_stage(self) -> None:
        current_widget = self.stack.currentWidget()
        order = ["feature", "manual_tests", "plan", "review", "execute"]
        for i, slug in enumerate(order):
            if self._panels.get(slug) is current_widget and i + 1 < len(order):
                self._select_slug(order[i + 1])
                return

    def _select_slug(self, slug: str) -> None:
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            if item.data(Qt.UserRole) == slug:
                self.sidebar.setCurrentRow(i)
                return

    # ------------------------------------------------------------------
    def _on_job_opened_from_dashboard(self, job_id: str, jira_key: str, target_slug: str) -> None:
        """
        Deep-link from Jobs dashboard row's 🔎 Open button. Sets the job on
        every downstream panel + jumps to the requested stage panel. Same
        UX as clicking a Jira ticket in Worklist then navigating manually,
        just one click.
        """
        self.current_job_id = job_id
        self.current_jira_key = jira_key
        for slug in ("feature", "manual_tests", "plan", "review", "execute"):
            panel = self._panels.get(slug)
            if panel is not None and hasattr(panel, "set_job"):
                panel.set_job(job_id, jira_key)
        self._select_slug(target_slug or "execute")

    def _logout(self) -> None:
        auth_store.clear_session()
        self.api.logout()
        self.logout_requested.emit()
