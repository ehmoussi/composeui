r"""Items widget."""

from composeui.items.core.qt.widgets.itemswidget import ItemsWidget, set_delegates
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.table.qt.widgets.tableitemmodel import TableItemModel
from composeui.items.tree.qt.treeitemmodel import TreeItemModel

from qtpy.QtCore import Signal  # type: ignore[attr-defined]
from qtpy.QtCore import Slot  # type: ignore[attr-defined]
from qtpy.QtCore import QItemSelection, QItemSelectionModel, QModelIndex, QPoint
from qtpy.QtGui import QShowEvent
from qtpy.QtWidgets import QAbstractItemDelegate, QHeaderView, QTableView, QWidget
from typing_extensions import OrderedDict

from typing import Any, List, Optional, Set, Tuple


class TableWidget(ItemsWidget):
    r"""Item widget."""

    def __init__(
        self,
        double_clicked_is_check: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        # Model/Items
        self._model: Optional[TableItemModel] = None
        super().__init__(_TableView(), double_clicked_is_check, parent)
        self.table: _TableView
        self._items: Optional[AbstractTableItems[Any]] = None

    def failed_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None:
        r"""Highlight the given index."""
        if self._model is not None:
            self._model.source_model.failed_highlight(items)

    def successful_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None:
        r"""Highlight the given index."""
        if self._model is not None:
            self._model.source_model.successful_highlight(items)

    def update_view(self) -> None:
        r"""Update the table."""
        assert self._items is not None, "The items of the table is not defined."
        if self._model is not None:
            self.pagination_view.view.size_changed.emit()
            self._model.beginResetModel()
            self._model.endResetModel()
            if isinstance(self.table, _TableView):
                self.table.horizontalHeader().resizeSections(QHeaderView.ResizeToContents)

    @property
    def items(self) -> Optional[AbstractTableItems[Any]]:
        """Get the items."""
        return self._items

    @items.setter
    def items(self, items: AbstractTableItems[Any]) -> None:
        """Set the items."""
        self._set_items(items)

    def _set_items(self, items: AbstractTableItems[Any]) -> None:
        """Set the items."""
        self._items = items
        self._model = TableItemModel(items)
        self.table.setModel(self._model)
        self._set_delegates()
        self.filter_view.columns_selector.set_items(items.get_column_titles())

    @property
    def selected_items(self) -> OrderedDict[Tuple[int, ...], List[int]]:
        """Get the selected items."""
        if self._items is not None and self._items.is_view_selection_suspended():
            return self._fake_selected_items
        else:
            selected_items: OrderedDict[Tuple[int, ...], List[int]] = OrderedDict({})
            if self._model is not None:
                for index in self.table.selectedIndexes():
                    source_index = self._model.mapToSource(index)
                    row = source_index.row()
                    column = source_index.column()
                    selected_items.setdefault((row,), []).append(column)
            return selected_items

    @selected_items.setter
    def selected_items(self, items: OrderedDict[Tuple[int, ...], List[int]]) -> None:
        """Set the selected items."""
        if self._items is not None and self._items.is_view_selection_suspended():
            self._fake_selected_items = OrderedDict(items)
        elif self._model is not None:
            selection_model = self.table.selectionModel()
            selection_model.clearSelection()
            if len(items) == 0:
                selection_model.selectionChanged.emit(QItemSelection(), QItemSelection())
            item_selection = self._model.generate_item_selection(items)
            selection_model.select(item_selection, QItemSelectionModel.Select)
            self.table.setFocus()

    @Slot(QModelIndex)
    def _check_selection(self, index: QModelIndex) -> None:
        r"""Check the item at the given index."""
        if index.isValid() and self.items is not None and self._model is not None:
            source_index = self._model.mapToSource(index)
            # the call to internalPointer need to be done before the call to edit_model
            # because the internals are invalidated by beginResetModel
            row = source_index.row()
            column = source_index.column()
            self._model.beginResetModel()
            self.items.set_checked(row, column, not self.items.is_checked(row, column))
            self._model.endResetModel()
            self.selected_items = OrderedDict({(row,): [column]})

    def _set_delegates(self) -> None:
        r"""Set the delegates in the view."""
        if self._items is not None:
            set_delegates(self.table, self._items)


class _TableView(QTableView):
    r"""Table view with a signal emitted when an item is edited."""

    item_edited = Signal()
    view_visible = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.context_menu_position: Tuple[int, int] = (0, 0)
        self.context_menu_selection: Tuple[Tuple[int, ...], int] = ((), 0)
        self.customContextMenuRequested.connect(self._store_context_menu_infos)

    def closeEditor(  # noqa: N802
        self, editor: QWidget, hint: QAbstractItemDelegate.EndEditHint
    ) -> None:
        r"""Close the given editor and releases it."""
        super().closeEditor(editor, hint)
        self.item_edited.emit()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Emit a signal when the widget is visible."""
        self.view_visible.emit()
        super().showEvent(event)

    @Slot(QPoint)
    def _store_context_menu_infos(self, position: QPoint) -> None:
        r"""Store the position where the context menu is requested."""
        global_position = self.mapToGlobal(position)
        self.context_menu_position = (global_position.x(), global_position.y())
        proxy_index = self.indexAt(position)
        model = self.model()
        if isinstance(model, TreeItemModel):
            index = model.mapToSource(proxy_index)
            rows = index.internalPointer()
            column = index.column()
            self.context_menu_selection = (rows, column)
