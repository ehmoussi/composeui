"""A console: plain text that grows at its end, scrolled to it unless the user scrolled up."""

from __future__ import annotations

from typing import Any

from qtpy.QtCore import Qt
from qtpy.QtGui import QFontDatabase, QTextCursor
from qtpy.QtWidgets import QPlainTextEdit, QSizePolicy, QToolButton, QVBoxLayout, QWidget


class QConsole(QPlainTextEdit):
    """Read-only plain text in a fixed-width font, a block per line, the last being written.

    `set_max_lines` keeps that many lines, the line being written not counted: Qt drops
    the oldest blocks. The user selects and copies the text.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.setReadOnly(True)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

    def set_max_lines(self, count: int) -> None:
        self.setMaximumBlockCount(count + 1)

    def set_text(self, text: str) -> None:
        """Show `text` instead, from its end."""
        self.setPlainText(text)
        self._scroll_to_end()

    def add(self, lines: list[str], last_line: str) -> None:
        """End the line being written with `lines`, then write `last_line` in its place.

        The text keeps its place on the screen unless the end was shown.
        """
        bar = self.verticalScrollBar()
        is_at_end = bar.value() == bar.maximum()
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText("\n".join([*lines, last_line]))
        if is_at_end:
            self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


class QConsoleBox(QWidget):
    """A `QConsole` under its controls: `save`, at the right, as a large table's export."""

    def __init__(self) -> None:
        super().__init__()
        self.text = QConsole()
        self.save = QToolButton()
        self.save.setAutoRaise(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.save, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.text, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
