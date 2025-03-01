"""View for the pagination of a table/tree."""

from composeui.core.qt.qtview import QtView
from composeui.items.core.qt.widgets.paginationwidget import PaginationWidget
from composeui.items.core.views.ipaginationview import IPaginationView

from dataclasses import dataclass, field
from typing import List


@dataclass(eq=False)
class QtPaginationView(QtView, IPaginationView):
    view: PaginationWidget = field(init=False, default_factory=PaginationWidget)

    _current_page: int = field(init=False, default=-1)

    def __post_init__(self) -> None:
        super().__post_init__()
        # add signals
        self.size_changed.add_qt_signals((self.view, self.view.size_changed))
        self.current_page_changed.add_qt_signals((self.view, self.view.current_page_changed))
        self.current_page_size_changed.add_qt_signals(
            (self.view.page_size_combobox, self.view.page_size_combobox.currentIndexChanged)
        )
        self.first_clicked.add_qt_signals(
            (self.view.page_navigation_first, self.view.page_navigation_first.clicked)
        )
        self.previous_clicked.add_qt_signals(
            (self.view.page_navigation_previous, self.view.page_navigation_previous.clicked)
        )
        self.next_clicked.add_qt_signals(
            (self.view.page_navigation_next, self.view.page_navigation_next.clicked)
        )
        self.last_clicked.add_qt_signals(
            (self.view.page_navigation_last, self.view.page_navigation_last.clicked)
        )

    @property  # type: ignore[misc]
    def current_page(self) -> int:
        return self._current_page

    @current_page.setter
    def current_page(self, page: int) -> None:
        if self._current_page != page:
            self._current_page = page
            # emit the signal
            self.view.current_page_changed.emit()

    @property  # type: ignore[misc]
    def current_page_size_index(self) -> int:
        return self.view.page_size_combobox.currentIndex()

    @current_page_size_index.setter
    def current_page_size_index(self, index: int) -> None:
        self.view.page_size_combobox.setCurrentIndex(index)

    @property  # type: ignore[misc]
    def is_first_enabled(self) -> bool:
        return self.view.page_navigation_first.isEnabled()

    @is_first_enabled.setter
    def is_first_enabled(self, is_enabled: bool) -> None:
        self.view.page_navigation_first.setEnabled(is_enabled)

    @property  # type: ignore[misc]
    def is_previous_enabled(self) -> bool:
        return self.view.page_navigation_previous.isEnabled()

    @is_previous_enabled.setter
    def is_previous_enabled(self, is_enabled: bool) -> None:
        self.view.page_navigation_previous.setEnabled(is_enabled)

    @property  # type: ignore[misc]
    def is_next_enabled(self) -> bool:
        return self.view.page_navigation_next.isEnabled()

    @is_next_enabled.setter
    def is_next_enabled(self, is_enabled: bool) -> None:
        self.view.page_navigation_next.setEnabled(is_enabled)

    @property  # type: ignore[misc]
    def is_last_enabled(self) -> bool:
        return self.view.page_navigation_last.isEnabled()

    @is_last_enabled.setter
    def is_last_enabled(self, is_enabled: bool) -> None:
        self.view.page_navigation_last.setEnabled(is_enabled)

    @property  # type: ignore[misc]
    def page_size_values(self) -> List[int]:
        return [
            int(self.view.page_size_combobox.itemData(i))
            for i in range(self.view.page_size_combobox.count())
        ]

    @page_size_values.setter
    def page_size_values(self, values: List[int]) -> None:
        if hasattr(self, "view"):
            self.view.page_size_combobox.blockSignals(True)
            self.view.page_size_combobox.clear()
            for page_size in values:
                self.view.page_size_combobox.addItem(str(page_size), userData=page_size)
            self.view.page_size_combobox.setCurrentIndex(0)
            self.view.page_size_combobox.blockSignals(False)

    @property  # type: ignore[misc]
    def row_summary(self) -> str:
        return self.view.row_summary.text()

    @row_summary.setter
    def row_summary(self, text: str) -> None:
        self.view.row_summary.setText(text)

    @property  # type: ignore[misc]
    def page_navigation_description(self) -> str:
        return self.view.page_navigation_description.text()

    @page_navigation_description.setter
    def page_navigation_description(self, text: str) -> None:
        self.view.page_navigation_description.setText(text)
