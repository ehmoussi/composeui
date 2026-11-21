"""Textual layouts, lists and tabs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import Container, Grid, Horizontal, Vertical
from textual.content import Content
from textual.widget import Widget
from textual.widgets import TabPane
from typing_extensions import override

from composeui.core.registry import RendererType
from composeui.core.view import (
    Align,
    ExpanderView,
    GridPosition,
    GridView,
    HorizontalView,
    ListView,
    Orientation,
    PageView,
    SplitterView,
    TabPage,
    TabView,
    VerticalView,
    View,
)
from composeui.textualcore._renderers.forms import _widget_of
from composeui.textualcore.textualrenderer import TextualWidgetRenderer, _refresh_tree
from composeui.textualcore.widgets.composecollapsible import ComposeCollapsible
from composeui.textualcore.widgets.composeflow import ComposeFlow
from composeui.textualcore.widgets.composelist import ComposeList
from composeui.textualcore.widgets.composesplitter import ComposeSplitter
from composeui.textualcore.widgets.composetabbedcontent import ComposeTabbedContent

if TYPE_CHECKING:
    from textual.widget import AwaitMount


class TextualPageRenderer(TextualWidgetRenderer[PageView, Vertical]):
    """A page's views in a column, like the screen's own."""

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            widgets = [
                widget
                for view in self._view.content_views
                if (widget := _widget_of(view)) is not None
            ]
            self._rendered_object = Vertical(*widgets)
            self._rendered_object.styles.height = "auto"


class TextualHorizontalRenderer(TextualWidgetRenderer[HorizontalView, Widget]):
    """Views side by side, each as wide as its share of the row.

    When none has a share (e.g. buttons), each keeps its own width, and the views that
    don't fit the row's width go on the next line.
    """

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            widgets: list[Widget] = []
            stretched_views = self._view.stretched_views
            for view, stretch in stretched_views:
                widget = _widget_of(view)
                if widget is not None:
                    # no share: as wide as its content
                    widget.styles.width = f"{stretch}fr" if stretch > 0 else "auto"
                    widgets.append(widget)
            align_end = self._view.align is Align.END
            if any(stretch > 0 for _, stretch in stretched_views):
                self._rendered_object = Horizontal(*widgets)
                self._rendered_object.styles.height = "auto"
                # for the views without a share while those with one are hidden
                if align_end:
                    self._rendered_object.styles.align_horizontal = "right"
            else:
                self._rendered_object = ComposeFlow(*widgets, align_end=align_end)


class TextualVerticalRenderer(TextualWidgetRenderer[VerticalView, Vertical]):
    """Views one above the other, at the top of the column."""

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            widgets = [
                widget
                for view in self._view.children_views
                if (widget := _widget_of(view)) is not None
            ]
            self._rendered_object = Vertical(*widgets)
            self._rendered_object.styles.height = "auto"


class TextualSplitterRenderer(TextualWidgetRenderer[SplitterView, ComposeSplitter]):
    """The panes in a row or a column, a handle between two the user drags or moves by keys."""

    def __init__(self, view: SplitterView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["sizes"] = self._refresh_sizes
        # names a border on the web only
        self._refresh_dispatcher["border_text"] = lambda _view, _splitter, _value: None

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            panes = [
                widget for view in self._view.panes if (widget := _widget_of(view)) is not None
            ]
            self._rendered_object = ComposeSplitter(
                *panes, is_vertical=self._view.orientation is Orientation.VERTICAL
            )
            self._rendered_object.resized.connect(self._update_sizes)

    @staticmethod
    def _refresh_sizes(
        _view: SplitterView, rendered_object: ComposeSplitter, value: list[int]
    ) -> None:
        rendered_object.set_sizes(value)

    def _update_sizes(self, lengths: list[int]) -> None:
        sizes = self._view.shares_of(lengths)
        if sizes == self._view.sizes:  # a click, or a move against a pane's minimum
            return
        with self.stop_refresh():
            self._view.sizes = sizes
        self._view.resized.emit(sizes)


class TextualExpanderRenderer(TextualWidgetRenderer[ExpanderView, ComposeCollapsible]):
    """Textual's collapsible: its title, then the views one above the other while expanded."""

    def __init__(self, view: ExpanderView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"title": self._refresh_title, "is_expanded": self._refresh_is_expanded}
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            widgets = [
                widget
                for view in self._view.children_views
                if (widget := _widget_of(view)) is not None
            ]
            self._rendered_object = ComposeCollapsible(*widgets)
            self._rendered_object.toggled.connect(self._update_expanded)

    @staticmethod
    def _refresh_title(
        _view: ExpanderView, rendered_object: ComposeCollapsible, value: str
    ) -> None:
        rendered_object.title = value

    @staticmethod
    def _refresh_is_expanded(
        _view: ExpanderView, rendered_object: ComposeCollapsible, value: bool
    ) -> None:
        rendered_object.set_expanded(value)

    def _update_expanded(self, is_expanded: bool) -> None:
        with self.stop_refresh():
            self._view.is_expanded = is_expanded
        self._view.toggled.emit(is_expanded)


