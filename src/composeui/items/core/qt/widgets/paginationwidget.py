"""Widget of the pagination of a table/tree."""

from qtpy.QtCore import Qt, Signal  # type: ignore[attr-defined]
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from typing import Optional


class PaginationWidget(QWidget):
    size_changed = Signal()
    current_page_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout()
        self._layout.addStretch()
        self.setLayout(self._layout)
        self._page_size_label = QLabel("Page Size:")
        self._layout.addWidget(self._page_size_label)
        self.page_size_combobox = QComboBox()
        self._layout.addWidget(self.page_size_combobox)
        self.row_summary = QLabel()
        self.row_summary.setMinimumWidth(80)
        self._layout.addWidget(self.row_summary)
        self.page_navigation_first = QPushButton()
        self.page_navigation_first.setIcon(QIcon(":/icons/first_page.png"))
        self._layout.addWidget(self.page_navigation_first)
        self.page_navigation_previous = QPushButton()
        self.page_navigation_previous.setIcon(QIcon(":/icons/previous_page.png"))
        self._layout.addWidget(self.page_navigation_previous)
        self.page_navigation_description = QLabel()
        self.page_navigation_description.setMinimumWidth(70)
        self.page_navigation_description.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self.page_navigation_description)
        self.page_navigation_next = QPushButton()
        self.page_navigation_next.setIcon(QIcon(":/icons/next_page.png"))
        self._layout.addWidget(self.page_navigation_next)
        self.page_navigation_last = QPushButton()
        self.page_navigation_last.setIcon(QIcon(":/icons/last_page.png"))
        self._layout.addWidget(self.page_navigation_last)
