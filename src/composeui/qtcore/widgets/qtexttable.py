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

from composeui.core.view import replace_cell

_Index = Union[QModelIndex, QPersistentModelIndex]


class QTextTableModel(QAbstractTableModel):
    """A table of text over the view's own lists, without a copy per cell.

    Qt asks only for the cells it draws, so a long table costs no more than a short one.
    The cells of `editable_columns` are editable: an edit changing a cell replaces its
    row (the view's lists aren't changed in place), then `cell_edited` emits it.
    """

    cell_edited = Signal(int, int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._headers: list[str] = []
        self._rows: list[list[str]] = []
        self.editable_columns: list[int] = []

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
        is_shown = role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole)
        if not is_shown or not index.isValid():
            return None
        row = self._rows[index.row()]
        # a row short of a cell shows it empty
        return row[index.column()] if index.column() < len(row) else None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and index.column() in self.editable_columns:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(  # noqa: N802
        self, index: _Index, value: Any, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        row, column, text = index.row(), index.column(), str(value)
        if text == (self.data(index) or ""):
            return False
        self._rows = replace_cell(self._rows, row, column, text)
        self.dataChanged.emit(index, index)
        self.cell_edited.emit(row, column, text)
        return True

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
    """A table of text, with no row numbers, where the user selects rows.

    One row at most by default; with `set_multiple_selection`, each click adds or removes
    a row, as Qt's `MultiSelection`. `selected_rows_changed` emits the selected rows'
    indexes, in order, only when the user changes them: setting them or the table from
    code stays silent. The user edits a cell of `set_editable_columns` with a double click
    or F2, and `cell_edited` emits its row, column and new text. `header_clicked` emits
    the column whose header the user clicked; the header shows the order
    `set_sort_indicator` gives, the table never sorting its rows itself.
    """

    selected_rows_changed = Signal(list)
    cell_edited = Signal(int, int, str)
    header_clicked = Signal(int)

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
        self.selectionModel().selectionChanged.connect(self._emit_selected_rows_changed)
        self._model.cell_edited.connect(self.cell_edited)
        self._sort: tuple[int, bool] | None = None
        self.horizontalHeader().sectionClicked.connect(self._header_clicked)

    def set_sort_indicator(self, sort: tuple[int, bool] | None, *, is_shown: bool) -> None:
        """Show the order: by a column, descending or not; None for the rows' own."""
        self._sort = sort
        header = self.horizontalHeader()
        header.setSortIndicatorShown(is_shown and sort is not None)
        header.setSectionsClickable(is_shown)
        if sort is not None:
            column, is_descending = sort
            order = Qt.SortOrder.DescendingOrder if is_descending else Qt.SortOrder.AscendingOrder
            header.setSortIndicator(column, order)

    def _header_clicked(self, column: int) -> None:
        # the header flips its indicator on a click: the order is the view's to say
        self.set_sort_indicator(self._sort, is_shown=self.horizontalHeader().sectionsClickable())
        self.header_clicked.emit(column)

    def set_table(self, headers: list[str], rows: list[list[str]]) -> None:
        self._is_setting = True
        try:
            self._model.set_table(headers, rows)
        finally:
            self._is_setting = False

    def set_editable_columns(self, columns: list[int]) -> None:
        self._model.editable_columns = columns

    def set_multiple_selection(self, *, is_multiple: bool) -> None:
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
            if is_multiple
            else QAbstractItemView.SelectionMode.SingleSelection
        )

    def selected_rows(self) -> list[int]:
        return sorted(index.row() for index in self.selectionModel().selectedRows())

    def set_selected_rows(self, rows: list[int]) -> None:
        self._is_setting = True
        try:
            selection = QItemSelection()
            for row in rows:
                index = self._model.index(row, 0)
                selection.select(index, index)
            self.selectionModel().select(
                selection,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        finally:
            self._is_setting = False

    def _emit_selected_rows_changed(
        self, _selected: QItemSelection, _deselected: QItemSelection
    ) -> None:
        if not self._is_setting:
            self.selected_rows_changed.emit(self.selected_rows())
