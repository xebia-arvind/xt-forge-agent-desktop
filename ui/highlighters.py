"""Phase 21 — VS-Code-Dark+ style syntax highlighters for the desktop
Review Artifacts panel.

Two highlighters:
    * TypeScriptHighlighter  — .ts files (step-defs + page objects).
    * GherkinHighlighter      — .feature files.

Both subclass QSyntaxHighlighter and paint against a dark background
(#1e1e1e) using the VS Code Dark+ colour scheme:

    keyword    #569cd6
    control    #c586c0
    type/class #4ec9b0
    function   #dcdcaa
    string     #ce9178
    comment    #6a9955
    number     #b5cea8
    default fg #d4d4d4

Attach via `highlighter_for(path, document)` — returns the right subclass
based on filename extension, or None when the file has no supported
grammar (falls through to the plain text render).
"""
from __future__ import annotations

import re
from typing import List, Tuple, Optional

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)


# ── Dark+ palette ────────────────────────────────────────────────────
_C_KEYWORD  = QColor("#569cd6")   # import / const / async / etc.
_C_CONTROL  = QColor("#c586c0")   # if / for / return / etc.
_C_TYPE     = QColor("#4ec9b0")   # Page / HomePage / class names
_C_FUNCTION = QColor("#dcdcaa")   # method names
_C_STRING   = QColor("#ce9178")   # 'literal', "literal", `template`
_C_COMMENT  = QColor("#6a9955")   # // and /* */
_C_NUMBER   = QColor("#b5cea8")   # 42 / 3.14
_C_FG       = QColor("#d4d4d4")   # default text

# Gherkin-specific
_C_GHERKIN_KW    = QColor("#c586c0")   # Feature / Scenario / Given / etc.
_C_GHERKIN_TAG   = QColor("#4ec9b0")   # @tag
_C_GHERKIN_PARAM = QColor("#b5cea8")   # <parameter>


