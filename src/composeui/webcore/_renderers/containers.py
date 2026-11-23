"""The web renderers of containers: rows, columns, panes, grids, lists, tabs, pages."""

from __future__ import annotations

import math
from abc import abstractmethod
from collections import deque
from typing import TYPE_CHECKING, Any, TypeVar

from markupsafe import Markup
from typing_extensions import override

from composeui.core._views.dialogs import dialogs_in
from composeui.core.registry import RendererType
from composeui.core.renderer import RendererContainer
from composeui.core.view import (
    Align,
    DialogView,
    ExpanderView,
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
from composeui.webcore.changes import _DIRTY

if TYPE_CHECKING:
    from collections.abc import Mapping

from composeui.webcore.webrenderer import UnsupportedEventError, WebRenderer, _is_shown, _view_html

TBuilt = TypeVar("TBuilt", bound=View)
TLayout = TypeVar("TLayout", bound="HorizontalView | VerticalView | GridView")


class _BuiltWhenShown(WebRenderer[TBuilt]):
    """A page or a tab whose views are built the first time it's shown, as Qt's are.

    So an app's many pages and tabs don't weigh on each session, in memory and in the time
    of its first page. Its views exist from the start: the app reads and sets any of them,
    and a view built later shows its state then. Until built, the dialogs inside its views,
    which the app opens whatever is shown, follow its enabled state: it adopts them.
    """

    def __init__(self, view: TBuilt) -> None:
        super().__init__(view)
        #: whether its views are built; `defer` leaves them until `build`
        self.is_built = True
        #: the dialogs it adopted until the views around them are built
        self._waiting: list[WebRenderer[Any]] = []

    @abstractmethod
    def _content_views(self) -> list[View]:
        """Get the views it shows, in order."""

    @override
    def render(self) -> None:
        super().render()
        self._adopt(self._content_views())

    def defer(self) -> None:
        """Leave its views unbuilt until `build`, adopting the dialogs inside them meanwhile."""
        self.is_built = False
        for dialog in dialogs_in(self._view):
            renderer = dialog.renderer
            if isinstance(renderer, WebRenderer) and renderer.parent is None:
                renderer.parent = self
                self.children.append(renderer)
                self._waiting.append(renderer)

    def build(self) -> None:
        """Build its views into its session, once: the router or the tabs show it."""
        if self.is_built:
            return
        self.is_built = True
        # the views around them adopt them now, or a tab not built yet, as `defer` does
        for renderer in self._waiting:
            self.children.remove(renderer)
            if renderer.parent is self:  # not adopted since, by a render again of its views
                renderer.parent = None
        self._waiting = []
        with self._in_session():
            for view in self._content_views():
                view.render(RendererType.WEB)
        self._adopt(self._content_views())


class WebPageRenderer(_BuiltWhenShown[PageView]):
    """A page's views in a column, like the main view's own."""

    _role = "page"

    @override
    def _content_views(self) -> list[View]:
        return self._view.content_views

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        content = Markup("").join(
            _view_html(view)
            for view in self._view.content_views
            # at the end of the page instead (see `WebDialogRenderer`)
            if _is_shown(view) and not isinstance(view, DialogView)
        )
        return Markup(
            '<section {root_attributes} data-width="{lower}" class="flex flex-col'
            ' gap-6">{content}</section>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            lower=self._view.width.name.lower(),
            content=content,
        )


class _WebLayoutRenderer(WebRenderer[TLayout]):
    def __init__(self, view: TLayout) -> None:
        super().__init__(view)
        if view.frame is not None:
            self._refresh_dispatcher["frame"] = self._mark_dirty

    @override
    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def _layout_html(self, content: Markup, classes: str, *, oob: bool) -> Markup:
        attributes = self._root_attributes(oob=oob)
        frame = self._view.frame
        if frame is None:
            return Markup('<div {} class="{}">{}</div>').format(attributes, classes, content)
        legend = (
            Markup(
                '<legend class="max-w-full wrap-anywhere px-1 text-sm font-semibold">{}</legend>'
            ).format(str(frame.title))
            if frame.title
            else Markup()
        )
        # The fieldset is the swap root; the inner div still measures its own width.
        return Markup(
            '<fieldset {} data-cui-frame class="min-w-0 rounded-box border border-base-300 p-4">'
            '{}<div class="{}">{}</div></fieldset>'
        ).format(attributes, legend, classes, content)


class WebHorizontalRenderer(_WebLayoutRenderer[HorizontalView]):
    """Views side by side, each as wide as its share of the row.

    Each view sits in a cell carrying its share, an inline style rather than a class
    per share; the cell hides with its view, which swaps on its own. A row narrower than
    42rem stacks its views instead, as a column, unless none has a share (e.g. buttons):
    the share is a variable only the wide row's cells use. A cell without a share is as
    wide as its view, or narrower down to its view's minimum. When no view has a share,
    each keeps its own width, and those that don't fit the row go on the next line.
    """

    _role = "horizontal"

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        stretched_views = self._view.stretched_views
        if not any(stretch > 0 for _, stretch in stretched_views):
            # as wide as their content, up to the row's width, where a label wraps: a
            # container query would measure them as 0 wide
            cells = Markup("").join(
                Markup(
                    '<div class="min-w-0 max-w-full has-[>[hidden]]:hidden" style="flex: none">'
                    "{}</div>"
                ).format(_view_html(view))
                for view, _ in stretched_views
                if _is_shown(view)
            )
            align = " justify-end" if self._view.align is Align.END else ""
            return self._layout_html(cells, f"flex flex-wrap gap-6{align}", oob=oob)
        cells = Markup("").join(
            Markup(
                '<div class="{}has-[>[hidden]]:hidden @2xl:flex-(--share)" style="--share: {}">'
                "{}</div>"
            ).format(
                *(
                    ("min-w-0 ", f"{stretch} 1 0%")
                    if stretch > 0
                    # no share: as wide as its content, narrower only down to its content's
                    # own minimum: a row of buttons within wraps rather than overflows
                    else ("", "0 1 auto")
                ),
                _view_html(view),
            )
            for view, stretch in stretched_views
            if _is_shown(view)
        )
        content = Markup('<div class="flex flex-col gap-6 @2xl:flex-row">{}</div>').format(cells)
        return self._layout_html(content, "@container", oob=oob)


class WebVerticalRenderer(_WebLayoutRenderer[VerticalView]):
    """Views one above the other, at the top of the column, like a page's."""

    _role = "vertical"

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        content = Markup("").join(
            _view_html(view) for view in self._view.children_views if _is_shown(view)
        )
        return self._layout_html(content, "flex flex-col gap-6", oob=oob)


class WebSplitterRenderer(WebRenderer[SplitterView]):
    """Panes side by side, each in a cell as wide as its share, a border between two.

    A border is an ARIA window splitter (a focusable separator) the user drags, or moves
    with the arrow keys. The browser shares the width between the panes beside it at
    once (see `page.js`), then posts every pane's width (`resize`). Like every control,
    the splitter is never swapped back after one. A splitter narrower than 42rem stacks
    its panes, as a row does, without borders; side by side, a pane is at least 12rem
    wide, for its text to be read. A border shows only between panes shown (see
    `app.css`), as a pane hides and swaps on its own. Vertical, the panes share its
    height, 32rem, one above the other, each scrolling within its share.
    """

    _role = "splitter"

    def __init__(self, view: SplitterView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"sizes": self._mark_dirty, "border_text": self._mark_dirty}
        )

    @override
    def render(self) -> None:
        super().render()
        self._adopt(self._view.panes)

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        view = self._view
        is_vertical = view.orientation is Orientation.VERTICAL
        shown = sum(size for pane, size in zip(view.panes, view.sizes) if pane.is_visible) or 1
        disabled = "" if self.is_enabled else Markup(' aria-disabled="true"')
        # a separator's orientation is its line's: across the splitter
        border_orientation = "horizontal" if is_vertical else "vertical"
        pane_class = (
            "min-h-0 overflow-auto has-[>[hidden]]:hidden flex-(--share)"
            if is_vertical
            # side by side, each wide enough to read its text (`page.js` reads it too)
            else "min-w-0 has-[>[hidden]]:hidden @2xl:min-w-48 @2xl:flex-(--share)"
        )
        cells: list[str] = []
        before = 0  # the length of the panes shown before the border, in percent
        for index, (pane, size) in enumerate(zip(view.panes, view.sizes)):
            if not _is_shown(pane):
                continue
            pane_id = f"{self.widget_id}-pane-{index}"
            if index > 0:
                cells.append(
                    Markup(
                        '<div class="cui-splitter-border" role="separator"'
                        ' aria-orientation="{border_orientation}" aria-controls="{pane_id}"'
                        ' aria-label="{border_text}" aria-valuemin="0"'
                        ' aria-valuemax="100" aria-valuenow="{round}"'
                        ' tabindex="{value}"{disabled}></div>'
                    ).format(
                        border_orientation=border_orientation,
                        pane_id=pane_id,
                        border_text=view.border_text,
                        round=round(100 * before / shown),
                        value=0 if self.is_enabled else -1,
                        disabled=disabled,
                    )
                )
            if pane.is_visible:
                before += size
            cells.append(
                Markup(
                    '<div id="{pane_id}" data-pane class="{pane_class}" style="--share: {size} 1'
                    ' 0%">{to_html}</div>'
                ).format(
                    pane_id=pane_id,
                    pane_class=pane_class,
                    size=size,
                    to_html=_view_html(pane),
                )
            )
        if is_vertical:
            return Markup(
                '<div {} data-splitter><div class="flex h-128 flex-col">{}</div></div>'
            ).format(self._root_attributes(oob=oob), Markup("").join(cells))
        # the splitter's own width is queried from its root, the panes laid out inside it
        return Markup(
            '<div {} class="@container" data-splitter>'
            '<div class="flex flex-col gap-6 @2xl:flex-row @2xl:gap-0">'
            "{}</div></div>"
        ).format(self._root_attributes(oob=oob), Markup("").join(cells))

    @override
    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "resize":
            super().dispatch(event, form)
        try:
            lengths = [float(length) for length in form.get("lengths", "").split(",")]
        except ValueError:
            return
        if len(lengths) != len(self._view.panes) or not all(
            math.isfinite(length) and length >= 0 for length in lengths
        ):
            return
        sizes = self._view.shares_of(lengths)
        if sizes == self._view.sizes:  # a click, or a move against a pane's minimum
            return
        with self.stop_refresh():
            self._view.sizes = sizes
        self._view.resized.emit(sizes)


