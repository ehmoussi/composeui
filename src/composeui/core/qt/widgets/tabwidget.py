r"""Tab widget."""

from qtpy.QtCore import Signal  # type: ignore[attr-defined]
from qtpy.QtWidgets import QTabWidget

from typing import Any


class TabWidget(QTabWidget):
    r"""QTabWidget with the index clicked in the bar stored."""

    tabbar_clicked = Signal()
    tabbar_double_clicked = Signal()
    tab_close_requested = Signal()
    current_changed = Signal()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.index_clicked = -1
        self.tabBarClicked.connect(self._tabbar_clicked)
        self.tabBarDoubleClicked.connect(self._tabbar_double_clicked)
        self.tabCloseRequested.connect(self._tab_close_requested)
        self.currentChanged.connect(self._current_changed)

    def _tabbar_clicked(self, index: int) -> None:
        self.index_clicked = index
        self.tabbar_clicked.emit()

    def _tabbar_double_clicked(self, index: int) -> None:
        self.index_clicked = index
        self.tabbar_double_clicked.emit()

    def _tab_close_requested(self, index: int) -> None:
        self.index_clicked = index
        self.tab_close_requested.emit()

    def _current_changed(self, index: int) -> None:
        self.index_clicked = index
        self.current_changed.emit()
