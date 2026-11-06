from __future__ import annotations

from typing import Any

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class QFileUpload(QWidget):
    """A button picking a file, then the name of the file picked.

    The button only reports its clicks: the renderer opens the file dialog.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton()
        layout.addWidget(self.button)
        self.name = QLabel()
        # a file's name is text: a QLabel would read one that looks like HTML as HTML
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.name, stretch=1)