class WebExpanderRenderer(WebRenderer[ExpanderView]):
    """A `<details>` (daisyUI's collapse): its title, then the views one above the other.

    The browser opens and closes it on a click or a key on the title, then posts its
    `toggle`. Like every control, it is never swapped back after one, only when the
    server changes it. Its views swap on their own, shown or not. Disabled, its title
    can't be clicked or focused, as a disabled Qt button can't be pressed.
    """

    _role = "expander"

    def __init__(self, view: ExpanderView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"title": self._mark_dirty, "is_expanded": self._mark_dirty}
        )

    @override
    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        is_open = " open" if self._view.is_expanded else ""
        summary_attributes = (
            "" if self.is_enabled else Markup(' tabindex="-1" aria-disabled="true"')
        )
        summary_classes = "" if self.is_enabled else " pointer-events-none opacity-50"
        content = Markup("").join(
            _view_html(view) for view in self._view.children_views if _is_shown(view)
        )
        # `toggle` also fires when the server swaps it in open: posting the state the
        # server already has, which `dispatch` ignores
        return Markup(
            "<details {root_attributes}{is_open}"
            ' class="collapse collapse-arrow rounded-box border border-base-300 bg-base-100"'
            ' hx-post="/_composeui/widget/{widget_id}" hx-trigger="toggle"'
            ' data-post-event data-post-open hx-swap="none">'
            '<summary class="collapse-title font-semibold{summary_classes}"{summary_attributes}>'
            "{title}</summary>"
            '<div class="collapse-content flex flex-col gap-6">{content}</div></details>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            is_open=is_open,
            widget_id=self.widget_id,
            summary_classes=summary_classes,
            summary_attributes=summary_attributes,
            title=self._view.title,
            content=content,
        )

    @override
    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "toggle":
            super().dispatch(event, form)
        is_expanded = form.get("open") == "true"
        if is_expanded == self._view.is_expanded:
            return
        with self.stop_refresh():
            self._view.is_expanded = is_expanded
        self._view.toggled.emit(is_expanded)


