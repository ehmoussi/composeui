r"""Items widget."""

from composeui.items.core.itemsutils import (
    ComboBoxDelegateProps,
    FloatDelegateProps,
    IntDelegateProps,
)
from composeui.items.core.qt.qtfiltertableview import QtFilterTableView
from composeui.items.core.qt.qtpaginationview import QtPaginationView
from composeui.items.core.qt.widgets.itemdelegates import ComboBoxDelegate, FloatDelegate
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.tree.abstracttreeitems import AbstractTreeItems

from qtpy.QtCore import Slot  # type: ignore[attr-defined]
from qtpy.QtCore import QModelIndex, QSortFilterProxyModel, Qt
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWhatsThis,
    QWidget,
)
from typing_extensions import OrderedDict, TypeAlias

import typing
from abc import abstractmethod
from typing import Any, List, Optional, Set, Tuple, Union

if typing.TYPE_CHECKING:
    from composeui.items.table.qt.widgets.tablewidget import _TableView
    from composeui.items.tree.qt.widgets.treewidget import _TreeView

Items: TypeAlias = Union[AbstractTableItems[Any], AbstractTreeItems[Any]]


class ItemsWidget(QWidget):
    r"""Item widget."""

    def __init__(
        self,
        table: Union["_TableView", "_TreeView"],
        double_clicked_is_check: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._fake_selected_items: OrderedDict[Tuple[int, ...], List[int]] = OrderedDict()
        # Layout
        self._layout = QVBoxLayout()
        self.setLayout(self._layout)
        # Import/Export buttons
        self.import_export_buttons = QHBoxLayout()
        self.import_export_buttons.addStretch()
        self._layout.addLayout(self.import_export_buttons)
        # - Import button
        self.import_button = QPushButton("Import")
        self.import_button.setIcon(QIcon(":/icons/import.png"))
        self.import_button.setToolTip("Import")
        self.import_export_buttons.addWidget(self.import_button)
        # - Export button
        self.export_button = QPushButton("Export")
        self.export_button.setIcon(QIcon(":/icons/export.png"))
        self.export_button.setToolTip("Export")
        self.import_export_buttons.addWidget(self.export_button)
        # Options buttons
        self.options_buttons = QHBoxLayout()
        self._layout.addLayout(self.options_buttons)
        # - Sort button
        self.sort_button = QPushButton()
        self.sort_button.setIcon(QIcon(":/icons/sort.png"))
        self.sort_button.setToolTip("Sorting")
        self.sort_button.setCheckable(True)
        self.options_buttons.addWidget(self.sort_button)
        # - Filter button
        self.filter_button = QPushButton()
        self.filter_button.setIcon(QIcon(":/icons/filter.png"))
        self.filter_button.setToolTip("Filter")
        self.filter_button.setCheckable(True)
        self.options_buttons.addWidget(self.filter_button)
        # - Check All button
        self.check_all_button = QPushButton()
        self.check_all_button.setIcon(QIcon(":/icons/select_all.png"))
        self.check_all_button.setToolTip("(Un)Check all")
        self.options_buttons.addWidget(self.check_all_button)
        # - Help Button
        self.help_button = QPushButton()
        self.help_button.setIcon(QIcon(":/icons/help.png"))
        self.help_button.setToolTip("Help")
        self.help_button.clicked.connect(self._show_help_text)
        self.help_text = ""
        self.options_buttons.addWidget(self.help_button)
        # - Stretch
        self.options_buttons.addStretch()
        # - Buttons +/-
        self.add_button = QPushButton()
        self.add_button.setIcon(QIcon(":/icons/add.png"))
        self.add_button.setMaximumWidth(40)
        self.add_button.setToolTip("Add")
        self.options_buttons.addWidget(self.add_button)
        self.remove_button = QPushButton()
        self.remove_button.setIcon(QIcon(":/icons/remove.png"))
        self.remove_button.setMaximumWidth(40)
        self.remove_button.setToolTip("Remove")
        self.options_buttons.addWidget(self.remove_button)
        # Filter View
        self.filter_view = QtFilterTableView()
        self._layout.addWidget(self.filter_view.view)
        self.filter_view.view.setVisible(False)
        # Table
        self.table = table
        self.table.setAlternatingRowColors(True)
        if hasattr(self.table, "horizontalHeader"):
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setSelectionBehavior(QTableView.SelectItems)
        self._layout.addWidget(self.table)
        # Pagination
        self.pagination_view = QtPaginationView()
        self.pagination_view.is_visible = False
        self._layout.addWidget(self.pagination_view.view)
        # Connect to slots
        self.sort_button.clicked.connect(self._enable_sorting)
        if double_clicked_is_check:
            self.table.doubleClicked.connect(self._check_selection)

    @Slot()
    def _show_help_text(self) -> None:
        QWhatsThis.showText(
            self.help_button.mapToGlobal(self.help_button.pos()),
            self.help_text,
        )

    @abstractmethod
    def failed_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None:
        r"""Highlight the given index."""
        raise NotImplementedError

    @abstractmethod
    def successful_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None:
        r"""Highlight the given index."""
        raise NotImplementedError

    @abstractmethod
    def update_view(self) -> None:
        r"""Update the table."""
        raise NotImplementedError

    @property
    @abstractmethod
    def selected_items(self) -> OrderedDict[Tuple[int, ...], List[int]]:
        """Get the selected items."""
        raise NotImplementedError

    @selected_items.setter
    @abstractmethod
    def selected_items(self, items: OrderedDict[Tuple[int, ...], List[int]]) -> None:
        """Set the selected items."""
        raise NotImplementedError

    @Slot(bool)
    def _enable_sorting(self, is_enabled: bool) -> None:
        r"""Enable the sorting of the table."""
        model = self.table.model()
        if isinstance(model, QSortFilterProxyModel):
            if is_enabled:
                self.table.setSortingEnabled(True)
                model.setSortRole(Qt.EditRole)
            else:
                model.sort(-1)
                model.beginResetModel()
                model.endResetModel()
                self.table.setSortingEnabled(False)

    @abstractmethod
    @Slot(QModelIndex)
    def _check_selection(self, index: QModelIndex) -> None:
        r"""Check the item at the given index."""
        raise NotImplementedError


def set_delegates(
    table: Union["_TableView", "_TreeView"],
    items: Union[AbstractTableItems[Any], AbstractTreeItems[Any]],
) -> None:
    for j in range(items.get_nb_columns()):
        delegate_type = items.get_delegate_props(0, j)
        if isinstance(delegate_type, ComboBoxDelegateProps):
            table.setItemDelegateForColumn(j, ComboBoxDelegate(items, table))
        elif isinstance(delegate_type, FloatDelegateProps):
            table.setItemDelegateForColumn(j, FloatDelegate(items, table))
        elif isinstance(delegate_type, IntDelegateProps):
            pass
            # TODO: Implement IntDelegate
            # self.table.setItemDelegateForColumn(
            #     j, IntDelegate(items, j, self.table)
            # )
