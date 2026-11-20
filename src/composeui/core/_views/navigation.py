"""The router and the sidebar, which move between the pages of an app."""

from __future__ import annotations

import functools
from typing import (
    Optional,
)

import attrs
from typing_extensions import override

from composeui.core._views.base import OMIT, SESSION, UI_TEXT, View, define_view
from composeui.core._views.containers import _ROUTE_PATTERN, PageView
from composeui.core._views.dialogs import dialogs_in
from composeui.core.registry import RendererType, renders_on_demand
from composeui.core.signal import Signal
from composeui.core.translation import (
    T,
)


@define_view
class Router(View):
    """Pages shown one at a time, picked from a toolbar with an entry per page.

    Its page fields are the pages, in toolbar order. It starts on the first page;
    triggering a page's `action` navigates to the page, and only the shown page's action
    is checked. Pages can't be added or removed once built.
    """

    _renderer_key = "router"

    #: the shown page's route; change it with `navigate`. Navigation, not study data:
    #: never saved, loaded or reset
    current_route: str = attrs.field(default="", metadata={OMIT: True})
    #: a different page is shown, by its route
    route_changed: Signal[str] = attrs.Factory(Signal[str])

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        routes: set[str] = set()
        for page in self.pages:
            if _ROUTE_PATTERN.fullmatch(page.route) is None:
                msg = (
                    f"{type(page).__name__}.route is {page.route!r}: a route is made of "
                    "letters, digits, '_' and '-' only. Set it in the page's class: "
                    'route = "results".'
                )
                raise ValueError(msg)
            if page.route in routes:
                msg = f"Two pages of {type(self).__name__} have the route {page.route!r}."
                raise ValueError(msg)
            routes.add(page.route)
            page.action.is_checkable = True
            page.action.triggered.connect(functools.partial(self.navigate, page.route))
        if len(self.pages) > 0:
            self._show(self.pages[0].route)

    @property
    def pages(self) -> list[PageView]:
        """Get the pages, in toolbar order."""
        return [view for view in self.children_views if isinstance(view, PageView)]

    @property
    def current_page(self) -> Optional[PageView]:
        """Get the shown page, or None without pages."""
        return self.page(self.current_route)

    def page(self, route: str) -> Optional[PageView]:
        """Get the page on `route`, or None if no page has it."""
        return next((page for page in self.pages if page.route == route), None)

    def navigate(self, route: str) -> None:
        """Show the page on `route`; raise `ValueError` if no page has it."""
        if self.page(route) is None:
            routes = [page.route for page in self.pages]
            msg = f"{type(self).__name__} has no page on {route!r}, only on {routes}."
            raise ValueError(msg)
        is_changed = route != self.current_route
        self._show(route)
        if is_changed:
            self.route_changed.emit(route)

    @override
    def _render_children(self, renderer_type: RendererType) -> None:
        if not renders_on_demand(renderer_type, "router"):
            super()._render_children(renderer_type)
            return
        # the pages not shown, nor built yet, get only their toolbar entry, and their
        # dialogs, which the app opens whatever the page shown: the renderer builds each
        # page the first time it's shown, from the page's state then
        for view in self.children_views:
            if (
                isinstance(view, PageView)
                and view.route != self.current_route
                and view.renderer is None
            ):
                view.action.render(renderer_type)
                for dialog in dialogs_in(view):
                    dialog.render(renderer_type)
            else:
                view.render(renderer_type)

    def _show(self, route: str) -> None:
        # set even when it's already the route: triggering a checked action unchecks it
        for page in self.pages:
            page.action.is_checked = page.route == route
        self.current_route = route


@define_view
class SidebarView(View):
    """A column of views beside the pages, shown whatever the page, e.g. a form creating a record.

    Make it a field of the main view, not of its router, rather than repeat a view on each
    page. Its view fields are its content, laid out in a column on the window's left. Qt
    docks it, and Textual shows it left of the scrolling content. The web shows a column
    left of the pages, and on a phone a drawer that a button in the header opens. The user
    retracts it to a narrow strip, and back, with a button (`is_expanded`).
    """

    _renderer_key = "sidebar"

    #: a heading above the content; none while empty
    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: the button retracting and expanding the sidebar (opening the drawer on a phone),
    #: for screen readers and as its tooltip
    toggle_text: str = attrs.field(default=T("Sidebar"), metadata={UI_TEXT: True})
    #: whether the content shows, else a narrow strip with the button bringing it back.
    #: Layout, not study data: never saved, loaded or reset, but kept with the session
    #: (`SESSION`)
    is_expanded: bool = attrs.field(default=True, metadata={OMIT: True, SESSION: True})
    #: the user retracted or expanded the sidebar; not emitted when `is_expanded` is set in code
    toggled: Signal[bool] = attrs.Factory(Signal[bool])
