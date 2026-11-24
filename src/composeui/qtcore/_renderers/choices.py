"""Qt renderers for choices and trees."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, cast

from qtpy.QtCore import Qt
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem, QWidget
from typing_extensions import Protocol, override

from composeui.core._views.choices import walk_tree
from composeui.core.renderer import ViewLike
from composeui.core.view import NodeMark, TreeView
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qchecklist import QCheckList, QMultiComboBox
from composeui.qtcore.widgets.qmarkicon import mark_icon
from composeui.qtcore.widgets.qplaintext import plain_tool_tip
from composeui.qtcore.widgets.qradiogroup import QRadioGroup
from composeui.qtcore.widgets.qvaluecombobox import QValueComboBox

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from composeui.core._views.choices import ChoicesShown
    from composeui.core.signal import Signal
    from composeui.core.view import TreeNode, TreePath


TValue = TypeVar("TValue")


class ValuesViewLike(ViewLike, Protocol, Generic[TValue]):
    value: TValue | None
    values: dict[str, TValue]
    value_changed: Signal[TValue | None]


class QtRadioGroupRenderer(QtWidgetRenderer[ValuesViewLike[TValue], QRadioGroup], Generic[TValue]):
    _invalid_style = "QRadioButton { color: red; }"

    def __init__(self, view: ValuesViewLike[TValue]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "values": self._refresh_values,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QRadioGroup(self._view.values)
            self._connect(
                self._rendered_object.value_changed,
                self._update_value,
                self._view.value_changed.call_callbacks,
            )
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: ValuesViewLike[TValue], rendered_object: QRadioGroup, value: Any
    ) -> None:
        rendered_object.set_value(value)

    @staticmethod
    def _refresh_values(
        view: ValuesViewLike[TValue], rendered_object: QRadioGroup, values: dict[str, Any]
    ) -> None:
        # rebuilding leaves nothing checked, even if `view.value` didn't itself change
        # (and so wouldn't otherwise trigger its own refresh) - reapply it explicitly
        rendered_object.set_values(values)
        rendered_object.set_value(view.value)

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value


class QtComboBoxRenderer(
    QtWidgetRenderer[ValuesViewLike[TValue], QValueComboBox[TValue]], Generic[TValue]
):
    _invalid_style = "QComboBox { border: 1px solid red; }"

    def __init__(self, view: ValuesViewLike[TValue]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "values": self._refresh_values,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QValueComboBox(self._view.values)
            self._connect(
                self._rendered_object.current_value_changed,
                self._update_value,
                self._view.value_changed.call_callbacks,
            )
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: ValuesViewLike[TValue], rendered_object: QValueComboBox[TValue], value: TValue
    ) -> None:
        rendered_object.set_current_value(value)

    @staticmethod
    def _refresh_values(
        view: ValuesViewLike[TValue],
        rendered_object: QValueComboBox[TValue],
        values: dict[str, TValue],
    ) -> None:
        rendered_object.set_values(values)
        rendered_object.set_current_value(view.value)

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value


class MultiValuesViewLike(ViewLike, Protocol):
    selected: list[Any]
    has_search: bool
    search: str
    has_check_all: bool
    check_all_text: str
    search_text: str
    selected_changed: Signal[list[Any]]

    @property
    def shown(self) -> ChoicesShown: ...

    def shown_once(self, name: str, value: Any) -> ChoicesShown: ...

    def select_keys(self, keys: Mapping[str, bool]) -> bool: ...

    def check_all(self, *, is_checked: bool) -> bool: ...


TChoicesWidget = TypeVar("TChoicesWidget", bound=QWidget)


class _QtChoicesRenderer(
    QtWidgetRenderer[MultiValuesViewLike, TChoicesWidget], Generic[TChoicesWidget]
):
    """A choice of several values: a `QCheckList`, alone or in a drop-down list."""

    #: the attributes that change what `_show` shows
    _shown_attributes: ClassVar[tuple[str, ...]] = (
        "values",
        "selected",
        "search",
        "check_all_text",
    )

    def __init__(self, view: MultiValuesViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                **{name: self._shown_refresher(name) for name in self._shown_attributes},
                "has_search": self._refresh_has_search,
                "has_check_all": self._refresh_has_check_all,
                "search_text": self._refresh_search_text,
            }
        )

    @staticmethod
    def _check_list(widget: TChoicesWidget) -> QCheckList:
        return cast("QCheckList", widget)

    def _make_widget(self) -> TChoicesWidget:
        return cast("TChoicesWidget", QCheckList())

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = self._make_widget()
            check_list = self._check_list(self._rendered_object)
            self._connect(check_list.toggled, self._toggle)
            self._connect(check_list.all_clicked, self._check_all)
            self._connect(check_list.searched, self._search)
            self.refresh()

    def _show(self, widget: TChoicesWidget, shown: ChoicesShown) -> None:
        self._check_list(widget).show_choices(shown)

    def _shown_refresher(
        self, name: str
    ) -> Callable[[MultiValuesViewLike, TChoicesWidget, Any], None]:
        def refresh(view: MultiValuesViewLike, widget: TChoicesWidget, value: Any) -> None:
            if name == "search":
                self._check_list(widget).set_search(value)
            elif name == "check_all_text":
                self._check_list(widget).check_all.setText(value)
            self._show(widget, view.shown_once(name, value))

        return refresh

    def _refresh_has_search(
        self, _view: MultiValuesViewLike, widget: TChoicesWidget, value: bool
    ) -> None:
        self._check_list(widget).search_field.setVisible(value)

    def _refresh_has_check_all(
        self, _view: MultiValuesViewLike, widget: TChoicesWidget, value: bool
    ) -> None:
        self._check_list(widget).check_all.setVisible(value)

    def _refresh_search_text(
        self, _view: MultiValuesViewLike, widget: TChoicesWidget, value: str
    ) -> None:
        self._check_list(widget).search_field.setPlaceholderText(value)

    def _after_user_change(self, *, is_changed: bool) -> None:
        """Show the view as the user left it, and tell if the choice changed."""
        # only the widget's own signals call it
        self._show(cast("TChoicesWidget", self._rendered_object), self._view.shown)
        if is_changed:
            self._view.selected_changed.emit(self._view.selected)

    def _toggle(self, key: str, is_checked: bool) -> None:
        with self.stop_refresh():
            is_changed = self._view.select_keys({key: is_checked})
        self._after_user_change(is_changed=is_changed)

    def _check_all(self, is_checked: bool) -> None:
        # the box's state as the user saw it change, partly checked to checked
        with self.stop_refresh():
            is_changed = self._view.check_all(is_checked=is_checked)
        self._after_user_change(is_changed=is_changed)

    def _search(self, text: str) -> None:
        with self.stop_refresh():
            self._view.search = text
        self._after_user_change(is_changed=False)


class QtCheckListRenderer(_QtChoicesRenderer[QCheckList]):
    """A list of check boxes, with a search field and a check-all box."""

    _invalid_style = "QListWidget { border: 1px solid red; }"


class QtMultiComboBoxRenderer(_QtChoicesRenderer[QMultiComboBox]):
    """A drop-down list of check boxes: a button showing the choice, its menu the list."""

    _invalid_style = "QPushButton { border: 1px solid red; }"
    _shown_attributes = (*_QtChoicesRenderer._shown_attributes, "empty_text", "count_text")  # noqa: SLF001 (the base renderer's attributes)

    @override
    @staticmethod
    def _check_list(widget: QMultiComboBox) -> QCheckList:
        return widget.check_list

    @override
    def _make_widget(self) -> QMultiComboBox:
        return QMultiComboBox()

    @override
    def _show(self, widget: QMultiComboBox, shown: ChoicesShown) -> None:
        widget.check_list.show_choices(shown)
        widget.setText(shown.summary)


class QtTreeRenderer(QtWidgetRenderer[TreeView, QTreeWidget]):
    """A tree widget without a header, each item holding its node's path.

    Its first column shows a node's icon and label, its second the node's mark, hidden
    while no node has one. The user selects one item at most: a Ctrl+click deselecting
    it selects it again, as the view always keeps the node the user selected.
    """

    def __init__(self, view: TreeView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "nodes": self._refresh_nodes,
                "expanded": self._refresh_expanded,
                "selected": self._refresh_selected,
                "done_text": functools.partial(self._refresh_mark_text, NodeMark.DONE),
                "warning_text": functools.partial(self._refresh_mark_text, NodeMark.WARNING),
                "error_text": functools.partial(self._refresh_mark_text, NodeMark.ERROR),
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QTreeWidget()
            self._rendered_object.setHeaderHidden(True)
            self._rendered_object.setColumnCount(2)
            header = self._rendered_object.header()
            assert header is not None
            # the marks as narrow as their icon, at the right
            header.setStretchLastSection(False)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            self._rendered_object.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
            self._connect(self._rendered_object.itemSelectionChanged, self._update_selected)
            self._rendered_object.itemExpanded.connect(
                lambda item: self._update_expanded(item, is_expanded=True)
            )
            self._rendered_object.itemCollapsed.connect(
                lambda item: self._update_expanded(item, is_expanded=False)
            )
            self.refresh()

    @classmethod
    def _refresh_nodes(
        cls, view: TreeView, rendered_object: QTreeWidget, value: list[TreeNode]
    ) -> None:
        rendered_object.clear()

        def add(
            parent: QTreeWidget | QTreeWidgetItem, nodes: Iterable[TreeNode], path: TreePath
        ) -> None:
            for node in nodes:
                item = QTreeWidgetItem(parent, [node.label])
                item.setData(0, Qt.ItemDataRole.UserRole, [*path, node.key])
                if node.icon is not None:
                    item.setIcon(0, QIcon(node.icon))
                font = item.font(0)
                font.setBold(node.is_bold)
                font.setUnderline(node.is_underlined)
                item.setFont(0, font)
                if node.mark is not None:
                    item.setIcon(1, mark_icon(node.mark))
                    item.setToolTip(1, plain_tool_tip(view.mark_text(node.mark)))
                add(item, node.children, (*path, node.key))

        add(rendered_object, value, ())
        rendered_object.setColumnHidden(1, all(node.mark is None for _, node in walk_tree(value)))
        # the view's, already kept to those still in the nodes
        cls._refresh_expanded(view, rendered_object, view.expanded)
        cls._refresh_selected(view, rendered_object, view.selected)

    @staticmethod
    def _refresh_expanded(
        _view: TreeView, rendered_object: QTreeWidget, value: list[TreePath]
    ) -> None:
        expanded = set(value)
        for path, item in _tree_items(rendered_object):
            item.setExpanded(path in expanded)

    @staticmethod
    def _refresh_selected(
        _view: TreeView, rendered_object: QTreeWidget, value: TreePath | None
    ) -> None:
        rendered_object.clearSelection()
        for path, item in _tree_items(rendered_object):
            if path == value:
                rendered_object.setCurrentItem(item)
                item.setSelected(True)

    @staticmethod
    def _refresh_mark_text(
        mark: NodeMark, view: TreeView, rendered_object: QTreeWidget, value: str
    ) -> None:
        for path, item in _tree_items(rendered_object):
            if view.node(path).mark is mark:
                item.setToolTip(1, plain_tool_tip(value))

    def _update_selected(self) -> None:
        assert self._rendered_object is not None
        selected = self._rendered_object.selectedItems()
        if len(selected) == 0:
            self.refresh_attribute("selected", self._view.selected)
            return
        path = _tree_path(selected[0])
        if path == self._view.selected:
            # Qt reports a change only: kept against a second `selection_changed`
            return  # pragma: no cover
        with self.stop_refresh():
            self._view.selected = path
        self._view.selection_changed.emit(path)

    def _update_expanded(self, item: QTreeWidgetItem, *, is_expanded: bool) -> None:
        path = _tree_path(item)
        with self.stop_refresh():
            self._view.expanded = self._view.expanded_with(path, is_expanded=is_expanded)
        self._view.toggled.emit(path, is_expanded)


def _tree_path(item: QTreeWidgetItem) -> TreePath:
    return tuple(item.data(0, Qt.ItemDataRole.UserRole))


def _tree_items(tree: QTreeWidget) -> list[tuple[TreePath, QTreeWidgetItem]]:
    """Get the tree's items with their nodes' paths, depth first."""
    items: list[tuple[TreePath, QTreeWidgetItem]] = []

    def add(item: QTreeWidgetItem) -> None:
        items.append((_tree_path(item), item))
        for index in range(item.childCount()):
            child = item.child(index)
            assert child is not None
            add(child)

    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        assert item is not None
        add(item)
    return items