class WebListRenderer(WebRenderer["ListView[Any]"]):
    """The records' views one above the other, each in an item of its own.

    As the records change, the response swaps only the items that changed: an item gone
    is deleted and a new one goes in after its neighbour. So the items kept, the one the
    user is busy in among them, are never swapped back. A change reordering the items
    kept, or anything else changing on the list, swaps the whole list instead. A record's
    view built since is rendered into the session; one gone is dropped from it.
    """

    _role = "list"

    def __init__(self, view: ListView[Any]) -> None:
        super().__init__(view)
        #: the records' views the page shows, as last sent; None until sent
        self._sent: list[View] | None = None
        #: whether more than the records changed since, for which the whole list swaps
        self._is_whole = False
        self._refresh_dispatcher["item_views"] = self._refresh_item_views

    @override
    def render(self) -> None:
        super().render()
        self._render_items(self._view.item_views)

    def _render_items(self, views: list[View]) -> None:
        """Render the views built since the list was, into the session, and adopt them all."""
        built_since = [view for view in views if view.renderer is None]
        with self._in_session():
            for view in built_since:
                view.render(RendererType.WEB)
        self._adopt(views)

    def _item_id(self, view: View) -> str:
        return f"{self.widget_id}-item-{id(view)}"

    def _item_html(self, view: View) -> Markup:
        content = _view_html(view)
        return Markup('<div id="{}">{}</div>').format(self._item_id(view), content)

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        views = self._view.item_views
        sent, self._sent = self._sent, list(views)
        is_whole, self._is_whole = self._is_whole, False
        if oob and not is_whole and sent is not None:
            kept = [view for view in sent if view in views]
            if kept == [view for view in views if view in sent]:
                return self._changes_html(sent, views)
        items = Markup("").join(self._item_html(view) for view in views)
        # `cui-list`: its expanders join in one box (see `css/app.css`)
        return Markup('<div {} class="cui-list flex flex-col gap-3">{}</div>').format(
            self._root_attributes(oob=oob), items
        )

    def _changes_html(self, sent: list[View], views: list[View]) -> Markup:
        """Delete the items gone and put each new one after its neighbour, in order."""
        fragments = [
            Markup('<div id="{}" hx-swap-oob="delete"></div>').format(self._item_id(view))
            for view in sent
            if view not in views
        ]
        for index, view in enumerate(views):
            if view in sent:
                continue
            place = (
                f"afterend:#{self._item_id(views[index - 1])}"
                if index > 0
                else f"afterbegin:#{self.widget_id}"
            )
            fragments.append(
                Markup('<div hx-swap-oob="{}">{}</div>').format(place, self._item_html(view))
            )
        return Markup("").join(fragments)

    def _refresh_item_views(
        self, view: ListView[Any], _rendered_object: str, value: list[View]
    ) -> None:
        self._render_items(value)
        # still the views before: the change lands in the view after its renderers hear it
        self._forget([item_view for item_view in view.item_views if item_view not in value])
        dirty = _DIRTY.get()
        if dirty is not None:
            dirty[self.widget_id] = self

    def _forget(self, views: list[View]) -> None:
        """Drop the renderers of `views`, whose records are gone, from the list and the session."""
        gone: deque[View] = deque(views)
        while len(gone) > 0:
            view = gone.popleft()
            gone.extend(view.children_views)
            renderer: Any = view.renderer
            renderers = (
                renderer.renderers if isinstance(renderer, RendererContainer) else [renderer]
            )
            # not a view this backend doesn't render, nor one never rendered
            shown = [
                child
                for child in renderers
                if isinstance(child, WebRenderer) and child._rendered_object is not None  # noqa: SLF001
            ]
            for child in shown:
                if child in self.children:
                    self.children.remove(child)
                if self._target is not None:
                    self._target.renderers.pop(child.widget_id, None)
                    self._target.pending.pop(child.widget_id, None)

    @override
    def _mark_dirty(self, view: ListView[Any], rendered_object: str, value: Any) -> None:
        self._is_whole = True
        super()._mark_dirty(view, rendered_object, value)


