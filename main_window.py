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

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import auth_store
from api_client import APIClient, APIError, AuthError
from ui.icons import bi_icon


def _logo_asset_path() -> Path:
    """Resolve the XT-Forge wordmark (Phase 20 asset) whether we're
    running from source or a PyInstaller bundle. Mirrors the
    _asset_path helper in panels/_two_column.py."""
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else Path(__file__).resolve().parent
    return base / "ui" / "images" / "xt-forge-logo.png"
from panels.execute import ExecutePanel
from panels.feature import FeaturePanel
from panels.jobs import JobsPanel
from panels.manual_tests import ManualTestsPanel
from panels.plan import PlanPanel
from panels.review import ReviewPanel
from panels.worklist import WorklistPanel


# Phase 19 — tuple grew from 3 to 4: (slug, label, section, bootstrap-icon-name).
# Emoji removed from labels; icons come from `ui.icons.bi_icon()`.
NAV_ITEMS = [
    ("jobs",         "Jobs",         "analytics", "graph-up-arrow"),
    ("worklist",     "Worklist",     "workflow",  "folder2"),
    ("feature",      "Feature",      "pipeline",  "puzzle"),
    ("manual_tests", "Manual Tests", "pipeline",  "journal-text"),
    ("plan",         "Plan",         "pipeline",  "diagram-3"),
    ("review",       "Review",       "pipeline",  "search"),
    ("execute",      "Execute",      "pipeline",  "play-fill"),
]