class TextualListRenderer(TextualWidgetRenderer["ListView[Any]", ComposeList]):
    """The records' views one above the other, added, moved and removed as they change.

    Widgets only mount in a running app. The column is put in step with the records once
    it is mounted (`_refresh_tree` refreshes it then too), a record's widget built since
    mounted next to its neighbours, then given its view's state.
    """

    def __init__(self, view: ListView[Any]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"item_views": self._refresh_item_views})

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeList(*self._widgets(self._view.item_views))

    @staticmethod
    def _widgets(views: list[View]) -> list[Widget]:
        """Get the views' widgets, rendering the views built since the list was."""
        widgets: list[Widget] = []
        for view in views:
            if view.renderer is None:
                view.render(RendererType.TEXTUAL)
            widget = _widget_of(view)
            if widget is not None:
                widgets.append(widget)
        return widgets

    @staticmethod
    def _refresh_item_views(_view: ListView[Any], column: ComposeList, value: list[View]) -> None:
        widgets = TextualListRenderer._widgets(value)
        if not column.is_attached:
            return  # put in step once mounted
        for child in list(column.children):
            if child not in widgets:
                child.remove()  # its record is gone
        previous: Widget | None = None
        for view, widget in zip(value, widgets):
            if widget.parent is column:
                if previous is not None:
                    column.move_child(widget, after=previous)
                elif column.children[0] is not widget:
                    column.move_child(widget, before=0)
            else:
                if previous is not None:
                    mounting = column.mount(widget, after=previous)
                elif len(column.children) > 0:
                    mounting = column.mount(widget, before=0)
                else:
                    mounting = column.mount(widget)
                column.call_next(TextualListRenderer._refresh_once_mounted, mounting, view)
            previous = widget

    @staticmethod
    async def _refresh_once_mounted(mounting: AwaitMount, view: View) -> None:
        """Give `view`'s widgets its state once mounted: Textual's widgets take it only then."""
        await mounting
        _refresh_tree(view)


class TextualTabPageRenderer(TextualWidgetRenderer[TabPage, TabPane]):
    """A tab's views in a pane; its title, visibility and enabled state are its tab's."""

    def __init__(self, view: TabPage) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "is_visible": self._refresh_tab_visible,
                "is_enabled": self._refresh_tab_enabled,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            widgets = [
                widget
                for view in self._view.children_views
                if (widget := _widget_of(view)) is not None
            ]
            # an id: the tabs tell their panes by it
            self._rendered_object = TabPane(
                Content(self._view.title), *widgets, id=f"cui-{id(self._view)}-tab"
            )

    @staticmethod
    def _tabs(pane: TabPane) -> ComposeTabbedContent | None:
        """Get the tabs `pane` is a tab of, once mounted."""
        if not pane.is_attached:
            return None
        return next((a for a in pane.ancestors if isinstance(a, ComposeTabbedContent)), None)

    @staticmethod
    def _refresh_title(_view: TabPage, rendered_object: TabPane, value: str) -> None:
        tabs = TextualTabPageRenderer._tabs(rendered_object)
        if tabs is not None:
            tabs.get_tab(rendered_object).label = Content(value)

    @staticmethod
    def _refresh_tab_visible(_view: TabPage, rendered_object: TabPane, value: bool) -> None:
        # not the pane's own display: only the current tab's pane shows
        tabs = TextualTabPageRenderer._tabs(rendered_object)
        if tabs is not None and rendered_object.id is not None:
            if value:
                tabs.show_tab(rendered_object.id)
            else:
                tabs.hide_tab(rendered_object.id)

    @staticmethod
    def _refresh_tab_enabled(_view: TabPage, rendered_object: TabPane, value: bool) -> None:
        rendered_object.disabled = not value  # its tab follows