class WebTabPageRenderer(_BuiltWhenShown[TabPage]):
    """A tab's views in a column, which its tabs put in a panel under its tab.

    Its title, visibility and enabled state are its tab's too: a change swaps its tabs.
    Only the current tab's views are sent: another tab's column is empty until picked.
    """

    _role = "tab_page"

    def __init__(self, view: TabPage) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_tab,
                "is_visible": self._refresh_tab,
                "is_enabled": self._refresh_tab,
            }
        )

    @override
    def _content_views(self) -> list[View]:
        return self._view.children_views

    @property
    def is_current(self) -> bool:
        """Whether this is the page of the tab shown, whose views are sent."""
        return not isinstance(self.parent, WebTabsRenderer) or self.parent.is_current(self)

    @override
    def shows(self, _child: WebRenderer[Any]) -> bool:
        return self.is_current

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        content = Markup("").join(
            _view_html(view)
            for view in self._view.children_views
            if self.is_current and _is_shown(view)
        )
        return Markup('<div {} class="flex flex-col gap-6">{}</div>').format(
            self._root_attributes(oob=oob), content
        )

    def _refresh_tab(self, view: TabPage, rendered_object: str, value: Any) -> None:
        self._refresh_enabled(view, rendered_object, value)
        dirty = _DIRTY.get()
        if dirty is not None and self.parent is not None:
            dirty[self.parent.widget_id] = self.parent


