"""
Reusable visual building blocks for the pipeline panels.

Keeps each panel short by centralising card/badge/bullet-list constructions.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def card(title: str = "", parent: Optional[QWidget] = None) -> QFrame:
    """A white-background rounded card with an optional bold title row."""
    frame = QFrame(parent)
    frame.setObjectName("card")
    frame.setFrameShape(QFrame.NoFrame)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    if title:
        lbl = QLabel(title)
        lbl.setObjectName("cardTitle")
        layout.addWidget(lbl)
    return frame


def badge(text: str, kind: str = "neutral") -> QLabel:
    """
    `kind` ∈ {smoke, negative, regression, neutral, ok, warn, err} — maps to
    the object-name styling in style.qss.
    """
    lbl = QLabel(text)
    lbl.setObjectName(f"badge-{kind}")
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
    return lbl


def bullet_list(items: Iterable[str], marker: str = "•") -> QWidget:
    """Vertical stack of `<marker> <text>` lines. Wraps long text."""
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    any_ = False
    for text in items or []:
        any_ = True
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        m = QLabel(marker)
        m.setObjectName("bulletMarker")
        m.setAlignment(Qt.AlignTop)
        m.setFixedWidth(14)
        row.addWidget(m)
        t = QLabel(str(text))
        t.setWordWrap(True)
        t.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(t, 1)
        holder = QWidget()
        holder.setLayout(row)
        layout.addWidget(holder)
    if not any_:
        lbl = QLabel("(none)")
        lbl.setObjectName("hint")
        layout.addWidget(lbl)
    return wrapper


def kv_row(key: str, value: str) -> QWidget:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    k = QLabel(key)
    k.setObjectName("kvKey")
    k.setFixedWidth(120)
    row.addWidget(k)
    v = QLabel(value)
    v.setWordWrap(True)
    v.setTextInteractionFlags(Qt.TextSelectableByMouse)
    row.addWidget(v, 1)
    holder = QWidget()
    holder.setLayout(row)
    return holder


def scenario_type_badge(scenario_type: str) -> QLabel:
    t = (scenario_type or "").upper()
    kind = {"SMOKE": "smoke", "NEGATIVE": "negative", "REGRESSION": "regression"}.get(t, "neutral")
    return badge(t or "—", kind=kind)


def stage_header_row(icon: str, title: str, badges: Optional[List[QLabel]] = None) -> QWidget:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)
    ic = QLabel(icon)
    ic.setObjectName("stageIcon")
    row.addWidget(ic)
    t = QLabel(title)
    t.setObjectName("stageEntryTitle")
    t.setWordWrap(True)
    row.addWidget(t, 1)
    for b in badges or []:
        row.addWidget(b)
    w = QWidget()
    w.setLayout(row)
    return w
