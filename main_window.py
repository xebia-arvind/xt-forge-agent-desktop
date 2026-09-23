"""
Top-level QMainWindow — top bar, left sidebar, stacked content area.

Sidebar layout:
  WORKFLOW  → Worklist (default landing)
  PIPELINE  → Feature, Test Design, Plan, Review, Execute, Execution Summary

Test Design hosts a segmented toggle so PR Analysis lives inside it
instead of getting its own sidebar entry.
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
    QProgressDialog,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import auth_store
from api_client import APIClient, APIError, AuthError
from ui.icons import bi_icon
from workers.agent_run_thread import AgentRunThread


def _logo_asset_path() -> Path:
    """Resolve the XT-Forge wordmark (Phase 20 asset) whether we're
    running from source or a PyInstaller bundle. Mirrors the
    _asset_path helper in panels/_two_column.py."""
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else Path(__file__).resolve().parent
    return base / "ui" / "images" / "xt-forge-logo.png"


def _xtforge_display_name(api: APIClient) -> str:
    """Text for the top-bar identity pill. Prefers the xtforge.xebia.in
    identity (real user); falls back to the Django email if for some
    reason xtforge_login() didn't populate the identity (e.g. legacy
    single-login code path)."""
    identity = getattr(api, "xtforge_identity", None)
    if identity is not None and identity.display_name:
        return identity.display_name
    return api.state.email or ""
from panels.execute_container import ExecuteContainer
from panels.feature import FeaturePanel
from panels.jobs import JobsPanel
from panels.plan import PlanPanel
from panels.review import ReviewPanel
from panels.test_design_container import TestDesignContainer
from panels.worklist import WorklistPanel


# Phase 19 — tuple grew from 3 to 4: (slug, label, section, bootstrap-icon-name).
# Emoji removed from labels; icons come from `ui.icons.bi_icon()`.
NAV_ITEMS = [
    ("worklist",     "Worklist",          "workflow",  "folder2"),
    ("feature",      "Feature",           "pipeline",  "puzzle"),
    ("manual_tests", "Test Design",       "pipeline",  "journal-text"),
    ("review",       "Review",            "pipeline",  "search"),
    ("execute",      "Execute",           "pipeline",  "play-fill"),
    ("jobs",         "Execution Summary", "pipeline",  "graph-up-arrow"),
]

# Plan runs in the background between Test Design and Review — no sidebar
# entry, no user-visible panel. The instance still lives in self._panels so
# set_job hydration works, but it's never shown.


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

        # Brand: PNG logo (Aug 2026 request — replaces the 🛡️ XT-Forge text
        # with the wordmark asset). Falls back to the text label if the
        # PNG is missing so dev branches without the asset still boot.
        _brand_logo_path = _logo_asset_path()
        if _brand_logo_path.exists():
            brand = QLabel()
            brand.setObjectName("brand")
            _brand_pm = QPixmap(str(_brand_logo_path))
            brand.setPixmap(_brand_pm.scaledToHeight(36, Qt.SmoothTransformation))
        else:
            brand = QLabel("🛡️  XT-Forge")
            brand.setObjectName("brand")
        top_layout.addWidget(brand)
        top_layout.addStretch(1)

        client_label_prefix = QLabel("Project:")
        client_label_prefix.setObjectName("hint")
        top_layout.addWidget(client_label_prefix)

        # Header project dropdown. Populated from the xtforge.xebia.in
        # projects list the user picked from at login. Switching entries
        # updates api.xtforge_project so downstream reads pick it up.
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("clientPicker")
        self.client_combo.setMinimumWidth(180)
        self.client_combo.activated.connect(self._on_project_switch)
        top_layout.addWidget(self.client_combo)

        # Top-bar identity pill shows the xtforge.xebia.in user (real
        # end-user identity) rather than the hard-coded Django email
        # used for the silent internal login.
        self.email_label = QLabel(_xtforge_display_name(self.api))
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
        self._panels["manual_tests"] = TestDesignContainer(self.api)
        self._panels["plan"] = PlanPanel(self.api)
        self._panels["review"] = ReviewPanel(self.api)
        self._panels["execute"] = ExecuteContainer(self.api)

        # Stack order mirrors sidebar order (Worklist is the landing panel).
        # PR Analysis lives inside Test Design's segmented toggle now — it
        # has no standalone sidebar entry.
        for slug in ("worklist", "feature", "manual_tests", "plan", "review", "execute", "jobs"):
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

        # Initial state — Worklist is the landing panel (row 1 = first
        # selectable row after the WORKFLOW header at row 0). Worklist
        # auto-loads via its showEvent, so no explicit reload here.
        self.sidebar.setCurrentRow(1)

        # Populate the header project dropdown once the UI is up.
        self._populate_project_combo()

    def _populate_project_combo(self) -> None:
        """Populate the header project dropdown from the xtforge.xebia.in
        projects list. Preselects whatever the user picked in the login
        picker dialog. Falls back to a re-fetch if the client didn't
        cache the projects on itself."""
        try:
            projects = self.api.list_xtforge_projects()
        except (APIError, AuthError):
            projects = []

        active_project = self.api.xtforge_project or {}
        active_id = str(active_project.get("id") or "")

        # If we couldn't fetch, at least show the active project so the
        # header isn't blank.
        if not projects and active_project:
            projects = [active_project]

        self._client_options = projects

        self.client_combo.blockSignals(True)
        self.client_combo.clear()
        selected_index = 0
        for i, p in enumerate(projects):
            display = str(p.get("projectName") or p.get("id") or "—")
            self.client_combo.addItem(display, userData=str(p.get("id") or ""))
            if str(p.get("id") or "") == active_id:
                selected_index = i
        self.client_combo.setCurrentIndex(selected_index)
        # Single-project users shouldn't invite a pointless click.
        self.client_combo.setEnabled(len(projects) > 1)
        self.client_combo.blockSignals(False)

    def _on_project_switch(self, index: int) -> None:
        """Header dropdown activated by the user. Swap the active
        xtforge.xebia.in project and clear any in-flight job state."""
        new_id = str(self.client_combo.itemData(index) or "")
        prev_id = str((self.api.xtforge_project or {}).get("id") or "")
        if not new_id or new_id == prev_id:
            return

        new_project = None
        for p in self._client_options:
            if str(p.get("id") or "") == new_id:
                new_project = p
                break
        if new_project is None:
            return

        self.api.set_xtforge_project(new_project)

        # Clear the current job — it belonged to the previous project
        # scope and probably doesn't apply here.
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
                next_slug = order[i + 1]
                # Plan has no sidebar entry — it runs headlessly between
                # Test Design and Review. When Test Design approves we
                # generate the plan AND the artifacts in the background,
                # then land the user on the Review panel with the
                # artifacts already visible for inspection.
                if next_slug == "plan":
                    self._auto_generate_artifact_then_review()
                else:
                    self._select_slug(next_slug)
                return

    # ------------------------------------------------------------------
    # Background artifact generation — invoked after Test Design's Approve.
    # Two-phase pipeline behind a single "Generating Artifact" progress
    # dialog:
    #   1. Run Plan agent          -> approve_stage("plan")
    #   2. Run Artifacts agent     -> re-hydrate Review, land on Review
    # Review is intentionally NOT auto-approved — the user should inspect
    # the generated artifacts before pushing forward.
    def _auto_generate_artifact_then_review(self) -> None:
        if not self.current_job_id:
            return

        self._artifact_progress = QProgressDialog(
            "Preparing the plan for artifact generation…",
            None, 0, 0, self,
        )
        self._artifact_progress.setWindowTitle("Generating Artifact")
        self._artifact_progress.setLabelText(
            "Preparing the plan for artifact generation…\n"
            "This usually takes 30–90 seconds."
        )
        self._artifact_progress.setWindowModality(Qt.ApplicationModal)
        self._artifact_progress.setCancelButton(None)
        self._artifact_progress.setMinimumDuration(0)
        self._artifact_progress.setAutoClose(False)
        self._artifact_progress.setAutoReset(False)
        self._artifact_progress.setMinimumWidth(360)
        self._artifact_progress.show()

        self._plan_thread = AgentRunThread(
            self.api, self.current_job_id, "plan", parent=self
        )
        self._plan_thread.succeeded.connect(self._on_plan_run_succeeded)
        self._plan_thread.failed.connect(self._on_plan_run_failed)
        self._plan_thread.start()

    def _on_plan_run_succeeded(self, _result) -> None:
        # Backend stored plan output; approve it, then kick off artifact
        # generation without dropping the modal.
        try:
            self.api.approve_stage(self.current_job_id, "plan")
        except APIError as exc:
            self._close_artifact_progress()
            QMessageBox.critical(self, "Plan approve failed", str(exc))
            return
        self._update_artifact_progress(
            "Generating test artifact…\n"
            "This usually takes 30–90 seconds."
        )
        self._artifact_thread = AgentRunThread(
            self.api, self.current_job_id, "artifacts", parent=self
        )
        self._artifact_thread.succeeded.connect(self._on_artifact_run_succeeded)
        self._artifact_thread.failed.connect(self._on_artifact_run_failed)
        self._artifact_thread.start()

    def _on_plan_run_failed(self, message: str) -> None:
        self._close_artifact_progress()
        QMessageBox.critical(
            self,
            "Plan agent failed",
            f"The Plan step failed and artifact generation did not start.\n\n{message}",
        )

    def _on_artifact_run_succeeded(self, _result) -> None:
        # Re-hydrate Review so its scroll area picks up the newly-generated
        # artifacts on paint, then land the user there.
        review_panel = self._panels.get("review")
        if review_panel is not None and hasattr(review_panel, "set_job"):
            review_panel.set_job(self.current_job_id, self.current_jira_key)
        self._close_artifact_progress()
        self._select_slug("review")

    def _on_artifact_run_failed(self, message: str) -> None:
        self._close_artifact_progress()
        QMessageBox.critical(
            self,
            "Artifact generation failed",
            f"The artifact agent failed. You can retry from the Review panel.\n\n{message}",
        )
        # Still land on Review — user can click Run agent to retry there.
        self._select_slug("review")

    def _update_artifact_progress(self, text: str) -> None:
        dlg = getattr(self, "_artifact_progress", None)
        if dlg is not None:
            dlg.setLabelText(text)

    def _close_artifact_progress(self) -> None:
        dlg = getattr(self, "_artifact_progress", None)
        if dlg is not None:
            dlg.close()
            self._artifact_progress = None

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
