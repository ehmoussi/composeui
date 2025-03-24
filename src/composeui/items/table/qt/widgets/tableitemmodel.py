r"""Item model of a table."""

from composeui.items.core.itemsutils import BackgroundType
from composeui.items.table.abstracttableitems import AbstractTableItems

from qtpy.QtCore import Signal  # type: ignore[attr-defined]
from qtpy.QtCore import Slot  # type: ignore[attr-defined]
from qtpy.QtCore import (
    QAbstractTableModel,
    QItemSelection,
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QObject,
    QSortFilterProxyModel,
    Qt,
    QTimer,
)
from qtpy.QtGui import QBrush, QColor

import contextlib
import pickle
from functools import partial
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union


class TableItemModel(QSortFilterProxyModel):
    r"""Item model for a tree."""

    def __init__(self, items: AbstractTableItems[Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.source_model = _TableItemModel(items, *args, **kwargs)
        self.setSourceModel(self.source_model)
        self.items = self.source_model.items
        self.setDynamicSortFilter(False)
        self.setSortRole(Qt.InitialSortOrderRole)
        self.modelAboutToBeReset.connect(self.update_cache)

    @Slot()
    def update_cache(self) -> None:
        self.source_model.update_cache()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        r"""Check if the row is not filtered."""
        return not self.items.is_filtered(source_row)

    def lessThan(  # noqa: N802
        self, source_left: QModelIndex, source_right: QModelIndex
    ) -> bool:
        r"""Check if the left index is less than the right index."""
        try:
            value_left = float(
                self.items.get_edit_data(source_left.row(), source_left.column())
            )
            value_right = float(
                self.items.get_edit_data(source_right.row(), source_right.column())
            )
        except ValueError:
            return bool(super().lessThan(source_left, source_right))
        else:
            return value_left < value_right

    def generate_item_selection(
        self, selected_items: Dict[Tuple[int, ...], List[int]]
    ) -> QItemSelection:
        r"""Generate an item selection from the dictionary of selection."""
        item_selection = QItemSelection()
        for (row,), columns in selected_items.items():
            for column in columns:
                source_index = self.source_model.index(row, column)
                index = self.mapFromSource(source_index)
                item_selection.merge(
                    QItemSelection(index, index),
                    QItemSelectionModel.Select,
                )
        return item_selection


class _TableItemModel(QAbstractTableModel):
    r"""Item model for a table."""

    item_toggled = Signal()

    def __init__(
        self, items: AbstractTableItems[Any], parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)
        self.items = items
        self.highlight_indices: Set[Tuple[int, int, bool]] = set()
        self._cache_data: List[List[str]] = []
        self.update_cache()

    def update_cache(self) -> None:
        self._cache_data = self.items.get_all_datas()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        r"""Get the number of rows under the given parent."""
        if parent.isValid() or len(self._cache_data) == 0:
            return 0
        return len(self._cache_data[0])

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        r"""Get the number of columns for the children of the given parent."""
        if parent.isValid():
            return 0
        return len(self._cache_data)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        r"""Get the data stored under the given role for the given index."""
        row = index.row()
        if role == Qt.DisplayRole:
            return self._cache_data[index.column()][row]
        elif role == Qt.EditRole:
            return self.items.get_edit_data(row, index.column())
        elif role == Qt.BackgroundRole:
            background = self.items.get_background(row, index.column())
            style = Qt.SolidPattern
            if BackgroundType.STRIPED in background:
                style = Qt.BDiagPattern
            if (row, index.column(), False) in self.highlight_indices:
                return QBrush(QColor(255, 0, 0, 30), style)
            elif (row, index.column(), True) in self.highlight_indices:
                return QBrush(QColor(186, 216, 0, 30), style)
            if BackgroundType.STRIPED in background:
                return QBrush(style)
        elif role == Qt.CheckStateRole:
            is_checked = self.items.is_checked(row, index.column())
            if is_checked is not None:
                if is_checked:
                    return Qt.Checked
                else:
                    return Qt.Unchecked
        return None

    def setData(  # noqa: N802
        self, index: QModelIndex, value: Any, role: int = Qt.EditRole
    ) -> bool:
        r"""Set the data of the given index."""
        row = index.row()
        column = index.column()
        if role == Qt.EditRole:
            value_str = str(value)
            is_ok = self.items.set_data_with_history(row, column, value_str)
            if is_ok:
                self._cache_data[column][row] = value_str
                self.dataChanged.emit(index, index, [Qt.EditRole])
            return is_ok
        elif role == Qt.CheckStateRole:
            is_ok = self.items.set_checked_with_history(row, column, bool(value))
            if is_ok:
                self.dataChanged.emit(index, index, [Qt.CheckStateRole])
                self.item_toggled.emit()
            return is_ok
        return super().setData(index, value, role)

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        r"""Get the item flags for the given index."""
        flags = Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled | Qt.ItemIsSelectable
        row = index.row()
        column = index.column()
        if self.items.is_checked(row, column) is not None:
            flags |= Qt.ItemIsUserCheckable
        if self.items.is_enabled(row, column):
            flags |= Qt.ItemIsEnabled
        if self.items.is_editable(row, column):
            flags |= Qt.ItemIsEditable
        return flags

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> Any:
        r"""Return the header data for the given role, section and orientation."""
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            with contextlib.suppress(IndexError):
                return self.items.get_column_title(section)
        elif orientation == Qt.Vertical and role == Qt.DisplayRole:
            return str(section + 1)
        return None

    def supportedDropActions(self) -> Qt.DropActions:  # noqa: N802
        return Qt.DropActions(Qt.MoveAction)

    def mimeTypes(self) -> List[str]:  # noqa: N802
        return ["bstream"]

    def mimeData(self, indexes: Iterable[QModelIndex]) -> QMimeData:  # noqa: N802
        """Get the positions of the given indexes into a QMimeData."""
        mime_data = QMimeData()
        rows = [index.row() for index in indexes if index.isValid()]
        mime_data.setData("bstream", pickle.dumps(rows))
        return mime_data

    def dropMimeData(  # noqa: N802
        self,
        mime_data: QMimeData,
        action: Qt.DropAction,
        row: int,
        column: int,
        parent: QModelIndex,
    ) -> bool:
        """Drop the items currently dragged into a new position."""
        if action == Qt.MoveAction:
            rows = set(pickle.loads(mime_data.data("bstream").data()))
            is_ok = True
            to_row = parent.row()
            for index, from_row in enumerate(rows):
                is_ok &= self.items.move(from_row, to_row + index)
            self.beginResetModel()
            self.endResetModel()
            return is_ok
        return False

    def failed_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None:
        r"""Highlight the given index."""
        highlight_table_infos = [(row, column, False) for (row, *_, column) in items]
        self.highlight_indices.update(highlight_table_infos)
        QTimer.singleShot(700, partial(self.remove_table_highlight, highlight_table_infos))

    def successful_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None:
        r"""Highlight the given index."""
        highlight_table_infos = [(row, column, True) for (row, *_, column) in items]
        self.highlight_indices.update(highlight_table_infos)
        QTimer.singleShot(700, partial(self.remove_table_highlight, highlight_table_infos))

    @Slot()
    def remove_table_highlight(
        self,
        indices_infos: Union[List[Tuple[int, int, bool]],],
    ) -> None:
        r"""Remove the highlighted items."""
        for infos in indices_infos:
            if infos in self.highlight_indices:
                self.highlight_indices.remove(infos)
                row, column, _ = infos
                index = self.index(row, column)
                self.dataChanged.emit(index, index, [Qt.BackgroundRole])
