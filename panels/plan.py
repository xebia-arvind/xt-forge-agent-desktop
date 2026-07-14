"""
Plan Architect output — one card per scenario with steps table + assertions.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from panels._stage_base import StagePanelBase
from panels._visuals import bullet_list, card, scenario_type_badge


class PlanPanel(StagePanelBase):
    TITLE = "🗺️ Plan"
    STAGE_KEY = "plan"
    OUTPUT_FIELD = "stage_plan_output"
    AGENT_KEY = "plan_architect"

    def render_output(self, payload: Any) -> QWidget:
        if not isinstance(payload, dict):
            return super().render_output(payload)

        scenarios = payload.get("scenarios") or []
        notes = payload.get("notes") or []

        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        # Summary
        summary = QLabel(f"{len(scenarios)} scenario(s) planned.")
        summary.setObjectName("hint")
        outer.addWidget(summary)

        if not scenarios:
            empty = card("No scenarios")
            empty.layout().addWidget(
                QLabel("Plan agent produced no scenarios — check crawl / base URL and re-run.")
            )
            outer.addWidget(empty)
            outer.addStretch(1)
            return wrapper

        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            outer.addWidget(_scenario_card(sc))

        if notes:
            n = card("Notes")
            n.layout().addWidget(bullet_list([str(x) for x in notes], marker="—"))
            outer.addWidget(n)

        outer.addStretch(1)
        return wrapper


def _scenario_card(sc: dict) -> QWidget:
    sc_id = str(sc.get("id") or "SC-?")
    title = str(sc.get("title") or "(untitled)")
    kind = str(sc.get("type") or "SMOKE")
    preconditions = sc.get("preconditions") or []
    steps = sc.get("steps") or []
    assertions = sc.get("assertions") or []

    c = card()
    layout = c.layout()

    # Header row
    hdr = QHBoxLayout()
    hdr.setContentsMargins(0, 0, 0, 0)
    hdr.setSpacing(10)
    id_lbl = QLabel(sc_id)
    id_lbl.setObjectName("chip")
    hdr.addWidget(id_lbl)
    title_lbl = QLabel(title)
    title_lbl.setObjectName("mtTitle")
    title_lbl.setWordWrap(True)
    hdr.addWidget(title_lbl, 1)
    hdr.addWidget(scenario_type_badge(kind))
    hw = QWidget()
    hw.setLayout(hdr)
    layout.addWidget(hw)

    # Preconditions
    if preconditions:
        pre_head = QLabel("Preconditions")
        pre_head.setObjectName("gwtHead")
        layout.addWidget(pre_head)
        layout.addWidget(bullet_list([str(x) for x in preconditions], marker="○"))

    # Steps table (Action / Selector / Intent / Value)
    if steps:
        head = QLabel("Steps")
        head.setObjectName("gwtHead")
        layout.addWidget(head)
        layout.addWidget(_steps_table(steps))

    # Assertions
    if assertions:
        head2 = QLabel("Assertions")
        head2.setObjectName("gwtHead")
        layout.addWidget(head2)
        layout.addWidget(bullet_list([str(x) for x in assertions], marker="✓"))

    return c


def _steps_table(steps) -> QTableWidget:
    table = QTableWidget(0, 4)
    table.setObjectName("planStepsTable")
    table.setHorizontalHeaderLabels(["Action", "Selector", "Intent key", "Value"])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)

    for step in steps:
        if not isinstance(step, dict):
            continue
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(str(step.get("action") or "")))
        sel_item = QTableWidgetItem(str(step.get("selector") or ""))
        if not str(step.get("selector") or "").strip():
            # Flag empty selectors (placeholder plan) so operators notice.
            sel_item.setText("(missing — patch me)")
            sel_item.setForeground(Qt.red)
        table.setItem(row, 1, sel_item)
        table.setItem(row, 2, QTableWidgetItem(str(step.get("intent_key") or "")))
        table.setItem(row, 3, QTableWidgetItem(str(step.get("value") or "")))

    table.resizeRowsToContents()
    # Give the table a reasonable min height so short tables aren't collapsed.
    total_height = table.horizontalHeader().height() + sum(
        table.rowHeight(i) for i in range(table.rowCount())
    ) + 8
    table.setMinimumHeight(min(360, max(80, total_height)))
    return table
