r"""Items view."""

from composeui.core.pendingupdate import pending_until_visible
from composeui.core.qt.qtgroupview import QtGroupView
from composeui.core.qt.qtview import QtView
from composeui.items.core.qt.qtfiltertableview import QtFilterTableView
from composeui.items.core.qt.qtpaginationview import QtPaginationView
from composeui.items.core.qt.widgets.itemswidget import ItemsWidget
from composeui.items.core.views.itemsview import ItemsView

from qtpy.QtCore import Qt
from qtpy.QtGui import QKeySequence
from qtpy.QtWidgets import QAbstractItemView, QGroupBox, QShortcut, QVBoxLayout
from typing_extensions import OrderedDict

from dataclasses import dataclass, field
from typing import List, Set, Tuple


@dataclass(eq=False)
class QtItemsView(QtView, ItemsView):
    r"""Items view."""

    table_widget: ItemsWidget = field(init=False)
    filter_view: QtFilterTableView = field(init=False)
    pagination_view: QtPaginationView = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        # Table
        self.table = self.table_widget.table
        self.filter_view = self.table_widget.filter_view
        self.pagination_view = self.table_widget.pagination_view
        self.table_widget.check_all_button.setVisible(False)
        self.table_widget.filter_button.setVisible(False)
        self.table_widget.filter_view.view.setVisible(False)
        self.table_widget.import_button.setVisible(False)
        self.table_widget.export_button.setVisible(False)
        self.table_widget.add_button.setVisible(False)
        self.table_widget.remove_button.setVisible(False)
        # shortcuts
        self._add_shortcut = QShortcut(QKeySequence("Ctrl+Alt+N"), self.table)
        self._delete_shortcut = QShortcut(QKeySequence.Delete, self.table)
        self._clear_shortcut = QShortcut(QKeySequence("Ctrl+Delete"), self.table)
        self._copy_shortcut = QShortcut(QKeySequence.Copy, self.table)
        self._paste_shortcut = QShortcut(QKeySequence.Paste, self.table)
        # assign the signals
        self.clicked.add_qt_signals((self.table, self.table.clicked))
        self.double_clicked.add_qt_signals((self.table, self.table.doubleClicked))
        self.item_edited.add_qt_signals((self.table, self.table.item_edited))
        self.context_menu_requested.add_qt_signals(
            (self.table, self.table.customContextMenuRequested)
        )
        self.shortcut_add.add_qt_signals((self._add_shortcut, self._add_shortcut.activated))
        self.shortcut_delete.add_qt_signals(
            (self._delete_shortcut, self._delete_shortcut.activated)
        )
        self.shortcut_clear.add_qt_signals(
            (self._clear_shortcut, self._clear_shortcut.activated)
        )
        self.shortcut_copy.add_qt_signals((self._copy_shortcut, self._copy_shortcut.activated))
        self.shortcut_paste.add_qt_signals(
            (self._paste_shortcut, self._paste_shortcut.activated)
        )
        self.check_all.add_qt_signals(
            (self.table_widget.check_all_button, self.table_widget.check_all_button.clicked)
        )
        self.filter_changed.add_qt_signals(
            (self.table_widget.filter_button, self.table_widget.filter_button.clicked)
        )
        self.import_clicked.add_qt_signals(
            (self.table_widget.import_button, self.table_widget.import_button.clicked)
        )
        self.export_clicked.add_qt_signals(
            (self.table_widget.export_button, self.table_widget.export_button.clicked)
        )
        self.add_clicked.add_qt_signals(
            (self.table_widget.add_button, self.table_widget.add_button.clicked)
        )
        self.remove_clicked.add_qt_signals(
            (self.table_widget.remove_button, self.table_widget.remove_button.clicked)
        )
        # connect to an internal slot to manage the pending of the update
        self.table.view_visible.connect(self._update_if_pending)

    def _update_if_pending(self) -> None:
        r"""Update the table if an update is pending."""
        if self.is_update_pending:
            self.update()

    @pending_until_visible
    def update(self) -> None:
        r"""Update the table."""
        self.table_widget.update_view()

    @property  # type: ignore[misc]
    def has_import(self) -> bool:
        return self.table_widget.import_button.isVisible()

    @has_import.setter
    def has_import(self, has_import: bool) -> None:
        self.table_widget.import_button.setVisible(has_import)

    @property  # type: ignore[misc]
    def has_export(self) -> bool:
        return self.table_widget.export_button.isVisible()

    @has_export.setter
    def has_export(self, has_export: bool) -> None:
        self.table_widget.export_button.setVisible(has_export)

    @property  # type: ignore[misc]
    def has_add(self) -> bool:
        return self.table_widget.add_button.isVisible()

    @has_add.setter
    def has_add(self, has_add: bool) -> None:
        self.table_widget.add_button.setVisible(has_add)

    @property  # type: ignore[misc]
    def has_remove(self) -> bool:
        return self.table_widget.remove_button.isVisible()

    @has_remove.setter
    def has_remove(self, has_remove: bool) -> None:
        self.table_widget.remove_button.setVisible(has_remove)

    @property  # type: ignore[misc]
    def has_pagination(self) -> bool:
        return self.table_widget.pagination_view.is_visible

    @has_pagination.setter
    def has_pagination(self, has_pagination: bool) -> None:
        self.table_widget.pagination_view.is_visible = has_pagination

    @property  # type: ignore[misc]
    def selected_items(self) -> OrderedDict[Tuple[int, ...], List[int]]:
        return self.table_widget.selected_items

    @selected_items.setter
    def selected_items(self, selected_items: OrderedDict[Tuple[int, ...], List[int]]) -> None:
        # The use of default_factory make the call of this setter
        # before the initialization of table_widget.
        if hasattr(self, "table_widget"):
            self.table_widget.selected_items = selected_items

    @property  # type: ignore[misc]
    def is_single_selection(self) -> bool:
        return bool(self.table.selectionMode() == QAbstractItemView.SingleSelection)

    @is_single_selection.setter
    def is_single_selection(self, is_single_selection: bool) -> None:
        if is_single_selection:
            self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        else:
            self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

    @property  # type: ignore[misc]
    def can_select_items(self) -> bool:
        return bool(self.table.selectionBehavior() == QAbstractItemView.SelectItems)

    @can_select_items.setter
    def can_select_items(self, can_select_items: bool) -> None:
        if can_select_items:
            self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        else:
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)

    @property  # type: ignore[misc]
    def has_focus(self) -> bool:
        return self.table.hasFocus()

    @has_focus.setter
    def has_focus(self, has_focus: bool) -> None:
        if has_focus:
            self.table.setFocus()
        else:
            self.table.clearFocus()

    @property  # type: ignore[misc]
    def has_check_all(self) -> bool:
        return bool(self.table_widget.check_all_button.isVisible())

    @has_check_all.setter
    def has_check_all(self, has_check_all: bool) -> None:
        self.table_widget.check_all_button.setVisible(has_check_all)

    @property  # type: ignore[misc]
    def sorting_enabled(self) -> bool:
        return bool(self.table_widget.sort_button.isChecked())

    @sorting_enabled.setter
    def sorting_enabled(self, sorting_enabled: bool) -> None:
        self.table_widget.sort_button.setChecked(sorting_enabled)

    @property  # type: ignore[misc]
    def is_filtered(self) -> bool:
        return bool(self.table_widget.filter_button.isChecked())

    @is_filtered.setter
    def is_filtered(self, is_filtered: bool) -> None:
        self.table_widget.filter_button.setChecked(is_filtered)

    @property  # type: ignore[misc]
    def help_text(self) -> str:
        return self.table_widget.help_text

    @help_text.setter
    def help_text(self, text: str) -> None:
        self.table_widget.help_text = text

    @property  # type: ignore[misc]
    def drag_drop_enabled(self) -> bool:
        return bool(self.table.dragEnabled() and self.table.acceptDrops())

    @drag_drop_enabled.setter
    def drag_drop_enabled(self, is_enabled: bool) -> None:
        self.table.setDragEnabled(is_enabled)
        self.table.setAcceptDrops(is_enabled)

    @property  # type: ignore[misc]
    def has_context_menu(self) -> bool:
        return bool(self.table.contextMenuPolicy() == Qt.CustomContextMenu)

    @has_context_menu.setter
    def has_context_menu(self, has_context_menu: bool) -> None:
        if has_context_menu:
            self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        else:
            self.table.setContextMenuPolicy(Qt.DefaultContextMenu)

    @property
    def context_menu_selection(self) -> Tuple[Tuple[int, ...], int]:
        return self.table.context_menu_selection

    @property
    def context_menu_position(self) -> Tuple[int, int]:
        return self.table.context_menu_position

    def failed_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None:
        self.table_widget.failed_highlight(items)

    def successful_highlight(self, items: Set[Tuple[int, Tuple[int, ...], int]]) -> None:
        self.table_widget.successful_highlight(items)


@dataclass(eq=False)
class QtItemsGroupView(QtItemsView, QtGroupView):
    r"""ItemsView inside a groupbox."""

    view: QGroupBox = field(init=False)

    def __post_init__(self) -> None:
        self.view = QGroupBox()
        super().__post_init__()
        self.layout = QVBoxLayout()
        self.layout.addWidget(self.table_widget)
        self.view.setLayout(self.layout)