class TextualTabsRenderer(TextualWidgetRenderer[TabView, ComposeTabbedContent]):
    """Textual's tabbed content: the tabs in a row, the current one's pane under them."""

    def __init__(self, view: TabView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["current_index"] = self._refresh_current_index

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            panes = [
                tab.renderer.widget
                for tab in self._view.tabs
                if isinstance(tab.renderer, TextualTabPageRenderer)
                and tab.renderer.widget is not None
            ]
            # on the view's tab: Textual reports the first tab shown as picked
            tabs = self._view.tabs
            initial = self._pane_id(tabs[self._view.current_index]) if len(tabs) > 0 else ""
            self._rendered_object = ComposeTabbedContent(*panes, initial=initial)
            self._rendered_object.picked.connect(self._update_current_index)

    @staticmethod
    def _pane_id(tab: TabPage) -> str:
        """Get the id of `tab`'s pane, which the tabs tell it by."""
        renderer = tab.renderer
        assert isinstance(renderer, TextualTabPageRenderer)
        assert renderer.widget is not None
        assert renderer.widget.id is not None  # given by the tab page's renderer
        return renderer.widget.id

    @staticmethod
    def _refresh_current_index(
        view: TabView, rendered_object: ComposeTabbedContent, value: int
    ) -> None:
        rendered_object.set_active(TextualTabsRenderer._pane_id(view.tabs[value]))

    @staticmethod
    def _index(view: TabView, pane_id: str) -> int | None:
        """Get the index of the tab whose pane is `pane_id`."""
        ids = [TextualTabsRenderer._pane_id(tab) for tab in view.tabs]
        return ids.index(pane_id) if pane_id in ids else None

    def _update_current_index(self, pane: TabPane) -> None:
        index = self._index(self._view, pane.id or "")
        if index is None or index == self._view.current_index:
            return
        with self.stop_refresh():
            self._view.current_index = index
        self._view.current_changed.emit(index)


class TextualGridRenderer(TextualWidgetRenderer[GridView, Grid]):
    """Views in a grid's cells: equally wide columns, rows as tall as their views.

    Textual's grid flows its widgets into the next free cell: each view sits in a cell
    widget, empty for cells no view takes. So a hidden view leaves its cell in place.
    """

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            at_cell = {
                (position.row, position.column): (view, position)
                for view, position in self._view.positioned_views
            }
            taken: set[tuple[int, int]] = set()
            cells: list[Widget] = []
            for row in range(self._view.row_count):
                for column in range(self._view.column_count):
                    if (row, column) in taken:
                        continue
                    view, position = at_cell.get((row, column), (None, GridPosition(row, column)))
                    taken.update(position.cells)
                    cell = Container()
                    widget = None if view is None else _widget_of(view)
                    if view is not None and widget is not None:
                        # with no share of a row, as wide as its content
                        widget.styles.width = "1fr" if view.default_stretch > 0 else "auto"
                        cell = Container(widget)
                    cell.styles.row_span = position.row_span
                    cell.styles.column_span = position.column_span
                    cell.styles.height = "auto"
                    cells.append(cell)
            self._rendered_object = Grid(*cells)
            self._rendered_object.styles.grid_size_columns = self._view.column_count
            self._rendered_object.styles.grid_columns = "1fr"
            self._rendered_object.styles.grid_rows = "auto"
            self._rendered_object.styles.height = "auto"
