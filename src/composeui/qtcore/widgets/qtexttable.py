from __future__ import annotations

from typing import Any, Union

from qtpy.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt
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
    """A read-only table of text, with no row numbers."""

    def __init__(self) -> None:
        super().__init__()
        self._model = QTextTableModel(self)
        self.setModel(self._model)
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

    def set_table(self, headers: list[str], rows: list[list[str]]) -> None:
        self._model.set_table(headers, rows)
