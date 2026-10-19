from __future__ import annotations

from typing import Any

from qtpy.QtWidgets import QHBoxLayout, QLineEdit, QStyle, QToolButton, QWidget


class QFilePathField(QWidget):
    """A field typing a file's path, then a "…" button and a reload button, hidden by default.

    The buttons only report their clicks: the renderer opens the file dialog. Both are
    squares as tall as the field: a tool button's own size depends on its text or icon,
    so "…" and the icon would differ from the field and from each other.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.line_edit = QLineEdit()
        layout.addWidget(self.line_edit)
        self.browse_button = QToolButton()
        self.browse_button.setText("…")
        layout.addWidget(self.browse_button)
        self.reload_button = QToolButton()
        self.reload_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.reload_button.setVisible(False)
        layout.addWidget(self.reload_button)
        side = self.line_edit.sizeHint().height()
        for button in (self.browse_button, self.reload_button):
            button.setFixedSize(side, side)
