r"""Items widget."""

from composeui.items.core.qt.widgets.itemswidget import ItemsWidget, set_delegates
from composeui.items.tree.abstracttreeitems import AbstractTreeItems
from composeui.items.tree.qt.treeitemmodel import TreeItemModel

from qtpy.QtCore import Signal  # type: ignore[attr-defined]
from qtpy.QtCore import Slot  # type: ignore[attr-defined]
from qtpy.QtCore import QItemSelection, QItemSelectionModel, QModelIndex, QPoint, Qt
from qtpy.QtGui import QIcon, QShowEvent
from qtpy.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QPushButton,
    QTreeView,
    QWidget,
)
from typing_extensions import OrderedDict

from contextlib import contextmanager
from typing import Any, Generator, List, Optional, Set, Tuple


class TreeWidget(ItemsWidget):
    r"""Tree widget."""

    def __init__(
        self, double_clicked_is_check: bool = False, parent: Optional[QWidget] = None
    ) -> None:
        # Model/Items
        self._model: Optional[TreeItemModel] = None
        super().__init__(_TreeView(), double_clicked_is_check, parent)
        self.table: _TreeView
        self._items: Optional[AbstractTreeItems[Any]] = None
        # - expand button
        self.expand_button = QPushButton()
        self.expand_button.setIcon(QIcon(":/icons/expand.png"))
        self.expand_button.setToolTip("Expand All")
        self.options_buttons.insertWidget(1, self.expand_button)
        # - collapse button
        self.collapse_button = QPushButton()
        self.collapse_button.setIcon(QIcon(":/icons/collapse.png"))
        self.collapse_button.setToolTip("Collapse All")
        self.options_buttons.insertWidget(2, self.collapse_button)
        # Table
        self.table.setEditTriggers(
            self.table.editTriggers() | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        # Connect to slots
        self.expand_button.clicked.connect(self.table.expandAll)
        self.collapse_button.clicked.connect(self.table.collapseAll)

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
        if self._items is None:
            raise ValueError("The items of the table is not defined.")
        if self._model is not None:
            self.pagination_view.view.size_changed.emit()
            self._model.beginResetModel()
            self._model.endResetModel()

    @contextmanager
    def edit_tree_model(self) -> Generator[Optional[TreeItemModel], None, None]:
        """Edit the model."""
        if self._model is None:
            yield None
        else:
            self._model.beginResetModel()
            try:
                yield self._model
            finally:
                self._model.endResetModel()

    @property
    def items(self) -> Optional[AbstractTreeItems[Any]]:
        """Get the items."""
        return self._items

    @items.setter
    def items(self, items: AbstractTreeItems[Any]) -> None:
        """Set the items."""
        self._set_items(items)

    def _set_items(self, items: AbstractTreeItems[Any]) -> None:
        """Set the items."""
        self._items = items
        self._model = TreeItemModel(items)
        self.table.setModel(self._model)
        self._set_delegates()
        self.filter_view.columns_selector.set_items(items.get_column_titles())
        if self._model is not None:
            self._model.modelReset.connect(self.table.update_expansion_status)

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
                    rows = source_index.internalPointer()
                    column = source_index.column()
                    selected_items.setdefault(rows, []).append(column)
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

    @Slot(bool)
    def _enable_sorting(self, is_enabled: bool) -> None:
        r"""Enable the sorting of the table."""
        model = self.table.model()
        if isinstance(model, TreeItemModel):
            if is_enabled:
                self.table.setSortingEnabled(True)
                model.setSortRole(Qt.EditRole)
            else:
                model.sort(-1)
                model.beginResetModel()
                model.endResetModel()
                self.table.setSortingEnabled(False)

    @Slot(QModelIndex)
    def _check_selection(self, index: QModelIndex) -> None:
        r"""Check the item at the given index."""
        if index.isValid() and self.items is not None and self._model is not None:
            source_index = self._model.mapToSource(index)
            # the call to internalPointer need to be done before the call to edit_model
            # because the internals are invalidated by beginResetModel
            *parent_rows, row = source_index.internalPointer()
            column = source_index.column()
            with self.edit_tree_model():
                self.items.set_checked(
                    row,
                    column,
                    not self.items.is_checked(row, column, parent_rows),
                    parent_rows,
                )
            self.selected_items = OrderedDict({(*parent_rows, row): [column]})
            self.table.update_expansion_status()

    def _set_delegates(self) -> None:
        r"""Set the delegates in the view."""
        if self._items is not None:
            set_delegates(self.table, self._items)


class _TreeView(QTreeView):
    r"""Tree view with a signal emitted when an item is edited."""

    item_edited = Signal()
    view_visible = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.context_menu_position: Tuple[int, int] = (0, 0)
        self.context_menu_selection: Tuple[Tuple[int, ...], int] = ((), 0)
        self.expanded.connect(self._item_expanded)
        self.collapsed.connect(self._item_collapsed)
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

    @Slot()
    def update_expansion_status(self) -> None:
        r"""Update the expansion status."""
        model = self.model()
        if isinstance(model, TreeItemModel):
            items = model.source_model.items
            for position in sorted(items.get_expand_positions(), key=lambda p: len(p)):
                index = QModelIndex()
                for row in reversed(position):
                    index = model.index(row, 0, index)
                # while len(position) > 0:
                #     row = position[-1]
                #     index = model.index(row, 0, index)
                #     position = position[:-1]
                self.expand(index)

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

    @Slot(QModelIndex)
    def _item_expanded(self, index: QModelIndex) -> None:
        r"""Set the given index as expanded."""
        model = self.model()
        if isinstance(model, TreeItemModel):
            rows = model.mapToSource(index).internalPointer()
            model.source_model.items.set_expanded(rows[-1], True, rows[:-1])

    @Slot(QModelIndex)
    def _item_collapsed(self, index: QModelIndex) -> None:
        r"""Set the given index as collapsed."""
        model = self.model()
        if isinstance(model, TreeItemModel):
            rows = model.mapToSource(index).internalPointer()
            model.source_model.items.set_expanded(rows[-1], False, rows[:-1])
