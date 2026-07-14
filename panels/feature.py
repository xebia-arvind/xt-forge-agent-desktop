"""Feature Author output — title + description + acceptance criteria + seed URLs."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from panels._stage_base import StagePanelBase
from panels._visuals import bullet_list, card, kv_row


class FeaturePanel(StagePanelBase):
    TITLE = "🧬 Feature Author"
    STAGE_KEY = "feature"
    OUTPUT_FIELD = "stage_feature_output"
    AGENT_KEY = "feature_author"

    def render_output(self, payload: Any) -> QWidget:
        if not isinstance(payload, dict):
            return super().render_output(payload)

        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        title = str(payload.get("title") or "(untitled feature)")
        description = str(payload.get("description") or "")
        criteria = payload.get("acceptance_criteria") or []
        seed_urls = payload.get("seed_urls") or []
        preconditions = payload.get("preconditions") or {}
        notes = payload.get("notes") or []

        # Header card — title + description
        head = card()
        h_layout = head.layout()
        t = QLabel(title)
        t.setObjectName("featureTitle")
        t.setWordWrap(True)
        h_layout.addWidget(t)
        if description:
            d = QLabel(description)
            d.setWordWrap(True)
            d.setObjectName("featureDescription")
            d.setTextInteractionFlags(Qt.TextSelectableByMouse)
            h_layout.addWidget(d)
        outer.addWidget(head)

        # Acceptance criteria card
        ac = card("Acceptance criteria")
        ac.layout().addWidget(bullet_list([str(x) for x in criteria], marker="✓"))
        outer.addWidget(ac)

        # Seed URLs card
        urls = card("Seed URLs")
        urls.layout().addWidget(bullet_list([str(x) for x in seed_urls], marker="›"))
        outer.addWidget(urls)

        # Preconditions card (only if non-empty). Shown read-only here —
        # editing happens in the Django Feature Review panel for v1.
        if preconditions:
            pre = card("Preconditions (edit in Django panel)")
            lines = []
            http = preconditions.get("http_basic") if isinstance(preconditions, dict) else None
            if isinstance(http, dict):
                user = str(http.get("username") or "")
                pwd = str(http.get("password") or "")
                if user or pwd:
                    lines.append(f"HTTP Basic Auth: {user} / {'•' * len(pwd)}")
            for k, v in (preconditions.items() if isinstance(preconditions, dict) else []):
                if k == "http_basic":
                    continue
                lines.append(f"{k}: {v}")
            pre.layout().addWidget(bullet_list(lines, marker="•"))
            outer.addWidget(pre)

        # Notes card (only if non-empty)
        if notes:
            n = card("Notes")
            n.layout().addWidget(bullet_list([str(x) for x in notes], marker="—"))
            outer.addWidget(n)

        outer.addStretch(1)
        return wrapper
