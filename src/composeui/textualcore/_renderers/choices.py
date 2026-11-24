"""Textual choices and trees."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, cast

from textual.content import Content
from typing_extensions import Protocol, override

from composeui.core.renderer import ViewLike
from composeui.core.view import TreeView
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composechecklist import ComposeCheckList, ComposeMultiComboBox
from composeui.textualcore.widgets.composecombobox import ComposeComboBox
from composeui.textualcore.widgets.composeradioset import ComposeRadioSet
from composeui.textualcore.widgets.composetree import ComposeTree

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from textual.widget import Widget

    from composeui.core._views.choices import ChoicesShown
    from composeui.core.signal import Signal
    from composeui.core.view import TreeNode, TreePath


TValue = TypeVar("TValue")


class ValuesViewLike(ViewLike, Protocol, Generic[TValue]):
    value: TValue | None
    values: dict[str, TValue]
    value_changed: Signal[TValue | None]


class TextualRadioGroupRenderer(
    TextualWidgetRenderer[ValuesViewLike[TValue], ComposeRadioSet[TValue]], Generic[TValue]
):
    _marks_invalid = True

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
            self._rendered_object = ComposeRadioSet(self._view.values)
            self._rendered_object.value_changed.connect(self._update_value)

    @staticmethod
    def _refresh_value(
        _view: ValuesViewLike[TValue], rendered_object: ComposeRadioSet[TValue], value: Any
    ) -> None:
        # `set_values`'s rebuild (remove_children/mount) is asynchronous; selecting
        # synchronously right after races with it and corrupts RadioSet's own
        # bookkeeping (see `_refresh_values`) - defer until the rebuild has landed.
        rendered_object.call_after_refresh(rendered_object.set_value, value)

    @staticmethod
    def _refresh_values(
        view: ValuesViewLike[TValue],
        rendered_object: ComposeRadioSet[TValue],
        values: dict[str, Any],
    ) -> None:
        # rebuilding leaves nothing selected, even if `view.value` didn't itself change
        # (and so wouldn't otherwise trigger its own refresh) - reapply it explicitly
        rendered_object.set_values(values)
        rendered_object.call_after_refresh(rendered_object.set_value, view.value)

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


class TextualComboBoxRenderer(
    TextualWidgetRenderer[ValuesViewLike[TValue], ComposeComboBox[TValue]], Generic[TValue]
):
    _marks_invalid = True

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
            self._rendered_object = ComposeComboBox(self._view.values)
            self._rendered_object.value_changed.connect(self._update_value)

    @staticmethod
    def _refresh_value(
        _view: ValuesViewLike[TValue], rendered_object: ComposeComboBox[TValue], value: Any
    ) -> None:
        rendered_object.call_after_refresh(rendered_object.set_value, value)

    @staticmethod
    def _refresh_values(
        view: ValuesViewLike[TValue],
        rendered_object: ComposeComboBox[TValue],
        values: dict[str, Any],
    ) -> None:
        rendered_object.set_values(values)
        rendered_object.call_after_refresh(rendered_object.set_value, view.value)

    def _update_value(self, value: TValue | None) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


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


TChoicesWidget = TypeVar("TChoicesWidget", bound="Widget")


class _TextualChoicesRenderer(
    TextualWidgetRenderer[MultiValuesViewLike, TChoicesWidget], Generic[TChoicesWidget]
):
    """A choice of several values: a `ComposeCheckList`, alone or in a drop-down list."""

    _marks_invalid = True

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

    #: the attributes that change what `_show` shows
    _shown_attributes: ClassVar[tuple[str, ...]] = (
        "values",
        "selected",
        "search",
        "check_all_text",
    )

    @staticmethod
    def _check_list(widget: TChoicesWidget) -> ComposeCheckList:
        return cast("ComposeCheckList", widget)

    def _make_widget(self) -> TChoicesWidget:
        return cast("TChoicesWidget", ComposeCheckList())

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = self._make_widget()
            check_list = self._check_list(self._rendered_object)
            check_list.toggled.connect(self._toggle)
            check_list.all_clicked.connect(self._check_all)
            check_list.searched.connect(self._search)

    def _show(self, widget: TChoicesWidget, shown: ChoicesShown) -> None:
        self._check_list(widget).show(shown)

    def _shown_refresher(
        self, name: str
    ) -> Callable[[MultiValuesViewLike, TChoicesWidget, Any], None]:
        def refresh(view: MultiValuesViewLike, widget: TChoicesWidget, value: Any) -> None:
            if name == "search":
                self._check_list(widget).set_search(value)
            elif name == "check_all_text":
                self._check_list(widget).check_all.label = Content(value)
            self._show(widget, view.shown_once(name, value))

        return refresh

    def _refresh_has_search(
        self, _view: MultiValuesViewLike, widget: TChoicesWidget, value: bool
    ) -> None:
        self._check_list(widget).search_input.display = value

    def _refresh_has_check_all(
        self, _view: MultiValuesViewLike, widget: TChoicesWidget, value: bool
    ) -> None:
        self._check_list(widget).check_all.display = value

    def _refresh_search_text(
        self, _view: MultiValuesViewLike, widget: TChoicesWidget, value: str
    ) -> None:
        self._check_list(widget).search_input.placeholder = value

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
        # the box's state as the user saw it change, partly checked (unchecked) to checked
        with self.stop_refresh():
            is_changed = self._view.check_all(is_checked=is_checked)
        self._after_user_change(is_changed=is_changed)

    def _search(self, text: str) -> None:
        with self.stop_refresh():
            self._view.search = text
        self._after_user_change(is_changed=False)


class TextualCheckListRenderer(_TextualChoicesRenderer[ComposeCheckList]):
    """A list of check boxes, with a search field and a check-all box."""


class TextualMultiComboBoxRenderer(_TextualChoicesRenderer[ComposeMultiComboBox]):
    """A drop-down list of check boxes: a collapsible titled with the choice's summary."""

    _shown_attributes = (
        *_TextualChoicesRenderer._shown_attributes,  # noqa: SLF001 (the base renderer's attributes)
        "empty_text",
        "count_text",
    )

    @override
    @staticmethod
    def _check_list(widget: ComposeMultiComboBox) -> ComposeCheckList:
        return widget.check_list

    @override
    def _make_widget(self) -> ComposeMultiComboBox:
        return ComposeMultiComboBox()

    @override
    def _show(self, widget: ComposeMultiComboBox, shown: ChoicesShown) -> None:
        widget.check_list.show(shown)
        widget.title = shown.summary


