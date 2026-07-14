"""
Manual Test Author output — one card per test with GIVEN/WHEN/THEN blocks.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from panels._stage_base import StagePanelBase
from panels._visuals import badge, bullet_list, card, scenario_type_badge


class ManualTestsPanel(StagePanelBase):
    TITLE = "📝 Manual Tests"
    STAGE_KEY = "manual-tests"
    OUTPUT_FIELD = "stage_manual_tests_output"
    AGENT_KEY = "manual_test_author"

    def render_output(self, payload: Any) -> QWidget:
        if not isinstance(payload, dict):
            return super().render_output(payload)

        tests = payload.get("manual_tests") or []
        notes = payload.get("notes") or []

        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        # Summary strip
        summary = QLabel(f"{len(tests)} manual test case(s) generated.")
        summary.setObjectName("hint")
        outer.addWidget(summary)

        if not tests:
            empty = card("No tests")
            empty.layout().addWidget(QLabel("The agent returned no manual tests."))
            outer.addWidget(empty)
            outer.addStretch(1)
            return wrapper

        for t in tests:
            if not isinstance(t, dict):
                continue
            outer.addWidget(_manual_test_card(t))

        if notes:
            n = card("Notes")
            n.layout().addWidget(bullet_list([str(x) for x in notes], marker="—"))
            outer.addWidget(n)

        outer.addStretch(1)
        return wrapper


def _manual_test_card(test: dict) -> QWidget:
    mt_id = str(test.get("id") or "MT-?")
    title = str(test.get("title") or "(untitled)")
    kind = str(test.get("type") or "SMOKE")

    c = card()
    layout = c.layout()

    # Header: id + title + type badge
    hdr = QHBoxLayout()
    hdr.setContentsMargins(0, 0, 0, 0)
    hdr.setSpacing(10)
    id_lbl = QLabel(mt_id)
    id_lbl.setObjectName("chip")
    hdr.addWidget(id_lbl)
    title_lbl = QLabel(title)
    title_lbl.setObjectName("mtTitle")
    title_lbl.setWordWrap(True)
    hdr.addWidget(title_lbl, 1)
    hdr.addWidget(scenario_type_badge(kind))
    hdr_w = QWidget()
    hdr_w.setLayout(hdr)
    layout.addWidget(hdr_w)

    for label, key, marker in (
        ("Given", "given", "○"),
        ("When", "when", "→"),
        ("Then", "then", "✓"),
    ):
        section = QVBoxLayout()
        section.setContentsMargins(0, 4, 0, 0)
        section.setSpacing(2)
        head = QLabel(label)
        head.setObjectName("gwtHead")
        section.addWidget(head)
        section.addWidget(bullet_list([str(x) for x in (test.get(key) or [])], marker=marker))
        w = QWidget()
        w.setLayout(section)
        layout.addWidget(w)

    return c