def _fmt(color: QColor, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(color)
    if bold:
        f.setFontWeight(QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


# ── TypeScript ────────────────────────────────────────────────────────
_TS_KEYWORDS = [
    "import", "export", "from", "as", "default",
    "const", "let", "var", "function", "async", "await",
    "class", "interface", "type", "enum", "extends", "implements",
    "public", "private", "protected", "readonly", "static",
    "new", "this", "super",
    "true", "false", "null", "undefined", "void",
]
_TS_CONTROL = [
    "if", "else", "for", "while", "do", "switch", "case", "break",
    "continue", "return", "throw", "try", "catch", "finally",
    "in", "of",
]
_TS_TYPES = [
    "string", "number", "boolean", "any", "unknown", "never", "object",
    "Promise", "Array", "Record", "Partial",
]


class TypeScriptHighlighter(QSyntaxHighlighter):
    """Regex-based highlighter — not a real parser but Cursor / VS Code
    Dark+ close enough for reviewing generated code."""

    def __init__(self, document: QTextDocument):
        super().__init__(document)
        # Order matters: comments last (they win) → strings → numbers →
        # keywords/types → identifiers. We build a list of (regex, fmt).
        self._rules: List[Tuple[QRegularExpression, QTextCharFormat]] = []

        # Numbers.
        self._rules.append((QRegularExpression(r"\b\d+(\.\d+)?\b"), _fmt(_C_NUMBER)))

        # Keywords.
        for kw in _TS_KEYWORDS:
            self._rules.append((QRegularExpression(r"\b" + kw + r"\b"), _fmt(_C_KEYWORD)))
        for kw in _TS_CONTROL:
            self._rules.append((QRegularExpression(r"\b" + kw + r"\b"), _fmt(_C_CONTROL)))
        for kw in _TS_TYPES:
            self._rules.append((QRegularExpression(r"\b" + kw + r"\b"), _fmt(_C_TYPE)))

        # Cucumber step-def calls: Given / When / Then / And / But.
        for kw in ("Given", "When", "Then", "And", "But", "Before", "After"):
            self._rules.append((QRegularExpression(r"\b" + kw + r"\b(?=\s*\()"), _fmt(_C_FUNCTION, bold=True)))

        # ClassName — capital letter start, at least one lowercase-like.
        # Matches HomePage, LoginPage, Page, Promise, etc. Non-capturing.
        self._rules.append((QRegularExpression(r"\b[A-Z][A-Za-z0-9_]*\b"), _fmt(_C_TYPE)))

        # Function-name calls: `foo(` — colour the identifier before the paren.
        self._rules.append((QRegularExpression(r"\b[a-z_][A-Za-z0-9_]*(?=\s*\()"), _fmt(_C_FUNCTION)))

        # Strings — three flavours. `template`, "double", 'single'. Basic;
        # no escape-inside-string awareness needed for this readonly viewer.
        self._rules.append((QRegularExpression(r"'([^'\\]|\\.)*'"), _fmt(_C_STRING)))
        self._rules.append((QRegularExpression(r'"([^"\\]|\\.)*"'), _fmt(_C_STRING)))
        self._rules.append((QRegularExpression(r"`([^`\\]|\\.)*`"), _fmt(_C_STRING)))

        # Line comments.
        self._rules.append((QRegularExpression(r"//[^\n]*"), _fmt(_C_COMMENT, italic=True)))

        # Multi-line comment handling uses the highlighter's block state.
        self._comment_start = QRegularExpression(r"/\*")
        self._comment_end = QRegularExpression(r"\*/")
        self._comment_fmt = _fmt(_C_COMMENT, italic=True)

    def highlightBlock(self, text: str) -> None:
        # Single-line rules first.
        for rgx, fmt in self._rules:
            it = rgx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        # Block-state driven /* ... */ across multiple lines.
        self.setCurrentBlockState(0)
        start_index = 0
        if self.previousBlockState() != 1:
            m = self._comment_start.match(text)
            start_index = m.capturedStart() if m.hasMatch() else -1
        while start_index >= 0:
            m_end = self._comment_end.match(text, start_index)
            if not m_end.hasMatch():
                self.setCurrentBlockState(1)
                length = len(text) - start_index
            else:
                length = m_end.capturedEnd() - start_index
            self.setFormat(start_index, length, self._comment_fmt)
            m_next = self._comment_start.match(text, start_index + length)
            start_index = m_next.capturedStart() if m_next.hasMatch() else -1


# ── Gherkin ────────────────────────────────────────────────────────────
_GHERKIN_KEYWORDS = [
    "Feature", "Rule", "Background", "Scenario",
    "Scenario Outline", "Scenario Template", "Examples",
    "Given", "When", "Then", "And", "But", "*",
]


class GherkinHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules: List[Tuple[QRegularExpression, QTextCharFormat]] = []

        # Comments — a leading `#` (whitespace before allowed).
        self._rules.append((QRegularExpression(r"^\s*#[^\n]*"), _fmt(_C_COMMENT, italic=True)))

        # Tags — @something at the start of a line (or after whitespace).
        self._rules.append((QRegularExpression(r"(?:^|\s)@[A-Za-z0-9_.-]+"), _fmt(_C_GHERKIN_TAG, bold=True)))

        # Keywords — colon-terminated OR step-word at start of line.
        for kw in ("Feature", "Rule", "Background", "Scenario Outline",
                   "Scenario Template", "Scenario", "Examples"):
            self._rules.append((
                QRegularExpression(r"^\s*" + kw + r"(?=:)"),
                _fmt(_C_GHERKIN_KW, bold=True),
            ))
        for kw in ("Given", "When", "Then", "And", "But"):
            self._rules.append((
                QRegularExpression(r"^\s*" + kw + r"\b"),
                _fmt(_C_GHERKIN_KW, bold=True),
            ))
        # Wildcard bullet.
        self._rules.append((QRegularExpression(r"^\s*\*"), _fmt(_C_GHERKIN_KW, bold=True)))

        # Placeholder <name> in scenario outlines.
        self._rules.append((QRegularExpression(r"<[^>]+>"), _fmt(_C_GHERKIN_PARAM)))

        # Strings — quoted values embedded in steps.
        self._rules.append((QRegularExpression(r"'([^'\\]|\\.)*'"), _fmt(_C_STRING)))
        self._rules.append((QRegularExpression(r'"([^"\\]|\\.)*"'), _fmt(_C_STRING)))

        # Numbers.
        self._rules.append((QRegularExpression(r"\b\d+(\.\d+)?\b"), _fmt(_C_NUMBER)))

    def highlightBlock(self, text: str) -> None:
        for rgx, fmt in self._rules:
            it = rgx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


# ── Dispatch ──────────────────────────────────────────────────────────
def highlighter_for(path: str, document: QTextDocument) -> Optional[QSyntaxHighlighter]:
    """Return the right highlighter for a filename, or None if we don't
    recognise the extension. Caller keeps a reference so Qt doesn't GC it."""
    p = (path or "").lower()
    if p.endswith(".ts") or p.endswith(".tsx") or p.endswith(".js"):
        return TypeScriptHighlighter(document)
    if p.endswith(".feature"):
        return GherkinHighlighter(document)
    return None