class TextualTreeRenderer(TextualWidgetRenderer[TreeView, ComposeTree]):
    def __init__(self, view: TreeView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "nodes": self._refresh_nodes,
                "expanded": self._refresh_expanded,
                "selected": self._refresh_selected,
                # a terminal shows the marks' glyphs, not their names
                "done_text": lambda _view, _rendered_object, _value: None,
                "warning_text": lambda _view, _rendered_object, _value: None,
                "error_text": lambda _view, _rendered_object, _value: None,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeTree()
            self._rendered_object.selected.connect(self._update_selected)
            self._rendered_object.toggled.connect(self._update_expanded)

    @staticmethod
    def _refresh_nodes(view: TreeView, rendered_object: ComposeTree, value: list[TreeNode]) -> None:
        # the view's, already kept to those still in the nodes
        rendered_object.set_nodes(value, view.expanded, view.selected)

    @staticmethod
    def _refresh_expanded(
        _view: TreeView, rendered_object: ComposeTree, value: list[TreePath]
    ) -> None:
        rendered_object.set_expanded(value)

    @staticmethod
    def _refresh_selected(
        _view: TreeView, rendered_object: ComposeTree, value: TreePath | None
    ) -> None:
        rendered_object.set_selected(value)

    def _update_selected(self, path: TreePath) -> None:
        with self.stop_refresh():
            self._view.selected = path
        self._view.selection_changed.emit(path)

    def _update_expanded(self, path: TreePath, is_expanded: bool) -> None:
        with self.stop_refresh():
            self._view.expanded = self._view.expanded_with(path, is_expanded=is_expanded)
        self._view.toggled.emit(path, is_expanded)