class WebTabsRenderer(WebRenderer[TabView]):
    """A row of tabs (an ARIA tab list), then a panel per tab, only the current one shown.

    Only the current tab's page is sent, the others' left empty: an app's many tabs
    don't weigh on each response, nor the browser's page. The browser shows the tab
    picked, by a click or the arrow keys (see `page.js`), before posting it (`select`):
    its answer fills the panel picked and empties the one left. Like every control, the
    tabs are never swapped back after a pick, only when the server changes them.
    """

    _role = "tabs"
    #: read by `TabView`: it renders only the tabs, and this renderer their views, once shown
    renders_on_demand = True

    def __init__(self, view: TabView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["current_index"] = self._refresh_current_index

    @override
    def render(self) -> None:
        super().render()
        for tab in self._view.tabs:
            assert isinstance(tab.renderer, WebTabPageRenderer)  # a tab page's, which the web has
            tab.renderer.defer()
        self._build(self._view.current_index)
        self._adopt(self._view.tabs)

    def _build(self, index: int) -> None:
        """Build the views of the tab at `index`, as it shows: none in a tab view without tabs."""
        for tab in self._view.tabs[index : index + 1]:
            assert isinstance(tab.renderer, WebTabPageRenderer)
            tab.renderer.build()

    def _refresh_current_index(self, view: TabView, rendered_object: str, value: int) -> None:
        self._build(value)  # the view holds it once this returns
        self._mark_dirty(view, rendered_object, value)

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        current = self._view.current_index
        tabs: list[str] = []
        panels: list[str] = []
        for index, tab in enumerate(self._view.tabs):
            assert isinstance(tab.renderer, WebRenderer)  # a tab page's, which the web has
            tab_id, panel_id = f"{self.widget_id}-tab-{index}", f"{self.widget_id}-panel-{index}"
            is_current = index == current
            active = " tab-active" if is_current else ""
            hidden = "" if tab.is_visible else " hidden"
            disabled = "" if tab.is_enabled and self.is_enabled else " disabled"
            # only the current tab in the tab order: the arrow keys move between them
            tabs.append(
                Markup(
                    '<button type="button" role="tab" id="{tab_id}" aria-controls="{panel_id}"'
                    ' aria-selected="{lower}" tabindex="{value}"'
                    ' class="tab{active}" data-tab hx-post="/_composeui/widget/{widget_id}"'
                    """ hx-vals='{{"event": "select", "index": "{index}"}}' hx-swap='none'"""
                    "{hidden}{disabled}>{title}</button>"
                ).format(
                    tab_id=tab_id,
                    panel_id=panel_id,
                    lower=str(is_current).lower(),
                    value=0 if is_current else -1,
                    active=active,
                    widget_id=self.widget_id,
                    index=index,
                    hidden=hidden,
                    disabled=disabled,
                    title=tab.title,
                )
            )
            panels.append(
                Markup(
                    '<div role="tabpanel" id="{panel_id}"'
                    ' aria-labelledby="{tab_id}"{value}>{to_html}</div>'
                ).format(
                    panel_id=panel_id,
                    tab_id=tab_id,
                    value="" if is_current else " hidden",
                    to_html=tab.renderer.to_html(),
                )
            )
        return Markup(
            '<div {root_attributes} class="flex flex-col gap-4">'
            '<div role="tablist" class="tabs tabs-border">{join}</div>'
            "{join2}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            join=Markup("").join(tabs),
            join2=Markup("").join(panels),
        )

    @override
    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "select":
            super().dispatch(event, form)
        try:
            index = int(form.get("index", ""))
        except ValueError:
            return
        if not 0 <= index < len(self._view.tabs) or index == self._view.current_index:
            return
        if not self._view.tabs[index].is_enabled:
            raise UnsupportedEventError(self, event)
        left = self._view.tabs[self._view.current_index]
        with self.stop_refresh():
            self._view.current_index = index
        self._build(index)
        dirty = _DIRTY.get()
        assert dirty is not None  # a browser event's, collected by `handle_event`
        for tab in (left, self._view.tabs[index]):
            assert isinstance(tab.renderer, WebRenderer)  # a tab page's, which the web has
            dirty[tab.renderer.widget_id] = tab.renderer
        self._view.current_changed.emit(index)

    def is_current(self, page: WebRenderer[Any]) -> bool:
        """Whether `page` is the renderer of the current tab's page."""
        current = self._view.current_tab
        return current is not None and current.renderer is page


class WebGridRenderer(_WebLayoutRenderer[GridView]):
    """Views in a grid's cells: equally wide columns, rows as tall as their views.

    The columns and each view's cell are variables rather than a class per count; a cell
    placed rather than flowed stays where it is when an earlier one hides. A grid
    narrower than 42rem stacks its views instead, in one column, row by row: only the
    wide grid uses the variables.
    """

    _role = "grid"

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        cells = Markup("").join(
            Markup(
                '<div class="min-w-0 has-[>[hidden]]:hidden @2xl:[grid-area:var(--area)]"'
                ' style="--area: {value} / {value2} / span {row_span} / span {column_span}">'
                "{to_html}</div>"
            ).format(
                value=row + 1,
                value2=column + 1,
                row_span=row_span,
                column_span=column_span,
                to_html=_view_html(view),
            )
            for view, (row, column, row_span, column_span) in self._view.positioned_views
            if _is_shown(view)
        )
        columns = f"repeat({self._view.column_count}, minmax(0, 1fr))"
        content = Markup(
            '<div class="grid grid-cols-1 items-start gap-6 @2xl:grid-cols-(--columns)"'
            ' style="--columns: {columns}">{cells}</div>'
        ).format(columns=columns, cells=cells)
        return self._layout_html(content, "@container", oob=oob)
