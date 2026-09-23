"""First-launch bootstrap.

Registers the Bootstrap Icons font so the sidebar and inline glyphs
resolve. That's it.

Previously this module also downloaded Playwright's Chromium browser on
first launch, but the desktop app is a thin PySide6 client — test
execution runs on the Django backend and is streamed back as an SSE
log, so Chromium on the operator's machine is unused. On Windows the
old download call also caused a recursive-popup crash (a PyInstaller
`sys.executable` re-launches the entire app rather than invoking
Python), so the whole Playwright branch is removed.

Called from `main.py` right after `QApplication` is created and before
`MainWindow` is constructed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QWidget


def _register_icon_font() -> None:
    """Register Bootstrap Icons so `QFont('bootstrap-icons')` resolves
    and `ui/icons.py::bi_icon()` renders. Idempotent — Qt de-dupes
    across repeated calls. Resolves the woff2 path whether we're
    running from source (desktop-app/ui/fonts/) or from a PyInstaller
    bundle (sys._MEIPASS/ui/fonts/)."""
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:
        return
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else Path(__file__).resolve().parent
    font_path = base / "ui" / "fonts" / "bootstrap-icons.woff2"
    if font_path.exists():
        try:
            QFontDatabase.addApplicationFont(str(font_path))
        except Exception:
            pass


def ensure_dependencies(parent: Optional[QWidget] = None) -> bool:
    """Idempotent: safe to call on every launch. Registers the icon
    font and returns True. The `parent` argument is retained for
    call-site compatibility even though nothing currently uses it."""
    _register_icon_font()
    return True
