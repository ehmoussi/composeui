from __future__ import annotations

from typing import Any, Union

from qtpy.QtCore import (
    QAbstractTableModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from qtpy.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QHeaderView,
    QSizePolicy,
    QTableView,
)

_Index = Union[QModelIndex, QPersistentModelIndex]


class QTextTableModel(QAbstractTableModel):
    """A read-only table of text over the view's own lists, without a copy per cell.

    Qt asks only for the cells it draws, so a long table costs no more than a short one.
    Its items aren't editable: `QAbstractTableModel.flags` leaves `ItemIsEditable` out.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._headers: list[str] = []
        self._rows: list[list[str]] = []

    def set_table(self, headers: list[str], rows: list[list[str]]) -> None:
        self.beginResetModel()
        self._headers = headers
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or not index.isValid():
            return None
        row = self._rows[index.row()]
        # a row short of a cell shows it empty
        return row[index.column()] if index.column() < len(row) else None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._headers[section]
        return None


class QTextTableView(QTableView):
    """A read-only table of text, with no row numbers, where the user selects one row.

    `selected_row_changed` emits the selected row's index, or `None`, only when the
    user changes the selection: setting it or the table from code stays silent.
    """

    selected_row_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._model = QTextTableModel(self)
        self.setModel(self._model)
        self._is_setting = False
        self.verticalHeader().setVisible(False)
        # as tall as its rows, not Qt's default height, which leaves an empty block
        self.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        # the columns share the width; light rows instead of a box around each cell
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 10)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.selectionModel().selectionChanged.connect(self._emit_selected_row_changed)

    def set_table(self, headers: list[str], rows: list[list[str]]) -> None:
        self._is_setting = True
        try:
            self._model.set_table(headers, rows)
        finally:
            self._is_setting = False

    def selected_row(self) -> int | None:
        rows = self.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def set_selected_row(self, row: int | None) -> None:
        self._is_setting = True
        try:
            if row is None:
                self.clearSelection()
            else:
                self.selectionModel().select(
                    self._model.index(row, 0),
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        finally:
            self._is_setting = False

    def _emit_selected_row_changed(
        self, _selected: QItemSelection, _deselected: QItemSelection
    ) -> None:
        if not self._is_setting:
            self.selected_row_changed.emit(self.selected_row())
