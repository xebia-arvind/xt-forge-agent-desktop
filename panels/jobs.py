"""
Jobs dashboard — the desktop counterpart of the Django Jobs panel.

Ships Phase 7.1 of the desktop parity work: a landing page that shows every
`GenerationJob` in the tenant with stage-wise progression pills, per-row
actions (Run smoke / Heal & retry / Push to Jira / Open), filters, and a
10-second auto-refresh while any job is in flight.

Design mirrors `test_analytics/templates/test_analytics/panels/jobs.html`
one-for-one so operators can flip between desktop and browser without
re-learning anything. Server-side inference of smoke-mode / heal-mode
means this panel only needs to know which job to hit — the button label
tells the user which mode will run.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from api_client import APIClient, APIError
from panels._visuals import badge, card


# Stage order mirrors STAGE_ORDER in jobs.html — F ▸ M ▸ P ▸ A ▸ E ▸ R ▸ D.
STAGE_ORDER = [
    ("FEATURE",      "F"),
    ("MANUAL_TESTS", "M"),
    ("PLAN",         "P"),
    ("ARTIFACTS",    "A"),
    ("EXECUTE",      "E"),
    ("REPORT",       "R"),
    ("DONE",         "D"),
]

# Which stage panel to jump to when the user clicks "🔎 Open" on a row.
STAGE_TO_SLUG = {
    "FEATURE":              "feature",
    "MANUAL_TESTS":         "manual_tests",
    "PLAN":                 "plan",
    "ARTIFACTS":            "review",
    "EXECUTE":              "execute",
    "REPORT":               "execute",
    "DONE":                 "execute",
    "HUMAN_REVIEW_NEEDED":  "execute",
}


def _fmt_relative(iso: str) -> str:
    """Turn an ISO-8601 timestamp into a compact relative string ('2h ago')."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        diff = (now - dt).total_seconds()
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{int(diff / 60)}m ago"
        if diff < 86400:
            return f"{int(diff / 3600)}h ago"
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso[:10] if len(iso) >= 10 else iso


def _derived_state(job: Dict[str, Any]) -> str:
    """
    Collapse (stage, final_state) into a single display state — same rule
    as jobDerivedState() in jobs.html.
    """
    stage = job.get("stage") or ""
    exec_out = job.get("stage_execute_output") or {}
    final_state = str(exec_out.get("final_state") or "").upper()
    if final_state == "GREEN":
        return "GREEN"
    if stage == "HUMAN_REVIEW_NEEDED" or final_state == "HUMAN_REVIEW_NEEDED":
        return "HUMAN_REVIEW_NEEDED"
    if final_state in ("RED", "STUCK_CONVERGED"):
        return "RED"
    if stage in ("EXECUTE", "ARTIFACTS", "PLAN", "MANUAL_TESTS", "FEATURE"):
        return "IN_PROGRESS"
    if stage in ("DONE", "REPORT"):
        return "GREEN"
    return "IN_PROGRESS"


def _stage_index(stage: str) -> int:
    for i, (code, _) in enumerate(STAGE_ORDER):
        if code == stage:
            return i
    return -1


