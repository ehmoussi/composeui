"""The views that place other views: rows, columns, tabs, grids, pages, lists."""

from __future__ import annotations

import enum
import re
import weakref
from collections.abc import Callable, Hashable, Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    NamedTuple,
    Optional,
    TypeVar,
    Union,
)

import attrs
from typing_extensions import override

from composeui.core._views.actions import ActionView
from composeui.core._views.base import (
    _P,
    GRID_POSITION,
    OMIT,
    SESSION,
    STRETCH,
    UI_TEXT,
    View,
    _attach_jobs,
    _release_tasks,
    _retranslate,
    _ViewT,
    child,
    define_view,
    set_references,
    view_fields,
)
from composeui.core._views.dialogs import dialogs_in
from composeui.core.model import Model
from composeui.core.registry import RendererType, renders_on_demand
from composeui.core.signal import Signal
from composeui.core.translation import (
    T,
    Translate,
    translate_again,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


class PageWidth(enum.Enum):
    """How wide the content of a main view or page may grow on the web."""

    #: a column of fields, easy to read
    NARROW = enum.auto()
    #: room for side by side views, e.g. tables
    WIDE = enum.auto()
    #: the whole window
    FULL = enum.auto()


class Align(enum.Enum):
    """Where a row packs its views when they leave some of its width free."""

    START = enum.auto()
    END = enum.auto()


@attrs.frozen(kw_only=True)
class Frame:
    """A border around a layout, with an optional title."""

    title: str = ""

    def translated(self, translate: Translate) -> Frame:
        """Get the frame with its title translated again."""
        title = translate_again(self.title, translate)
        return self if title is self.title else attrs.evolve(self, title=title)


@define_view
class _FramedView(View):
    #: the frame around this layout, set at construction and not saved in a study
    frame: Optional[Frame] = attrs.field(
        default=None, on_setattr=attrs.setters.frozen, metadata={OMIT: True}
    )


@define_view
class HorizontalView(_FramedView):
    """Its view fields laid out side by side, in a row.

    Each field takes a share of the row's width, set by its `STRETCH` metadata:
    ``rooms: TableView = attrs.field(factory=TableView, metadata={STRETCH: 3})``. When the
    metadata is unset, the share is the view's `default_stretch` (1). A view with a share
    of 0 keeps its content's width, as a button does by default. When all views do,
    `align` packs them at the row's start or end: a subclass sets ``align = Align.END``,
    and the views that don't fit the row's width go on the next line. When a view takes a
    share, a row narrower than 42rem stacks its views on the web.
    """

    _renderer_key = "horizontal"

    #: where the views go when none of them takes a share of the row's free width
    align: ClassVar[Align] = Align.START

    @property
    def stretched_views(self) -> list[tuple[View, int]]:
        """Get the views in the row, in order, each with its share of the row's width."""
        return [
            (view, f.metadata.get(STRETCH, view.default_stretch))
            for f in view_fields(type(self))
            if isinstance(view := getattr(self, f.name), View)
        ]


@define_view
class VerticalView(_FramedView):
    """Its view fields laid out one above the other, in a column, as tall as their content.

    A page is already a column: this one is for a column inside a `HorizontalView`, e.g.
    a table above its buttons, next to another table.
    """

    _renderer_key = "vertical"


class Orientation(enum.Enum):
    """How a splitter lays out its panes."""

    #: side by side, sharing its width
    HORIZONTAL = enum.auto()
    #: one above the other, sharing its height
    VERTICAL = enum.auto()


@define_view
class SplitterView(View):
    """Its view fields in panes, side by side, the user dragging the border between two.

    E.g. a study tree beside its result. Each pane starts with its share of the width, set
    by its field's `STRETCH` metadata as in a `HorizontalView`. The share is at least 1:
    every pane takes some width. `sizes` holds the shares. The user changes them by
    dragging a border, or with the arrow keys on it, and never shrinks a pane to nothing.
    A hidden pane leaves its width to the others. On the web, a splitter narrower than
    42rem stacks its panes, as a row does.

    A subclass that sets ``orientation = Orientation.VERTICAL`` lays out the panes one
    above the other instead, e.g. a chart above its table. The panes then share its
    height: the window's spare height on Qt, a set height elsewhere (24 rows on Textual,
    32rem on the web). Each pane scrolls within its share.
    """

    _renderer_key = "splitter"

    #: how the panes are laid out: side by side, or one above the other
    orientation: ClassVar[Orientation] = Orientation.HORIZONTAL

    def _check_sizes(self, _attribute: attrs.Attribute[Any], sizes: list[int]) -> None:
        count = len(self.children_views)
        if len(sizes) not in (0, count) or any(size <= 0 for size in sizes):
            msg = f"Cannot share {type(self).__name__}'s {count} panes as {sizes}."
            raise ValueError(msg)

    #: each pane's share of the width (the height, vertical), in order; once the user drags
    #: a border, the panes shown in percent of theirs. Layout, not study data: never saved,
    #: loaded or reset, but kept with the session (`SESSION`)
    sizes: list[int] = attrs.field(
        factory=list, validator=[_check_sizes], metadata={OMIT: True, SESSION: True}
    )
    #: names a border between two panes for a screen reader, on the web
    border_text: str = attrs.field(default=T("Resize the panes"), metadata={UI_TEXT: True})
    #: the user dragged a border (once dropped) or moved one with a key, giving the new
    #: `sizes`; not emitted when `sizes` is set in code
    resized: Signal[list[int]] = attrs.Factory(Signal[list[int]])

    @override
    def __attrs_post_init__(self) -> None:
        if len(self.sizes) == 0:
            self.sizes = [
                max(f.metadata.get(STRETCH, view.default_stretch), 1)
                for f in view_fields(type(self))
                if isinstance(view := getattr(self, f.name), View)
            ]
        super().__attrs_post_init__()

    @property
    def panes(self) -> list[View]:
        """Get the panes' views, in order."""
        return self.children_views

    def shares_of(self, lengths: Sequence[float]) -> list[int]:
        """Get the `sizes` of panes `lengths` wide (tall, vertical), as the user dragged them.

        In any unit: a pane shown gets its percent of the shown panes' length, at least 1;
        a hidden one keeps its share.
        """
        shown = [view.is_visible for view in self.panes]
        total = sum(length for length, is_shown in zip(lengths, shown) if is_shown)
        if total <= 0:  # not laid out yet
            return list(self.sizes)
        return [
            max(round(100 * length / total), 1) if is_shown else size
            for length, is_shown, size in zip(lengths, shown, self.sizes)
        ]


@define_view
class ExpanderView(View):
    """A collapsible section: its title always shown, its view fields only while expanded.

    Its view fields are laid out one above the other, as in a `VerticalView`, e.g. a
    record's details above its Edit and Delete buttons.
    """

    _renderer_key = "expander"

    #: shown in the header the user clicks to expand or collapse the section
    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    is_expanded: bool = attrs.field(default=False)
    #: the user expanded or collapsed the section; not emitted when `is_expanded` is set in code
    toggled: Signal[bool] = attrs.Factory(Signal[bool])


@define_view
class TabPage(View):
    """A tab of a `TabView`: its `title` on the tab, its view fields its content, in a column.

    Hidden, its tab is too; disabled, its tab can't be picked.
    """

    _renderer_key = "tab_page"

    title: str = attrs.field(default="", metadata={UI_TEXT: True})


@define_view
class TabView(View):
    """Views shown a tab at a time, picked from a row of tabs, e.g. a record's details and history.

    Its `TabPage` fields are the tabs, in order; it starts on the first. Distinct from
    pages: tabs live inside a page or a form, and have no address of their own.
    """

    _renderer_key = "tabs"

    def _check_current_index(self, _attribute: attrs.Attribute[Any], index: int) -> None:
        count = len(self.tabs)
        if not 0 <= index < max(count, 1):
            msg = f"Cannot show tab {index} of {type(self).__name__}: it has {count} tabs."
            raise ValueError(msg)

    #: the tab shown, counted from 0. Navigation, not study data: never saved, loaded or
    #: reset, but kept with the session (`SESSION`)
    current_index: int = attrs.field(
        default=0, validator=[_check_current_index], metadata={OMIT: True, SESSION: True}
    )
    #: the user picked another tab, by its index; not emitted when `current_index` is set in code
    current_changed: Signal[int] = attrs.Factory(Signal[int])

    @property
    def tabs(self) -> list[TabPage]:
        """Get the tabs, in order."""
        return [view for view in self.children_views if isinstance(view, TabPage)]

    @property
    def current_tab(self) -> Optional[TabPage]:
        """Get the tab shown, or None without tabs."""
        tabs = self.tabs
        return tabs[self.current_index] if len(tabs) > 0 else None

    @override
    def _render_children(self, renderer_type: RendererType) -> None:
        if not renders_on_demand(renderer_type, "tabs"):
            super()._render_children(renderer_type)
            return
        # a tab gets its renderer, which shows its title and state on its tab, and its
        # dialogs: the renderer builds its views the first time it's shown, the shown one's
        # at once
        for tab in self.tabs:
            for dialog in dialogs_in(tab):
                dialog.render(renderer_type)
            if tab.renderer is None:
                tab._create_renderer(renderer_type)  # noqa: SLF001 (a tab rendered with the tabs)
            # a backend building tabs once shown renders the tabs themselves
            assert tab.renderer is not None
            tab.renderer.render()


class GridPosition(NamedTuple):
    """A view's cell in a `GridView`, counted from 0, spanning more cells to its right or below."""

    row: int
    column: int
    row_span: int = 1
    column_span: int = 1

    @property
    def cells(self) -> list[tuple[int, int]]:
        """Get the (row, column) cells the view covers."""
        return [
            (row, column)
            for row in range(self.row, self.row + self.row_span)
            for column in range(self.column, self.column + self.column_span)
        ]


class GridPositionError(ValueError):
    """A `GridView`'s view field has no cell, or one outside the grid or another view's."""


def grid_cell(
    position: Union[GridPosition, tuple[int, int]],
    cls: Callable[_P, _ViewT],
    /,
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _ViewT:
    """Get a `GridView` field's default: a `cls` view in the cell at `position`.

    E.g. ``chart: ChartView = grid_cell((1, 0), ChartView, title="Sales")``. The arguments
    after `cls` build the view, as those of `child` do.
    """
    return attrs.field(default=child(cls, *args, **kwargs), metadata={GRID_POSITION: position})


@define_view
class GridView(_FramedView):
    """Its view fields laid out in a grid: equally wide columns, rows as tall as their views.

    Each field sets its cell with `grid_cell`:
    ``chart: ChartView = grid_cell((1, 0), ChartView, title="Sales")``,
    or ``grid_cell(GridPosition(1, 0, column_span=2), ChartView)`` to span two columns. A
    field that needs other metadata sets its `GRID_POSITION` metadata itself. Cells no view
    takes are left empty, as are those of a hidden view. A view shorter than its row stays at its
    top. A view with no share of a row (`default_stretch` 0, e.g. a button) keeps its
    content's width, at its cell's start. On the web, a grid narrower than 42rem stacks
    its views in one column, row by row.
    """

    _renderer_key = "grid"

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        taken: dict[tuple[int, int], str] = {}
        for name, (_, position) in self._named_positions().items():
            if position.row < 0 or position.column < 0:
                msg = f"{type(self).__name__}.{name}: no cell before row or column 0"
                raise GridPositionError(msg)
            if position.row_span < 1 or position.column_span < 1:
                msg = f"{type(self).__name__}.{name}: a span is at least 1"
                raise GridPositionError(msg)
            for cell in position.cells:
                if cell in taken:
                    msg = f"{type(self).__name__}.{name}: cell {cell} is {taken[cell]}'s"
                    raise GridPositionError(msg)
                taken[cell] = name

    @property
    def positioned_views(self) -> list[tuple[View, GridPosition]]:
        """Get the views in the grid with their cells, row by row."""
        return sorted(self._named_positions().values(), key=lambda vp: (vp[1].row, vp[1].column))

    @property
    def row_count(self) -> int:
        """Get the number of rows: down to the lowest view's last."""
        return max((p.row + p.row_span for _, p in self.positioned_views), default=0)

    @property
    def column_count(self) -> int:
        """Get the number of columns: up to the rightmost view's last."""
        return max((p.column + p.column_span for _, p in self.positioned_views), default=0)

    def _named_positions(self) -> dict[str, tuple[View, GridPosition]]:
        """Get each view field's view and cell, by field name."""
        positions: dict[str, tuple[View, GridPosition]] = {}
        for f in view_fields(type(self)):
            if isinstance(view := getattr(self, f.name), View):
                position = f.metadata.get(GRID_POSITION)
                if position is None:
                    msg = f"{type(self).__name__}.{f.name}: no GRID_POSITION in its metadata"
                    raise GridPositionError(msg)
                positions[f.name] = (view, GridPosition(*position))
        return positions


#: what a page's route can be: it also names the page in a web address (``/<route>``)
_ROUTE_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


@define_view
class PageView(View):
    """A page of the app, shown while its `Router` is on the page's `route`.

    Its view fields are its content, laid out in a column. `action` is its entry in the
    router's toolbar, which shows the page's `title` and `icon`. The action isn't content.
    It is navigation, not study data: never saved, loaded or reset.
    """

    _renderer_key = "page"
    #: how wide the page may grow; a subclass sets it: ``width = PageWidth.WIDE``
    width: ClassVar[PageWidth] = PageWidth.NARROW
    #: names the page in its router; a subclass sets it: ``route = "results"``
    route: ClassVar[str] = ""
    #: the `title` the page starts with: ``page_title = T("Results")``
    page_title: ClassVar[str] = ""

    action: ActionView = attrs.field(factory=ActionView, metadata={OMIT: True})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.page_title

    @property
    def title(self) -> str:
        """The page's name in the toolbar."""
        return self.action.text

    @title.setter
    def title(self, title: str) -> None:
        self.action.text = title

    @property
    def icon(self) -> Optional[str]:
        """The page's icon in the toolbar, if the backend shows icons."""
        return self.action.icon

    @icon.setter
    def icon(self, icon: Optional[str]) -> None:
        self.action.icon = icon

    @property
    def content_views(self) -> list[View]:
        """Get the views shown on the page, in order."""
        return [view for view in self.children_views if view is not self.action]


ItemT = TypeVar("ItemT")


@define_view
class ListView(View, Generic[ItemT]):
    """A view per record, laid out in a column, e.g. an expander per record.

    A subclass builds a record's view (`build_item`). Set `items` to the records, e.g. the
    model's, to show them. A new record gets a view of its own, and a record gone takes
    its view along. A record still there keeps its view, told by its key (`item_key`). A
    changed record keeps its view if `update_item` shows the change in it. The view then
    keeps what the user did to it, e.g. an expander stays expanded. Else the record gets a
    new view. The records and their views are the model's, not study data: never saved,
    loaded or reset.
    """

    _renderer_key = "list"

    #: the records' views, in the records' order; made by setting `items`
    item_views: list[View] = attrs.field(factory=list, init=False, metadata={OMIT: True})
    _items: list[ItemT] = attrs.field(factory=list, init=False, repr=False, metadata={OMIT: True})
    #: the model the signals of the views built pass on (see `set_references`)
    _model: Optional[Callable[[], Optional[Model]]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @override
    def _keep_model(self, model: Optional[Model]) -> None:
        self._model = None if model is None else weakref.ref(model)

    @property
    @override
    def children_views(self) -> list[View]:
        return [*super().children_views, *self.item_views]

    @property
    def items(self) -> list[ItemT]:
        """Get the records shown, in order."""
        return list(self._items)

    @items.setter
    def items(self, items: Iterable[ItemT]) -> None:
        new_items = list(items)
        old = {
            self.item_key(item): (item, view) for item, view in zip(self._items, self.item_views)
        }
        views: list[View] = []
        keys: set[Hashable] = set()
        for item in new_items:
            key = self.item_key(item)
            if key in keys:
                msg = f"Two records of {type(self).__name__} have the key {key!r}."
                raise ValueError(msg)
            keys.add(key)
            old_item, view = old.get(key, (None, None))
            if view is None or (old_item != item and not self.update_item(view, item)):
                view = self._new_item_view(item)
            views.append(view)
        kept = {id(view) for view in views}
        for view in self.item_views:
            if id(view) not in kept:
                _release_tasks(view)
        self._items = new_items
        self.item_views = views

    def build_item(self, item: ItemT) -> View:
        """Get a new view showing `item`; a subclass builds it."""
        raise NotImplementedError(self.build_item)

    def item_key(self, item: ItemT) -> Hashable:
        """Get what tells `item` apart from the other records: the record itself by default.

        A record changed, with the same key, keeps its view; e.g. a key of its name or id.
        """
        return item

    def update_item(self, view: View, item: ItemT) -> bool:
        """Show `item`, changed, in `view`, its view; return False to get a new view instead.

        The default, so a subclass only shows a change in place where it's worth it.
        """
        return False

    def _new_item_view(self, item: ItemT) -> View:
        """Build `item`'s view, set up as the views built with the main view were.

        Its signals pass the main view and the model on, and it shows the main view's
        language; the list's renderer renders it, if the list is rendered. Set in
        `item_views`, it starts its reactive methods if the list's are started.
        """
        view = self.build_item(item)
        main_view = None if self._main_view is None else self._main_view()
        if main_view is not None:
            set_references(view, main_view, None if self._model is None else self._model())
        jobs = None if self._task_jobs is None else self._task_jobs()
        if jobs is not None:
            _attach_jobs(view, jobs)
        _retranslate(view, self._tr)
        return view
