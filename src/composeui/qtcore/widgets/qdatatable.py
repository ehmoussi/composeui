"""A large table's widget: a `QTableView` that asks its view for the rows it draws."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Protocol, Union

from qtpy.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from qtpy.QtGui import QAction, QKeySequence, QPalette
from qtpy.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from composeui.qtcore.widgets.qfiltertable import QTableFilterBar

if TYPE_CHECKING:
    from qtpy.QtGui import QKeyEvent

_Index = Union[QModelIndex, QPersistentModelIndex]


class DataTableLike(Protocol):
    """What the model reads from a `DataTableView`."""

    @property
    def headers(self) -> list[str]: ...
    @property
    def row_count(self) -> int: ...
    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]: ...
    def is_selected(self, row_id: Any) -> bool: ...


class QDataTableModel(QAbstractTableModel):
    """The rows of a large table, read from its view as Qt draws them, never all at once.

    Qt asks for the cells it draws, and the view reads them from its source a window at
    a time. `reset` shows a new order of the rows; `repaint` the same rows, formatted or
    selected again. The rows' headers are their positions, from 1. A selected row has the
    palette's highlight colors.
    """

    def __init__(self, table: DataTableLike, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._table = table

    def reset(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def repaint(self) -> None:
        if self.rowCount() > 0 and self.columnCount() > 0:
            last = self.index(self.rowCount() - 1, self.columnCount() - 1)
            self.dataChanged.emit(self.index(0, 0), last)

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else self._table.row_count

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._table.headers)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        looks: dict[int, QPalette.ColorRole] = {
            Qt.ItemDataRole.BackgroundRole: QPalette.ColorRole.Highlight,
            Qt.ItemDataRole.ForegroundRole: QPalette.ColorRole.HighlightedText,
        }
        if not index.isValid() or (role != Qt.ItemDataRole.DisplayRole and role not in looks):
            return None
        rows = self._table.rows(index.row(), index.row() + 1)
        if len(rows) == 0:  # rows not shown any longer, the model not reset yet
            return None
        row_id, cells = rows[0]
        if role in looks:
            is_selected = self._table.is_selected(row_id)
            return QApplication.palette().brush(looks[role]) if is_selected else None
        return cells[index.column()] if index.column() < len(cells) else None

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            headers = self._table.headers
            return headers[section] if section < len(headers) else None
        return f"{section + 1:,}"


class QDataTableView(QTableView):
    """A large table: as tall as its place, its rows scrolled, each row of the same height.

    The rows all have the height of a line of text, so the scroll bar's place gives the
    rows shown with no row measured. The columns share the width. `header_clicked` emits
    the column whose header the user clicked; the header shows the order
    `set_sort_indicator` gives, the table never sorting its rows itself.

    The table selects no row itself: `row_clicked` emits the position the user clicked,
    or the current one on Space, and whether Shift extends the selection to it;
    `row_activated` emits it on a double click, Enter or Return. `copy_requested` emits
    on the platform's Copy shortcut (Ctrl+C), `export_requested` on `export_action`, in
    the table's context menu.
    """

    header_clicked = Signal(int)
    row_clicked = Signal(int, bool)
    row_activated = Signal(int)
    copy_requested = Signal()
    export_requested = Signal()

    def __init__(self, table: DataTableLike) -> None:
        super().__init__()
        self._sort: Optional[tuple[int, bool]] = None
        self.data_model = QDataTableModel(table, self)
        self.setModel(self.data_model)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rows = self.verticalHeader()
        rows.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        rows.setDefaultSectionSize(self.fontMetrics().height() + 10)
        rows.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        columns = self.horizontalHeader()
        columns.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        columns.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        columns.setSectionsClickable(True)
        columns.sectionClicked.connect(self._header_clicked)
        self.clicked.connect(self._row_clicked)
        self.doubleClicked.connect(lambda index: self.row_activated.emit(index.row()))
        self.export_action = QAction(self)
        self.export_action.triggered.connect(self.export_requested.emit)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.addAction(self.export_action)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        current = self.currentIndex()
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_requested.emit()
        elif current.isValid() and event.key() == Qt.Key.Key_Space:
            is_extended = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.row_clicked.emit(current.row(), is_extended)
        elif current.isValid() and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.row_activated.emit(current.row())
        else:
            super().keyPressEvent(event)

    def _row_clicked(self, index: QModelIndex) -> None:
        modifiers = QApplication.keyboardModifiers()
        self.row_clicked.emit(index.row(), bool(modifiers & Qt.KeyboardModifier.ShiftModifier))

    def set_sort_indicator(self, sort: Optional[tuple[int, bool]]) -> None:
        """Show the order: by a column, descending or not; None for the source's own."""
        self._sort = sort
        header = self.horizontalHeader()
        header.setSortIndicatorShown(sort is not None)
        if sort is not None:
            column, is_descending = sort
            order = Qt.SortOrder.DescendingOrder if is_descending else Qt.SortOrder.AscendingOrder
            header.setSortIndicator(column, order)

    def _header_clicked(self, column: int) -> None:
        # the header flips its indicator on a click: the order is the view's to say
        self.set_sort_indicator(self._sort)
        self.header_clicked.emit(column)


class QDataFilterTable(QWidget):
    """A large table under its filter bar, which shows only while a column filters.

    When the search or the filters hide every row, `empty` says so under the headers.
    """

    def __init__(self, table: DataTableLike) -> None:
        super().__init__()
        self.bar = QTableFilterBar()
        self.table = QDataTableView(table)
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.bar)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty)
        self.bar.setVisible(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
