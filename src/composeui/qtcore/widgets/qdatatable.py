"""A large table's widget: a `QTableView` that asks its view for the rows it draws."""

from __future__ import annotations

from typing import Any, Optional, Protocol, Union

from qtpy.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from qtpy.QtWidgets import QAbstractItemView, QHeaderView, QSizePolicy, QTableView

_Index = Union[QModelIndex, QPersistentModelIndex]


class DataTableLike(Protocol):
    """What the model reads from a `DataTableView`."""

    @property
    def headers(self) -> list[str]: ...
    @property
    def row_count(self) -> int: ...
    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]: ...


class QDataTableModel(QAbstractTableModel):
    """The rows of a large table, read from its view as Qt draws them, never all at once.

    Qt asks for the cells it draws, and the view reads them from its source a window at
    a time. `reset` shows a new order of the rows; `repaint` the same rows, formatted
    again. The rows' headers are their positions, from 1.
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
            self.dataChanged.emit(self.index(0, 0), last, [Qt.ItemDataRole.DisplayRole])

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else self._table.row_count

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._table.headers)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        rows = self._table.rows(index.row(), index.row() + 1)
        if len(rows) == 0:  # rows not shown any longer, the model not reset yet
            return None
        cells = rows[0][1]
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
    rows shown with no row measured. The columns share the width.
    """

    def __init__(self, table: DataTableLike) -> None:
        super().__init__()
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
