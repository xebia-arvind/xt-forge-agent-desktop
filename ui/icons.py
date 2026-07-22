"""Phase 19 — Bootstrap Icons helper.

The font (`bootstrap-icons.woff2`) is registered once at app startup by
`bootstrap.py::_register_icon_font()`. This module maps a short list of
icon names to their Unicode codepoints and renders each into a QIcon
via QPainter — theme-color aware, no SVG plugin needed.

Only the icons we actually use are baked in. Add new entries to
`_GLYPHS` as they're needed; unknown names fall back to `question-circle`.

Codepoints copied verbatim from bootstrap-icons.css @ 1.11.3.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


# name → single-char Unicode codepoint in the Bootstrap Icons font's PUA.
_GLYPHS = {
    "graph-up-arrow":     "",  # Jobs
    "folder2":            "",  # Worklist
    "puzzle":             "",  # Feature
    "journal-text":       "",  # Manual Tests
    "diagram-3":          "",  # Plan
    "search":             "",  # Review
    "play-fill":          "",  # Execute
    "file-earmark-code":  "",  # .feature files
    "braces":             "",  # step-defs
    "box":                "",  # page-objects
    "question-circle":    "",  # fallback
}

# Family name Qt exposes after QFontDatabase.addApplicationFont on the woff2.
_FAMILY = "bootstrap-icons"


def bi_glyph(name: str) -> str:
    """Return the Unicode char for a Bootstrap Icons name, or the
    fallback question-circle char if the name isn't in the bake-in list."""
    return _GLYPHS.get(name, _GLYPHS["question-circle"])


def bi_icon(name: str, color: Optional[str] = None, size: int = 20) -> QIcon:
    """Render a Bootstrap Icons glyph into a QIcon at the given pixel
    size + color. `color` is a hex string like '#dbeafe'; when None we
    use the default text color (near-black)."""
    px = QPixmap(size, size)
    px.fill(Qt.transparent)

    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    font = QFont(_FAMILY)
    # Font's glyphs are designed on a 16px em; pointSize keeps them
    # crisp at any pixel size when we then paint into an NxN pixmap.
    font.setPixelSize(max(8, size - 2))
    painter.setFont(font)
    painter.setPen(QColor(color or "#1a0a16"))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, bi_glyph(name))
    painter.end()

    return QIcon(px)