class MainWindow(QMainWindow):
    logout_requested = Signal()
    # Phase 18 — emitted after a successful header-dropdown client switch.
    # Panels don't currently listen to this; the switch handler calls
    # `_refresh_current_panel()` directly. Kept as a signal so future
    # panels can subscribe without threading through MainWindow.
    client_changed = Signal(str)   # emits the new client's UUID

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("XT-Forge Agent")
        self.resize(1280, 800)
        self.current_job_id: str = ""
        self.current_jira_key: str = ""
        self._panels: Dict[str, QWidget] = {}
        self._client_options: list = []
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

        # Phase 18 — replaces the read-only client pill with a switching
        # dropdown. Populated on init via /auth/my-clients/. Selecting a
        # different item calls /auth/pick-client/ and refreshes the panel.
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("clientPicker")
        self.client_combo.setMinimumWidth(180)
        self.client_combo.activated.connect(self._on_client_switch)
        top_layout.addWidget(self.client_combo)

        self.email_label = QLabel(self.api.state.email or "")
        self.email_label.setObjectName("emailPill")
        top_layout.addWidget(self.email_label)

        self.logout_btn = QPushButton("Sign out")
        self.logout_btn.setObjectName("linkButton")
        self.logout_btn.clicked.connect(self._logout)
        top_layout.addWidget(self.logout_btn)

        # Phase 20 — brand wordmark on the far-right of the header.
        # Same asset used by the two-column login/setup shell. Silent
        # fallback when the PNG isn't present so builds don't crash on
        # branches that haven't checked the asset in.
        logo_path = _logo_asset_path()
        if logo_path.exists():
            self.header_logo = QLabel()
            self.header_logo.setObjectName("headerLogo")
            pm = QPixmap(str(logo_path))
            pm = pm.scaledToHeight(32, Qt.SmoothTransformation)
            self.header_logo.setPixmap(pm)
            top_layout.addWidget(self.header_logo)

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
        for slug, label, kind, icon_name in NAV_ITEMS:
            if kind == "analytics":
                self._add_nav_item(slug, label, icon_name)
        self._add_nav_header("WORKFLOW")
        for slug, label, kind, icon_name in NAV_ITEMS:
            if kind == "workflow":
                self._add_nav_item(slug, label, icon_name)
        self._add_nav_header("PIPELINE")
        for slug, label, kind, icon_name in NAV_ITEMS:
            if kind == "pipeline":
                self._add_nav_item(slug, label, icon_name)

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

        # Phase 18 — populate the header client dropdown once the UI is up.
        self._populate_client_combo()

    def _populate_client_combo(self) -> None:
        """Fetch /auth/my-clients/ and populate the top-right dropdown.
        Best-effort — a failure here doesn't block the shell; we fall
        back to a single-item combo showing the active client name."""
        try:
            data = self.api.list_my_clients()
            clients = list(data.get("clients") or [])
        except (APIError, AuthError):
            clients = []

        active_id = str(self.api.state.client_secret or "")
        active_name = self.api.state.client_name or ""

        # If we couldn't fetch, at least show the active client so the
        # header isn't blank.
        if not clients and active_name:
            clients = [{"id": active_id, "name": active_name, "slug": ""}]

        self._client_options = clients

        self.client_combo.blockSignals(True)
        self.client_combo.clear()
        selected_index = 0
        for i, c in enumerate(clients):
            self.client_combo.addItem(c.get("name") or c.get("slug") or c.get("id") or "—",
                                      userData=str(c.get("id") or ""))
            if str(c.get("id") or "") == active_id:
                selected_index = i
        self.client_combo.setCurrentIndex(selected_index)
        # Single-client tenants shouldn't invite a pointless click.
        self.client_combo.setEnabled(len(clients) > 1)
        self.client_combo.blockSignals(False)

    def _on_client_switch(self, index: int) -> None:
        """Header dropdown activated by the user. Swap tenants and refresh
        whatever panel is currently visible."""
        new_id = str(self.client_combo.itemData(index) or "")
        prev_id = str(self.api.state.client_secret or "")
        if not new_id or new_id == prev_id:
            return
        try:
            self.api.pick_client(new_id)
        except (APIError, AuthError) as exc:
            # Revert the combo to the previous selection and surface a
            # modal — silent failure would leave the operator staring at
            # the wrong client name.
            QMessageBox.warning(
                self, "Client switch failed",
                f"Could not switch client: {exc}\n\nStaying on the "
                "previous tenant.",
            )
            self._populate_client_combo()
            return

        # Persist the new session so a keychain re-hydrate doesn't fall
        # back to a stale token.
        auth_store.save_session(
            access=self.api.state.access,
            refresh=self.api.state.refresh,
            email=self.api.state.email,
            client_name=self.api.state.client_name,
            client_secret=self.api.state.client_secret,
        )
        # Clear the current job — it belonged to the previous tenant and
        # its id won't resolve under the new JWT.
        self.current_job_id = ""
        self.current_jira_key = ""
        for slug in ("feature", "manual_tests", "plan", "review", "execute"):
            panel = self._panels.get(slug)
            if panel is not None and hasattr(panel, "set_job"):
                try:
                    panel.set_job("", "")
                except Exception:
                    pass
        self.client_changed.emit(new_id)
        self._refresh_current_panel()

    def _refresh_current_panel(self) -> None:
        """Re-hydrate whichever panel is currently visible. Jobs + Worklist
        have explicit reload paths; stage panels re-fetch via set_job()."""
        current = self.stack.currentWidget()
        if current is self._panels.get("jobs") and hasattr(current, "reload"):
            current.reload()
            return
        if current is self._panels.get("worklist"):
            # WorklistPanel auto-loads via showEvent — trigger it by
            # re-selecting the row.
            row = self.sidebar.currentRow()
            self.sidebar.setCurrentRow(-1)
            self.sidebar.setCurrentRow(row)

    # ------------------------------------------------------------------
    def _add_nav_header(self, text: str) -> None:
        header = QListWidgetItem(text)
        header.setFlags(Qt.NoItemFlags)   # not selectable
        header.setData(Qt.UserRole, None)
        header.setForeground(Qt.gray)
        self.sidebar.addItem(header)

    def _add_nav_item(self, slug: str, label: str, icon_name: str = "") -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, slug)
        if icon_name:
            # Phase 19 — Bootstrap Icons. Colour matches the sidebar's
            # near-white text (#dbeafe per style.qss #sidebar nav a rule).
            item.setIcon(bi_icon(icon_name, color="#dbeafe", size=18))
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