class StagePillsWidget(QWidget):
    """
    Renders F ▸ M ▸ P ▸ A ▸ E ▸ R ▸ D as coloured circles.

      done      → green (--ok)
      current   → blue (--blue)
      failed    → red (--bad)
      future    → grey (--line)

    Painted via QPainter so the row height stays low and there's no
    per-cell widget overhead when the table has 100+ rows.
    """

    _COLORS = {
        "done":    QColor("#1d7f4f"),
        "current": QColor("#1d4ed8"),
        "failed":  QColor("#b91c1c"),
        "future":  QColor("#e5e7eb"),
    }
    _TEXT_LIGHT = QColor("#ffffff")
    _TEXT_DIM = QColor("#94a3b8")

    def __init__(self, job: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.job = job
        self.setMinimumHeight(28)
        self.setMinimumWidth(220)
        # Cache the per-pill kinds so paintEvent is fast.
        self._kinds = self._compute_kinds()

    def _compute_kinds(self) -> List[str]:
        stage = str(self.job.get("stage") or "")
        exec_out = self.job.get("stage_execute_output") or {}
        final_state = str(exec_out.get("final_state") or "").upper()
        is_red = (
            final_state in ("RED", "STUCK_CONVERGED")
            or stage == "HUMAN_REVIEW_NEEDED"
        )
        cur_idx = _stage_index(stage)
        kinds: List[str] = []
        for i, (code, _) in enumerate(STAGE_ORDER):
            if stage == "DONE":
                kinds.append("done")
            elif cur_idx < 0:
                kinds.append("future")
            elif i < cur_idx:
                kinds.append("done")
            elif i == cur_idx:
                kinds.append("failed" if is_red else "current")
            else:
                kinds.append("future")
        return kinds

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt naming
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        r = self.rect()
        pill_diam = min(22, r.height() - 6)
        gap = 6
        total_w = (pill_diam + gap) * len(STAGE_ORDER) - gap
        x = (r.width() - total_w) // 2
        y = (r.height() - pill_diam) // 2
        font = QFont()
        font.setBold(True)
        font.setPointSize(8)
        p.setFont(font)
        for i, ((_, letter), kind) in enumerate(zip(STAGE_ORDER, self._kinds)):
            cx = x + i * (pill_diam + gap)
            p.setBrush(QBrush(self._COLORS[kind]))
            p.drawEllipse(cx, y, pill_diam, pill_diam)
            p.setPen(self._TEXT_DIM if kind == "future" else self._TEXT_LIGHT)
            p.drawText(cx, y, pill_diam, pill_diam, Qt.AlignCenter, letter)
            p.setPen(Qt.NoPen)
        p.end()


class JobsPanel(QWidget):
    """
    Landing dashboard. Emits `job_opened(job_id, jira_key, target_slug)`
    when the user clicks a row's 🔎 Open button — MainWindow catches the
    signal and deep-links into the correct stage panel.
    """

    job_opened = Signal(str, str, str)

    _COLUMNS = ["Jira", "Feature", "Stage progression", "Iterations", "Last run", "Actions"]

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._jobs: List[Dict[str, Any]] = []
        self._filtered: List[Dict[str, Any]] = []
        self._build_ui()
        # Poll every 10s while any job is IN_PROGRESS.
        self._timer = QTimer(self)
        self._timer.setInterval(10_000)
        self._timer.timeout.connect(self._maybe_poll)
        self._timer.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        # Title row
        title = QLabel("📈 Jobs Dashboard")
        title.setObjectName("h1")
        root.addWidget(title)

        # Summary badges row
        self.summary_row = QHBoxLayout()
        self.summary_row.setSpacing(8)
        self._summary_widgets: Dict[str, QLabel] = {}
        for key, text, kind in [
            ("total",  "Total: 0",       "neutral"),
            ("green",  "🟢 Green: 0",     "smoke"),
            ("red",    "🔴 Red: 0",       "negative"),
            ("review", "👤 Review: 0",    "regression"),
            ("prog",   "⚙ In progress: 0", "neutral"),
        ]:
            lbl = badge(text, kind=kind)
            self._summary_widgets[key] = lbl
            self.summary_row.addWidget(lbl)
        self.summary_row.addStretch(1)
        summary_holder = QWidget()
        summary_holder.setLayout(self.summary_row)
        root.addWidget(summary_holder)

        # Filters row
        filters_row = QHBoxLayout()
        filters_row.setSpacing(6)
        filters_row.addWidget(QLabel("Stage:"))
        self.stage_filter = QComboBox()
        self.stage_filter.addItem("All", "")
        for code, _ in STAGE_ORDER:
            self.stage_filter.addItem(code.replace("_", " ").title(), code)
        self.stage_filter.addItem("Human review", "HUMAN_REVIEW_NEEDED")
        self.stage_filter.currentIndexChanged.connect(self._apply_filters)
        filters_row.addWidget(self.stage_filter)

        filters_row.addSpacing(12)
        filters_row.addWidget(QLabel("State:"))
        self.state_filter = QComboBox()
        for label, val in [("All", ""), ("Green", "GREEN"), ("Red", "RED"),
                            ("Needs review", "HUMAN_REVIEW_NEEDED"),
                            ("In progress", "IN_PROGRESS")]:
            self.state_filter.addItem(label, val)
        self.state_filter.currentIndexChanged.connect(self._apply_filters)
        filters_row.addWidget(self.state_filter)

        filters_row.addSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search feature or Jira key…")
        self.search.textChanged.connect(self._apply_filters)
        filters_row.addWidget(self.search, 1)

        self.refresh_btn = QPushButton("↻ Refresh")
        self.refresh_btn.clicked.connect(self.reload)
        filters_row.addWidget(self.refresh_btn)

        self.autorefresh_toggle = QCheckBox("Auto-refresh (10s)")
        self.autorefresh_toggle.setChecked(True)
        filters_row.addWidget(self.autorefresh_toggle)

        filters_holder = QWidget()
        filters_holder.setLayout(filters_row)
        root.addWidget(filters_holder)

        # Status message (loading / errors)
        self.status_label = QLabel("Loading jobs…")
        self.status_label.setObjectName("hint")
        root.addWidget(self.status_label)

        # Table
        self.table = QTableWidget(0, len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels(self._COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)  # Feature grows
        self.table.setColumnWidth(0, 100)   # Jira
        self.table.setColumnWidth(2, 240)   # Stage progression
        self.table.setColumnWidth(3, 90)    # Iterations
        self.table.setColumnWidth(4, 110)   # Last run
        self.table.setColumnWidth(5, 280)   # Actions
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(56)
        root.addWidget(self.table, 1)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def reload(self) -> None:
        """
        Fetch the jobs list, then enrich each row with detail (stage_execute_output,
        execute_iteration). Ignore errors on individual detail fetches so a
        single bad row doesn't break the whole table.
        """
        try:
            rows = self.api.list_jobs()
        except APIError as exc:
            self.status_label.setText(f"Failed to load jobs: {exc}")
            self._render([])
            return

        enriched: List[Dict[str, Any]] = []
        for row in rows[:200]:  # cap for safety
            merged = dict(row)
            job_id = row.get("job_id") or ""
            if job_id:
                try:
                    detail = self.api.get_job(job_id)
                    if isinstance(detail, dict):
                        merged.update(detail)
                except APIError:
                    # Detail fetch failed — still show the row with list-only info.
                    pass
            enriched.append(merged)

        self._jobs = enriched
        self._render(enriched)

    def _maybe_poll(self) -> None:
        if not self.autorefresh_toggle.isChecked():
            return
        # Only re-poll when there IS an in-flight job (matches the Django
        # dashboard's rule so we don't hammer the API on idle days).
        if any(_derived_state(j) == "IN_PROGRESS" for j in self._jobs):
            self.reload()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _apply_filters(self) -> None:
        self._render(self._jobs)

    def _render(self, jobs: List[Dict[str, Any]]) -> None:
        stage_f = self.stage_filter.currentData() or ""
        state_f = self.state_filter.currentData() or ""
        search_q = (self.search.text() or "").lower().strip()

        filtered = []
        for j in jobs:
            if stage_f and j.get("stage") != stage_f:
                continue
            if state_f and _derived_state(j) != state_f:
                continue
            if search_q:
                hay = " ".join([
                    str(j.get("feature_name") or ""),
                    str(j.get("jira_issue_key") or ""),
                    str(j.get("job_id") or ""),
                ]).lower()
                if search_q not in hay:
                    continue
            filtered.append(j)
        self._filtered = filtered

        self._render_summary(jobs)
        self.status_label.setText(
            "No jobs match the current filters." if not filtered
            else f"{len(filtered)} of {len(jobs)} jobs"
        )
        self.table.setRowCount(0)
        for j in filtered:
            self._append_row(j)

    def _render_summary(self, jobs: List[Dict[str, Any]]) -> None:
        counts = {"total": len(jobs), "green": 0, "red": 0, "review": 0, "prog": 0}
        for j in jobs:
            s = _derived_state(j)
            if s == "GREEN":
                counts["green"] += 1
            elif s == "RED":
                counts["red"] += 1
            elif s == "HUMAN_REVIEW_NEEDED":
                counts["review"] += 1
            elif s == "IN_PROGRESS":
                counts["prog"] += 1
        self._summary_widgets["total"].setText(f"Total: {counts['total']}")
        self._summary_widgets["green"].setText(f"🟢 Green: {counts['green']}")
        self._summary_widgets["red"].setText(f"🔴 Red: {counts['red']}")
        self._summary_widgets["review"].setText(f"👤 Review: {counts['review']}")
        self._summary_widgets["prog"].setText(f"⚙ In progress: {counts['prog']}")

    def _append_row(self, job: Dict[str, Any]) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)

        # Col 0: Jira key
        jira_key = str(job.get("jira_issue_key") or "—")
        jira_item = QTableWidgetItem(jira_key)
        jira_item.setFont(_mono_font())
        self.table.setItem(r, 0, jira_item)

        # Col 1: Feature name + job_id preview underneath
        feature_widget = QWidget()
        fl = QVBoxLayout(feature_widget)
        fl.setContentsMargins(6, 6, 6, 6)
        fl.setSpacing(2)
        feature_name = str(job.get("feature_name") or "(unnamed)")
        name_lbl = QLabel(feature_name)
        name_lbl.setStyleSheet("font-weight: 500;")
        fl.addWidget(name_lbl)
        jid_short = (job.get("job_id") or "")[:8]
        if jid_short:
            id_lbl = QLabel(jid_short)
            id_lbl.setObjectName("hint")
            id_lbl.setStyleSheet("font-family: ui-monospace, monospace; font-size: 10px;")
            fl.addWidget(id_lbl)
        self.table.setCellWidget(r, 1, feature_widget)

        # Col 2: Stage pills
        self.table.setCellWidget(r, 2, StagePillsWidget(job))

        # Col 3: Iterations badge
        derived = _derived_state(job)
        iters = job.get("execute_iteration") or 0
        exec_iters = (job.get("stage_execute_output") or {}).get("iterations") or []
        iter_text = str(iters or len(exec_iters)) if exec_iters else "—"
        iter_kind = {
            "GREEN":  "smoke",
            "RED":    "negative",
            "HUMAN_REVIEW_NEEDED": "regression",
        }.get(derived, "neutral")
        iter_widget = _centered(badge(iter_text, kind=iter_kind))
        self.table.setCellWidget(r, 3, iter_widget)

        # Col 4: Last run (relative)
        last_run = _fmt_relative(job.get("last_modified") or job.get("created_on") or "")
        last_item = QTableWidgetItem(last_run)
        last_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(r, 4, last_item)

        # Col 5: Actions
        self.table.setCellWidget(r, 5, self._action_buttons(job))

    def _action_buttons(self, job: Dict[str, Any]) -> QWidget:
        stage = str(job.get("stage") or "")
        exec_out = job.get("stage_execute_output") or {}
        final_state = str(exec_out.get("final_state") or "").upper()
        jira_key = str(job.get("jira_issue_key") or "")
        job_id = str(job.get("job_id") or "")

        can_rerun = stage in ("EXECUTE", "HUMAN_REVIEW_NEEDED", "REPORT", "DONE")
        can_push = final_state == "GREEN" and bool(jira_key)
        # Context-aware label: smoke run on GREEN+DONE/REPORT, heal otherwise.
        will_be_smoke = (final_state == "GREEN") and (stage in ("REPORT", "DONE"))
        run_label = "▶ Run smoke" if will_be_smoke else "▶ Heal & retry"
        run_tip = (
            "Re-run existing Cucumber test as-is (no LLM). Fails if the UI has changed."
            if will_be_smoke
            else "Kick a full LLM-assisted repair loop."
        )

        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)

        run_btn = QPushButton(run_label)
        run_btn.setToolTip(run_tip)
        run_btn.setEnabled(can_rerun)
        if will_be_smoke:
            run_btn.setObjectName("primaryButton")
        run_btn.clicked.connect(lambda _=None, jid=job_id, smoke=will_be_smoke: self._rerun(jid, smoke))
        row.addWidget(run_btn)

        push_btn = QPushButton("🚀 Push")
        push_btn.setToolTip("Push report to Jira (available on GREEN + Jira-linked jobs)")
        push_btn.setEnabled(can_push)
        if can_push:
            push_btn.setObjectName("primaryButton")
        push_btn.clicked.connect(lambda _=None, jid=job_id: self._push(jid))
        row.addWidget(push_btn)

        open_btn = QPushButton("🔎 Open")
        open_btn.setToolTip("Deep-link into the correct stage panel for this job")
        open_btn.clicked.connect(
            lambda _=None, jid=job_id, jk=jira_key, st=stage: self._open_job(jid, jk, st)
        )
        row.addWidget(open_btn)

        return holder

    # ------------------------------------------------------------------
    # Row actions
    # ------------------------------------------------------------------
    def _rerun(self, job_id: str, will_be_smoke: bool) -> None:
        if not will_be_smoke:
            reply = QMessageBox.question(
                self,
                "Kick heal loop?",
                "Kick a full LLM-assisted repair loop? Current iterations will be "
                "archived to run history.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        try:
            self.api.run_stage(job_id, "execute")
        except APIError as exc:
            QMessageBox.critical(self, "Re-run failed", str(exc))
            return
        self.status_label.setText(
            "Smoke run enqueued." if will_be_smoke else "Heal loop enqueued."
        )
        QTimer.singleShot(500, self.reload)

    def _push(self, job_id: str) -> None:
        try:
            resp = self.api.approve_stage(job_id, "execute")
        except APIError as exc:
            QMessageBox.critical(self, "Push failed", str(exc))
            return
        headline = (resp or {}).get("headline") or ""
        issue = (resp or {}).get("jira_issue_key") or "the ticket"
        self.status_label.setText(f"Report posted to {issue}. {headline[:120]}")
        QTimer.singleShot(500, self.reload)

    def _open_job(self, job_id: str, jira_key: str, stage: str) -> None:
        slug = STAGE_TO_SLUG.get(stage, "execute")
        self.job_opened.emit(job_id, jira_key, slug)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _mono_font() -> QFont:
    f = QFont()
    f.setFamily("ui-monospace, Menlo, Consolas, monospace")
    return f


def _centered(inner: QWidget) -> QWidget:
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addStretch(1)
    lay.addWidget(inner)
    lay.addStretch(1)
    return holder
