"""View text that Qt shows as it is, never read as HTML.

A `QLabel` and a tooltip guess their text's format: a text that looks like HTML, such as
`<b>x</b>`, would show as rich text, its tags hidden and its links clickable.
"""

from __future__ import annotations

import html

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QLabel


def plain_label() -> QLabel:
    """Get a label that shows its text as plain text."""
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def plain_tool_tip(text: str) -> str:
    """Get `text` as a tooltip that shows it as it is.

    A tooltip has no plain format: a text with a tag is escaped as rich text instead.
    """
    if "<" not in text:
        return text  # no tag: Qt shows it as plain text
    return "<p>{}</p>".format(html.escape(text, quote=False).replace("\n", "<br>"))
