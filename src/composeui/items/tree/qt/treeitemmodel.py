r"""Item model of a tree."""

from composeui.items.core.itemsutils import BackgroundType
from composeui.items.tree.abstracttreeitems import AbstractTreeItems

from qtpy.QtCore import Signal  # type: ignore[attr-defined]
from qtpy.QtCore import Slot  # type: ignore[attr-defined]
from qtpy.QtCore import (
    QAbstractItemModel,
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
from collections import deque
from functools import partial
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union, overload


class TreeItemModel(QSortFilterProxyModel):
    r"""Item model for a tree."""

    def __init__(self, items: AbstractTreeItems[Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.source_model = _TreeItemModel(items, *args, **kwargs)
        self.setSourceModel(self.source_model)
        self.items = self.source_model.items
        self.setDynamicSortFilter(False)
        self.setSortRole(Qt.InitialSortOrderRole)
        self.modelAboutToBeReset.connect(self.source_model.update_cache)
        # self.modelReset.connect(self.source_model.highlight_indices.clear)

    @Slot()
    def update_cache(self) -> None:
        self.source_model.update_cache()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        r"""Check if the row is not filtered."""
        if source_parent.isValid():
            return not self.items.is_filtered(source_row, source_parent.internalPointer())
        else:
            return not self.items.is_filtered(source_row)

    def lessThan(  # noqa: N802
        self, source_left: QModelIndex, source_right: QModelIndex
    ) -> bool:
        r"""Check if the left index is less than the right index."""
        try:
            left_rows = source_left.internalPointer()
            *left_parent_rows, left_row = left_rows
            value_left = float(
                self.items.get_data(left_row, source_left.column(), left_parent_rows)
            )
            right_rows = source_right.internalPointer()
            *right_parent_rows, right_row = right_rows
            value_right = float(
                self.items.get_data(right_row, source_right.column(), right_parent_rows)
            )
        except ValueError:
            return bool(super().lessThan(source_left, source_right))
        else:
            return value_left < value_right

    def index_from_rows(self, rows: Tuple[int, ...], column: int) -> QModelIndex:
        r"""Get the index from the rows and column."""
        source_index = self.source_model.index_from_rows(rows, column)
        return self.mapFromSource(source_index)

    def generate_item_selection(
        self, selected_items: Dict[Tuple[int, ...], List[int]]
    ) -> QItemSelection:
        r"""Generate an item selection from the dictionary of selection."""
        item_selection = QItemSelection()
        for rows, columns in selected_items.items():
            for column in columns:
                index = self.index_from_rows(rows, column)
                item_selection.merge(
                    QItemSelection(index, index),
                    QItemSelectionModel.Select,
                )
        return item_selection


class _TreeItemModel(QAbstractItemModel):
    r"""Item model for the table of the Table GUI."""

    item_toggled = Signal()

    def __init__(self, items: AbstractTreeItems[Any], *args: Any, **kwargs: Any) -> None:
        r"""Instantiate the class."""
        super().__init__(*args, **kwargs)
        self.items = items
        self._cache_rows: Dict[Tuple[int, ...], Tuple[int, ...]] = {}
        self._cache_data: Dict[Tuple[int, ...], List[List[str]]] = {}
        self.highlight_indices: Set[Tuple[int, Tuple[int, ...], int, bool]] = set()
        self.update_cache()

    def index_from_rows(self, rows: Tuple[int, ...], column: int) -> QModelIndex:
        r"""Get the index from the rows and column."""
        ancestors = deque(rows)
        index = QModelIndex()
        while len(ancestors) > 0:
            row = ancestors.popleft()
            current_column = column if len(ancestors) == 0 else 0
            index = self.index(row, current_column, index)
        return index

    def update_cache(self) -> None:
        r"""Update the internal datas."""
        self._cache_data = self.items.get_all_datas()
        self._cache_rows = {
            (*parent_rows, row): (*parent_rows, row)
            for parent_rows in self._cache_data
            for row in range(len(self._cache_data[parent_rows]))
        }

    def index(
        self, row: int, column: int, parent: QModelIndex = QModelIndex()  # noqa: B008
    ) -> QModelIndex:
        r"""Get the index of the item for the given row and column."""
        if self.hasIndex(row, column, parent):
            if parent.isValid():
                parent_rows = parent.internalPointer()
            else:
                parent_rows = ()
            return self.createIndex(row, column, self._cache_rows[(*parent_rows, row)])
        else:
            return QModelIndex()

    @overload
    def parent(self, child: QModelIndex) -> QModelIndex: ...
    @overload
    def parent(self) -> QObject: ...
    def parent(self, child: Optional[QModelIndex] = None) -> Union[QObject, QModelIndex]:
        """Get the parent of the given index."""
        if child is not None:
            if child.isValid():
                rows = child.internalPointer()
                if len(rows) > 1:
                    return self.createIndex(rows[-2], 0, self._cache_rows[rows[:-1]])
            return QModelIndex()
        else:
            return super().parent()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        """Get the number of rows under the given parent."""
        if parent.isValid():
            return len(self._cache_data[parent.internalPointer()])
        else:
            return len(self._cache_data[()])

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        r"""Get the number of columns for the children of the given parent."""
        return self.items.get_nb_columns()

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        r"""Get the data stored under the given role for the given index."""
        rows = index.internalPointer()
        parent_rows, row = rows[:-1], rows[-1]
        column = index.column()
        if role == Qt.DisplayRole:
            return self._cache_data[parent_rows][row][column]
        elif role == Qt.EditRole:
            return self.items.get_edit_data(row, column, parent_rows)
        elif role == Qt.BackgroundRole:
            background = self.items.get_background(row, column, parent_rows)
            style = Qt.SolidPattern
            if BackgroundType.STRIPED in background:
                style = Qt.BDiagPattern
            if (row, parent_rows, column, False) in self.highlight_indices:
                return QBrush(QColor(255, 0, 0, 30), style)
            elif (row, parent_rows, column, True) in self.highlight_indices:
                return QBrush(QColor(186, 216, 0, 30), style)
            if BackgroundType.STRIPED in background:
                return QBrush(style)
        elif role == Qt.CheckStateRole:
            is_checked = self.items.is_checked(row, column, parent_rows)
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
        rows = index.internalPointer()
        parent_rows, row = rows[:-1], rows[-1]
        column = index.column()
        if role == Qt.EditRole:
            is_ok = self.items.set_data(row, column, str(value), parent_rows)
            if is_ok:
                self._cache_data[parent_rows][row][column] = str(value)
                self.dataChanged.emit(index, index, [Qt.EditRole])
            return is_ok
        elif role == Qt.CheckStateRole:
            is_ok = self.items.set_checked(row, column, bool(value), parent_rows)
            if is_ok:
                self.dataChanged.emit(index, index, [Qt.CheckStateRole])
                self.item_toggled.emit()
            return is_ok
        return super().setData(index, value, role)

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        r"""Get the item flags for the given index."""
        flags = Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled | Qt.ItemIsSelectable
        rows = index.internalPointer()
        column = index.column()
        if rows is None:
            return flags
        row, parent_rows = rows[-1], rows[:-1]
        if self.items.is_checked(row, column, parent_rows) is not None:
            flags |= Qt.ItemIsUserCheckable
        if self.items.is_enabled(row, column, parent_rows):
            flags |= Qt.ItemIsEnabled
        if self.items.is_editable(row, column, parent_rows):
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
        positions = [index.internalPointer() for index in indexes if index.isValid()]
        mime_data.setData("bstream", pickle.dumps(positions))
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
            to_parent_rows = parent.internalPointer()
            if to_parent_rows is None:
                to_parent_rows = ()
            positions = set(pickle.loads(mime_data.data("bstream").data()))
            is_ok = True
            for index, (*from_parent_rows, from_row) in enumerate(positions):
                is_ok &= self.items.move(
                    from_row, row + index, from_parent_rows, to_parent_rows
                )
            self.beginResetModel()
            self.endResetModel()
            return is_ok
        return False

    def failed_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None:
        r"""Highlight the given index."""
        highlight_tree_infos = [(*item, False) for item in items]
        self.highlight_indices.update(highlight_tree_infos)
        QTimer.singleShot(700, partial(self.remove_tree_highlight, highlight_tree_infos))

    def successful_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None:
        r"""Highlight the given index."""
        highlight_tree_infos = [(*item, True) for item in items]
        self.highlight_indices.update(highlight_tree_infos)
        QTimer.singleShot(700, partial(self.remove_tree_highlight, highlight_tree_infos))

    @Slot()
    def remove_tree_highlight(
        self,
        indices_infos: List[Tuple[int, Tuple[int, ...], int, bool]],
    ) -> None:
        r"""Remove the highlighted items."""
        for infos in indices_infos:
            if infos in self.highlight_indices:
                self.highlight_indices.remove(infos)
                row, parent_rows, column, _ = infos
                rows = (*parent_rows, row)
                index = self.index_from_rows(rows, column)
                self.dataChanged.emit(index, index, [Qt.BackgroundRole])
