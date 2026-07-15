"""
Artifacts review — one tab per generated file, monospace content view.

The Artifacts endpoint returns a list of files. The old code dumped them all
into a single text area; here each file gets its own tab (name = basename)
with the language-appropriate content shown in a JetBrains-Mono view. A small
sidebar on the left lists the file paths for context, matching how VS Code
displays generated code.
"""
from __future__ import annotations

import os
from typing import Any, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from api_client import APIError
from panels._stage_base import StagePanelBase
from panels._visuals import badge, bullet_list, card
from workers.agent_run_thread import AgentRunThread


class ReviewPanel(StagePanelBase):
    TITLE = "🔍 Review Artifacts"
    STAGE_KEY = "artifacts"
    OUTPUT_FIELD = ""   # artifacts live on job.artifacts, not on a stage_*_output field
    AGENT_KEY = "artifact_generator"

    def _build_ui(self) -> None:
        super()._build_ui()
        # Mirror the browser's "🔄 Regenerate artifacts" button. POSTs to the
        # same /stage/artifacts/run/ endpoint the Django panel uses; visible
        # whenever the job is at (or past) ARTIFACTS so operators can retry a
        # bad batch without editing anything.
        self.regenerate_btn = QPushButton("🔄 Regenerate artifacts")
        self.regenerate_btn.setObjectName("secondary")
        self.regenerate_btn.setVisible(False)
        self.regenerate_btn.clicked.connect(self._regenerate)
        # Insert just after Approve so the action row reads:
        # [ Run agent | Approve & advance | 🔄 Regenerate | { } Raw JSON ]
        idx = self.btn_row.indexOf(self.approve_btn)
        self.btn_row.insertWidget(idx + 1, self.regenerate_btn)

    # We override hydration + render so the run/get shapes both work.
    def _try_hydrate(self) -> None:
        if not self.job_id:
            return
        try:
            job = self.api.get_job(self.job_id)
        except APIError:
            return
        artifacts = job.get("artifacts") or []
        stage = str(job.get("stage") or "").upper()
        # Always render the payload — even when artifacts is empty — so the
        # header + Regenerate button surface. The empty-state card inside
        # render_output already handles "no artifacts" messaging.
        self._show({
            "artifacts": artifacts,
            "stage_history": job.get("stage_history") or [],
        })
        self._paint_action_buttons(stage, len(artifacts))

    def _paint_action_buttons(self, stage: str, artifact_count: int) -> None:
        # Show Regenerate whenever the job has reached (or is at) ARTIFACTS.
        # Empty-artifact recovery on ARTIFACTS also gets the button so
        # operators can re-kick after a failed LLM pass.
        past_artifacts = stage in ("ARTIFACTS", "EXECUTE", "REPORT", "DONE",
                                   "HUMAN_REVIEW_NEEDED")
        self.regenerate_btn.setVisible(past_artifacts)
        # Deep-linked jobs past ARTIFACTS should NOT re-approve from here.
        # For ARTIFACTS with content, _show already flipped Approve on.
        if stage != "ARTIFACTS":
            self.approve_btn.setEnabled(False)
        elif artifact_count == 0:
            self.approve_btn.setEnabled(False)

    def _regenerate(self) -> None:
        if not self.job_id:
            return
        ok = QMessageBox.question(
            self,
            "Regenerate artifacts",
            "This re-runs the Artifact generator against the current plan. "
            "Existing artifacts will be replaced. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return
        # Phase 12.4 — reuse the base class async runner. Extra visual cue
        # on the Regenerate button; success/failure land in the same
        # _on_agent_* slots as the primary Run agent path.
        if self._agent_thread is not None and self._agent_thread.isRunning():
            return
        self.regenerate_btn.setEnabled(False)
        self.regenerate_btn.setText("Regenerating…")
        self._set_running(True)
        self._agent_thread = AgentRunThread(self.api, self.job_id, self.STAGE_KEY, parent=self)
        self._agent_thread.succeeded.connect(self._on_regenerate_finished)
        self._agent_thread.failed.connect(self._on_agent_failed)
        self._agent_thread.finished.connect(self._on_regenerate_thread_finished)
        self._agent_thread.start()

    def _on_regenerate_finished(self, _result: Any) -> None:
        # /run/ response omits `artifacts` — re-fetch job detail.
        self._try_hydrate()

    def _on_regenerate_thread_finished(self) -> None:
        self._set_running(False)
        self.regenerate_btn.setEnabled(True)
        self.regenerate_btn.setText("🔄 Regenerate artifacts")

    def _run(self) -> None:
        # The base class hands the /run/ response body ({stage,
        # validation_summary, notes, diagnostic}) to render_output — which
        # has no `artifacts` field, so the panel would draw "No artifacts"
        # even after a successful generation. Override to re-hydrate from
        # the job detail after the agent finishes.
        if not self.job_id:
            QMessageBox.warning(self, "No job", "Start a pipeline from Worklist first.")
            return
        if self._agent_thread is not None and self._agent_thread.isRunning():
            return
        self._set_running(True)
        self._agent_thread = AgentRunThread(self.api, self.job_id, self.STAGE_KEY, parent=self)
        self._agent_thread.succeeded.connect(lambda _r: self._try_hydrate())
        self._agent_thread.failed.connect(self._on_agent_failed)
        self._agent_thread.finished.connect(lambda: self._set_running(False))
        self._agent_thread.start()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Re-hydrate on every panel show so background finishes (or browser-
        # side re-runs while the desktop was elsewhere) don't leave stale
        # placeholder text on screen. One GET /jobs/<id>/ per show; cheap.
        super().showEvent(event)
        if self.job_id:
            self._try_hydrate()

    def render_output(self, payload: Any) -> QWidget:
        artifacts = _extract_artifacts(payload)
        norm_by_path = _extract_normalizer_report(payload)
        verify_by_path = _extract_selector_verify_report(payload)

        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        # Header row: summary + re-validated timestamp.
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        summary = QLabel(f"{len(artifacts)} artifact file(s) generated.")
        summary.setObjectName("hint")
        header_row.addWidget(summary)
        header_row.addStretch(1)
        stamp = QLabel(f"re-validated at {_now_hhmm()}")
        stamp.setObjectName("hint")
        header_row.addWidget(stamp)
        hr = QWidget()
        hr.setLayout(header_row)
        outer.addWidget(hr)

        if not artifacts:
            empty = card("No artifacts")
            empty.layout().addWidget(QLabel("The agent produced no artifacts. Approve Plan first, or re-run."))
            outer.addWidget(empty)
            outer.addStretch(1)
            return wrapper

        # Summary strip — one badge per artifact type + valid/invalid counts.
        counts: dict = {}
        valid = invalid = 0
        for a in artifacts:
            t = str(a.get("artifact_type") or "OTHER")
            counts[t] = counts.get(t, 0) + 1
            if str(a.get("validation_status") or "").upper() == "INVALID":
                invalid += 1
            else:
                valid += 1
        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(6)
        for t, n in sorted(counts.items()):
            summary_row.addWidget(_type_badge(t, n))
        if valid:
            summary_row.addWidget(badge(f"{valid} valid", kind="smoke"))
        if invalid:
            summary_row.addWidget(badge(f"{invalid} invalid", kind="negative"))
        summary_row.addStretch(1)
        srow = QWidget()
        srow.setLayout(summary_row)
        outer.addWidget(srow)

        # Splitter: file list on the left, content + validation panel on the right
        splitter = QSplitter(Qt.Horizontal)

        file_list = QListWidget()
        file_list.setObjectName("artifactList")
        file_list.setFixedWidth(300)

        stack = QStackedWidget()

        for artifact in artifacts:
            path = str(artifact.get("relative_path") or artifact.get("path") or "unknown")
            content = str(
                artifact.get("content_final")
                or artifact.get("content_draft")
                or artifact.get("content")
                or ""
            )
            atype = str(artifact.get("artifact_type") or "").upper()
            status_ = str(artifact.get("validation_status") or "").upper() or "VALID"
            errors = artifact.get("validation_errors") or []
            warnings = artifact.get("warnings") or []

            marker = "✓" if status_ != "INVALID" else "✕"
            item = QListWidgetItem(f"{marker} {_type_icon(atype)}  {os.path.basename(path)}")
            item.setToolTip(path)
            file_list.addItem(item)

            viewer = _file_viewer(
                path, content, status_, errors, warnings,
                normalizer_entry=norm_by_path.get(path),
                verify_entry=verify_by_path.get(path),
            )
            stack.addWidget(viewer)

        file_list.currentRowChanged.connect(stack.setCurrentIndex)
        file_list.setCurrentRow(0)

        splitter.addWidget(file_list)
        splitter.addWidget(stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        return wrapper


# ------------------------------------------------------------------
def _extract_artifacts(payload: Any) -> List[dict]:
    if isinstance(payload, dict):
        if isinstance(payload.get("artifacts"), list):
            return payload["artifacts"]
        # Some paths return the raw stage_execute_output shape — grab any list
        # of file-shaped dicts.
        for k in ("files", "results"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
    if isinstance(payload, list):
        return payload
    return []


def _type_badge(type_key: str, count: int) -> QLabel:
    mapping = {
        "PAGE_OBJECT": ("page objects", "smoke"),
        "SPEC": ("specs", "smoke"),
        "FEATURE": ("features", "regression"),
        "STEP_DEFINITIONS": ("step defs", "negative"),
    }
    label, kind = mapping.get(type_key.upper(), (type_key.lower(), "neutral"))
    return badge(f"{count} {label}", kind=kind)


def _type_icon(type_key: str) -> str:
    return {
        "PAGE_OBJECT": "📦",
        "SPEC": "🧪",
        "FEATURE": "🥒",
        "STEP_DEFINITIONS": "🔗",
    }.get(type_key.upper(), "📄")


def _file_viewer(path: str, content: str, status_: str = "VALID",
                 errors: List = None, warnings: List = None,
                 normalizer_entry: dict = None,
                 verify_entry: dict = None) -> QWidget:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    # Header row: file path + status badge
    header_row = QHBoxLayout()
    header_row.setContentsMargins(0, 0, 0, 0)
    header = QLabel(path)
    header.setObjectName("filePath")
    header.setTextInteractionFlags(Qt.TextSelectableByMouse)
    header_row.addWidget(header, 1)
    kind = "negative" if status_ == "INVALID" else "smoke"
    header_row.addWidget(badge(status_, kind=kind))
    hr = QWidget()
    hr.setLayout(header_row)
    layout.addWidget(hr)

    # Validation errors / warnings — shown above the code so operators see
    # them without scrolling. Each entry is rendered as `[rule] message` so
    # the rule name is obvious.
    for entry in (errors or []):
        layout.addWidget(_validation_row(entry, severity="error"))
    for entry in (warnings or []):
        layout.addWidget(_validation_row(entry, severity="warning"))

    # Auto-fixes applied — Phase 2 AST normalizer sidecar output. Lists each
    # transformation that ran (e.g. "decorator-to-registration: moved 5 …").
    normalizer_widget = _normalizer_block(normalizer_entry)
    if normalizer_widget is not None:
        layout.addWidget(normalizer_widget)

    # Live-DOM selector probe — one row per missed locator, or a green
    # summary badge if every locator resolved.
    verify_widget = _selector_verify_block(verify_entry)
    if verify_widget is not None:
        layout.addWidget(verify_widget)

    editor = QPlainTextEdit()
    editor.setReadOnly(True)
    editor.setObjectName("codeViewer")
    editor.setLineWrapMode(QPlainTextEdit.NoWrap)
    mono = QFont("JetBrains Mono, Menlo, Consolas, monospace", 11)
    editor.setFont(mono)
    editor.setPlainText(content or "(empty file)")
    layout.addWidget(editor, 1)

    return wrapper


def _validation_row(entry, severity: str = "error") -> QWidget:
    """
    Render one `{rule, message}` (new shape) or plain string (legacy) as a
    single-line row: `[rule] message`. Color = red for error, amber for warning.
    """
    if isinstance(entry, dict):
        rule = str(entry.get("rule") or "").strip()
        msg = str(entry.get("message") or "")
    else:
        rule = ""
        msg = str(entry)
    text = f"[{rule}] {msg}" if rule else msg
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lbl.setObjectName("validationError" if severity == "error" else "validationWarning")
    return lbl


def _now_hhmm() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")


def _extract_normalizer_report(payload: Any) -> dict:
    """
    Pull `{path: normalizer_entry}` out of the payload's `stage_history`.
    The most recent history entry with a `diagnostic.normalizer_report`
    wins (Phase 2 writes exactly one report per Artifact stage run).
    Returns `{}` if no report is present, so callers can safely `.get(path)`.
    """
    if not isinstance(payload, dict):
        return {}
    history = payload.get("stage_history")
    if not isinstance(history, list):
        return {}
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        diag = entry.get("diagnostic")
        if not isinstance(diag, dict):
            continue
        report = diag.get("normalizer_report")
        if isinstance(report, list) and report:
            return {
                str(r.get("path") or ""): r
                for r in report
                if isinstance(r, dict) and r.get("path")
            }
    return {}


def _extract_selector_verify_report(payload: Any) -> dict:
    """
    Pull `{path: per_file_entry}` out of the payload's stage_history. The
    Selector Verifier writes `diagnostic.selector_verify_report.per_file`
    keyed by relative_path.
    """
    if not isinstance(payload, dict):
        return {}
    history = payload.get("stage_history")
    if not isinstance(history, list):
        return {}
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        diag = entry.get("diagnostic")
        if not isinstance(diag, dict):
            continue
        report = diag.get("selector_verify_report")
        if not isinstance(report, dict):
            continue
        per_file = report.get("per_file")
        if isinstance(per_file, list) and per_file:
            return {
                str(pf.get("relative_path") or ""): pf
                for pf in per_file
                if isinstance(pf, dict) and pf.get("relative_path")
            }
    return {}


def _selector_verify_block(entry: dict) -> QWidget:
    """
    Render the selector-verifier per-file result. Returns None if this
    artifact wasn't probed (e.g. it wasn't a page-object).
    """
    if not entry:
        return None
    hit  = entry.get("hit_count") or 0
    miss = entry.get("miss_count") or 0
    if hit == 0 and miss == 0:
        return None

    container = QWidget()
    v = QVBoxLayout(container)
    v.setContentsMargins(4, 4, 4, 4)
    v.setSpacing(2)

    head_row = QHBoxLayout()
    head_row.setContentsMargins(0, 0, 0, 0)
    head_row.setSpacing(6)
    title = QLabel("Live-DOM selector probe")
    title.setObjectName("hint")
    head_row.addWidget(title)
    kind = "smoke" if miss == 0 else "negative"
    head_row.addWidget(badge(f"{hit}/{hit + miss} resolved", kind=kind))
    url = str(entry.get("seed_url") or "")
    if url:
        seed_lbl = QLabel(url)
        seed_lbl.setObjectName("hint")
        seed_lbl.setStyleSheet("opacity: 0.7;")
        head_row.addWidget(seed_lbl)
    head_row.addStretch(1)
    hr = QWidget()
    hr.setLayout(head_row)
    v.addWidget(hr)

    for m in entry.get("misses") or []:
        line = QLabel(
            f"  ✕ [{str(m.get('kind') or '')}] "
            f"{str(m.get('selector') or '')}  "
            f"(count={m.get('count') if m.get('count') is not None else '?'})"
        )
        line.setWordWrap(True)
        line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        line.setObjectName("validationError")
        v.addWidget(line)

    return container


def _normalizer_block(entry: dict) -> QWidget:
    """
    Render one artifact's normalizer entry as a small 'Auto-fixes applied'
    panel. Returns None when there's nothing to show.
    """
    if not entry:
        return None
    txs = entry.get("transformations") or []
    sidecar = str(entry.get("sidecar") or "").strip()
    if not txs and sidecar != "error":
        return None

    container = QWidget()
    v = QVBoxLayout(container)
    v.setContentsMargins(4, 4, 4, 4)
    v.setSpacing(2)

    head_row = QHBoxLayout()
    head_row.setContentsMargins(0, 0, 0, 0)
    head_row.setSpacing(6)
    title = QLabel("Auto-fixes applied")
    title.setObjectName("hint")
    head_row.addWidget(title)
    kind = "smoke" if sidecar == "ast" else ("negative" if sidecar == "error" else "neutral")
    if sidecar:
        head_row.addWidget(badge(sidecar, kind=kind))
    head_row.addStretch(1)
    hr = QWidget()
    hr.setLayout(head_row)
    v.addWidget(hr)

    for t in txs:
        name = str(t.get("name") or "").strip() or "transform"
        detail = str(t.get("detail") or "").strip()
        line = QLabel(f"  • [{name}] {detail}")
        line.setWordWrap(True)
        line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        line.setObjectName("hint")
        v.addWidget(line)

    return container
