"""Phase 20 — shared two-column shell for the Login + Setup screens.

Left column: brand-tinted gradient background + hero image scaled to fill
with `KeepAspectRatioByExpanding` on every resize (crops the image on
the shorter axis rather than distorting it).

Right column: white background, XT-Forge wordmark near the top-center,
then the caller-supplied form widget below.

Images live under `desktop-app/ui/images/`:
    login-hero.png       — AI-mind hero for the left column.
    xt-forge-logo.png    — wordmark shown above the form.

Missing images degrade gracefully — the panel still renders (empty
QLabel where the image would go). We don't want a first-launch crash
if a build somehow shipped without an asset.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _asset_path(name: str) -> Path:
    """Resolve an asset under ui/images/ whether we're running from source
    or from a PyInstaller bundle. Mirrors bootstrap.py's _MEIPASS handling."""
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else Path(__file__).resolve().parent.parent
    return base / "ui" / "images" / name


class HeroImageLabel(QLabel):
    """QLabel that keeps a source QPixmap and rescales it to fill the label
    with KeepAspectRatioByExpanding on every resizeEvent. Falls back to a
    blank label when the source pixmap is null (missing asset)."""

    def __init__(self, source_path: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("loginHero")
        self.setAlignment(Qt.AlignCenter)
        self.setScaledContents(False)
        self.setMinimumSize(QSize(320, 320))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._source: QPixmap = QPixmap(str(source_path)) if source_path.exists() else QPixmap()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._source.isNull():
            return
        scaled = self._source.scaled(
            self.size(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.setPixmap(scaled)


def build_two_column(form_widget: QWidget) -> QWidget:
    """Wrap `form_widget` in the two-column login/setup shell.

    Left column (~45%): gradient background + hero image (fills, crops on
    resize). Right column (~55%): white background, wordmark centered
    near the top, then the caller-supplied form under it.

    Returns the top-level container QWidget — caller should install it
    as the panel's layout target (e.g. `outer.addWidget(build_two_column(form))`
    if wrapping, or use it as `panel.setLayout(...)`-equivalent by adding
    a single layout that hosts this widget).
    """
    container = QWidget()
    root = QHBoxLayout(container)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # ── Left column: gradient + hero image ────────────────────────────
    left = QWidget()
    left.setObjectName("loginLeft")
    left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    left_layout = QVBoxLayout(left)
    left_layout.setContentsMargins(0, 0, 0, 0)
    left_layout.setSpacing(0)
    hero = HeroImageLabel(_asset_path("login-hero.png"), left)
    left_layout.addWidget(hero, 1)
    root.addWidget(left, 45)

    # ── Right column: logo + caller's form ────────────────────────────
    right = QWidget()
    right.setObjectName("loginRight")
    right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    right_layout = QVBoxLayout(right)
    # Symmetric horizontal padding + generous top so the logo doesn't
    # crowd the top edge of the window.
    right_layout.setContentsMargins(56, 48, 56, 48)
    right_layout.setSpacing(20)

    right_layout.addStretch(1)

    logo_path = _asset_path("xt-forge-logo.png")
    logo_label = QLabel()
    logo_label.setObjectName("loginLogo")
    logo_label.setAlignment(Qt.AlignCenter)
    if logo_path.exists():
        pm = QPixmap(str(logo_path))
        # 140px tall keeps the wordmark readable without eating into the
        # form area. Preserves aspect via KeepAspectRatio.
        pm = pm.scaledToHeight(140, Qt.SmoothTransformation)
        logo_label.setPixmap(pm)
    right_layout.addWidget(logo_label)

    right_layout.addWidget(form_widget)

    right_layout.addStretch(2)

    root.addWidget(right, 55)

    return container
