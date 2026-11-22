"""The web renderers of the page itself: the main view, its sidebar, and its router."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Final

from markupsafe import Markup
from typing_extensions import override

from composeui.core._views.actions import OpenFileAction
from composeui.core.renderer import MainRenderer
from composeui.core.view import (
    DialogView,
    FormRowView,
    MainView,
    Menu,
    PageWidth,
    Router,
    SidebarView,
    StatusBar,
    ToolBar,
    View,
)
from composeui.webcore.downloads import Downloads, downloads_marker
from composeui.webcore.icons import icon_url
from composeui.webcore.page import NO_LINKS, get_page, jobs_poller, reload_poller
from composeui.webcore.rendertarget import _RENDER_TARGET, RenderTarget, call_in_session

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from composeui.core.view import DownloadedFile
from composeui.webcore._renderers.actions import Placement, WebActionRenderer
from composeui.webcore._renderers.containers import WebPageRenderer
from composeui.webcore._renderers.dialogs import WebDialogRenderer
from composeui.webcore.webrenderer import WebRenderer, _icon, _is_shown, _view_html


class WebSidebarRenderer(WebRenderer[SidebarView]):
    """An `<aside>`: its title, then its views in a column, left of the pages.

    The main renderer wraps it in a daisyUI drawer (`drawer_html`): a column beside the
    pages on a wide screen, and on a phone a drawer over them, closed by a click beside
    it. A button in the header (`toggle_html`; see `page.js`) retracts and expands the
    column, which the browser does before posting it (`toggle`), like every control
    never swapped back after one. On a phone, it shows and hides the drawer instead.
    The button isn't in the aside's fragment: a swap of the aside brings it along.
    """

    _role = "sidebar"

    def __init__(self, view: SidebarView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(("title", "toggle_text", "is_expanded"), self._mark_dirty)
        )

    @override
    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    @property
    def drawer_id(self) -> str:
        """The id of the drawer's checkbox, checked while the drawer shows on a phone."""
        return f"{self.widget_id}-drawer"

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        title = self._view.title
        heading = (
            Markup('<h2 class="font-semibold text-primary">{}</h2>').format(title) if title else ""
        )
        content = Markup("").join(
            _view_html(view) for view in self._view.children_views if _is_shown(view)
        )
        name = title or self._view.toggle_text
        retracted = "" if self._view.is_expanded else " data-retracted"
        # bottom padding keeps the last view clear of the fixed status bar
        aside = Markup(
            '<aside {root_attributes}{retracted} aria-label="{name}"'
            ' class="cui-sidebar flex min-h-full w-80 max-w-[85vw] flex-col gap-6 border-r'
            ' border-base-300 bg-base-100 p-4 pb-20">{heading}{content}</aside>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            retracted=retracted,
            name=name,
            heading=heading,
            content=content,
        )
        return aside + self.toggle_html(oob=True) if oob else aside

    def toggle_html(self, *, oob: bool = False) -> Markup:
        """Get the header's button retracting and expanding the sidebar.

        `aria-expanded` tells whether the column shows; the page's script keeps it
        telling whether the drawer shows on a phone.
        """
        swap = Markup(' hx-swap-oob="true"') if oob else ""
        expanded = "true" if self._view.is_expanded else "false"
        text = self._view.toggle_text
        # posted by the page's script on a wide screen only, once the column has changed,
        # with whether it is now expanded
        return Markup(
            '<button id="{widget_id}-toggle" type="button"{swap}'
            ' class="btn btn-ghost btn-square btn-sm"'
            ' data-sidebar-toggle="{drawer_id}" aria-controls="{widget_id}"'
            ' aria-expanded="{expanded}" aria-label="{text}" title="{text}"'
            ' hx-post="/widget/{widget_id}" hx-trigger="sidebar-toggle"'
            """ hx-vals='{{"event": "toggle"}}' hx-swap="none">"""
            "{sidebar_icon}</button>"
        ).format(
            widget_id=self.widget_id,
            swap=swap,
            drawer_id=self.drawer_id,
            expanded=expanded,
            text=text,
            sidebar_icon=_icon("sidebar", "size-5"),
        )

    @override
    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "toggle":
            super().dispatch(event, form)
        is_expanded = form.get("expanded") == "true"
        if is_expanded == self._view.is_expanded:
            return
        with self.stop_refresh():
            self._view.is_expanded = is_expanded
        self._view.toggled.emit(is_expanded)

    def drawer_html(self, content: str) -> Markup:
        """Lay out `content`, the pages' column, beside the sidebar, in a drawer on a phone."""
        return Markup(
            '<div class="cui-drawer drawer lg:drawer-open">'
            '<input id="{drawer_id}" type="checkbox" class="drawer-toggle"'
            ' tabindex="-1" aria-hidden="true">'
            '<div class="drawer-content">{content}</div>'
            '<div class="drawer-side z-30">'
            '<label for="{drawer_id}" class="drawer-overlay"'
            ' aria-label="{toggle_text}"></label>'
            "{to_html}</div></div>"
        ).format(
            drawer_id=self.drawer_id,
            content=content,
            toggle_text=self._view.toggle_text,
            to_html=self.to_html(),
        )


#: the main column's width, following the shown page's `PageView.width`: switching pages
#: only swaps the router, so CSS picks the width from the page neither hidden nor in a
#: hidden element
_MAIN_WIDTHS = (
    " has-[[data-width=wide]:not([hidden],[hidden]_*)]:max-w-6xl"
    " has-[[data-width=full]:not([hidden],[hidden]_*)]:max-w-none"
)


def page_path(route: str) -> str:
    """Get the address of the page on `route` (routes are made to fit in one)."""
    return f"/{route}"


class WebRouterRenderer(WebRenderer[Router]):
    """The current page, and the toolbar of the pages' links.

    Only the current page is sent, in a slot of its own, which leaves the page's own
    `is_visible` to the page. An app's many pages don't weigh on each response, nor the
    browser's page. Navigating swaps the router, so the page left goes, and the page
    shown comes as it stands now. The toolbar has no fragment of its own: the main
    renderer puts it in the header, and each link swaps on its own.
    """

    _role = "router"
    #: read by `Router`: it renders only the page shown, and this renderer the others once shown
    renders_on_demand = True

    def __init__(self, view: Router) -> None:
        super().__init__(view)
        self._refresh_dispatcher["current_route"] = self._refresh_current_route

    @override
    def render(self) -> None:
        super().render()
        for page in self._view.pages:
            if page.renderer is None:  # not shown, so not built by the router's view
                renderer = WebPageRenderer(page)
                page.renderer = renderer
                renderer.render()
                renderer.defer()
        # not the toolbar: apart from the pages, like Qt's, it still switches them
        self._adopt(self._view.pages)
        # the children are rendered first: make each page's action a link to it
        for page in self._view.pages:
            assert isinstance(page.action.renderer, WebActionRenderer)
            page.action.renderer.placement = Placement.PAGE
            page.action.renderer.href = page_path(page.route)

    def _refresh_current_route(self, view: Router, rendered_object: str, value: str) -> None:
        page = self._view.page(value)
        if page is not None:
            assert isinstance(page.renderer, WebPageRenderer)  # rendered with the router
            page.renderer.build()
        self._mark_dirty(view, rendered_object, value)

    @override
    def shows(self, child: WebRenderer[Any]) -> bool:
        return self.is_current(child)

    def is_current(self, page: WebRenderer[Any]) -> bool:
        """Whether `page` is the renderer of the page shown."""
        return any(
            view.renderer is page and view.route == self._view.current_route
            for view in self._view.pages
        )

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        slots: list[str] = []
        for page in self._view.pages:
            assert isinstance(page.renderer, WebRenderer)  # a page's, which the web has
            if page.route == self._view.current_route:
                slots.append(
                    Markup('<div data-route="{route}">{to_html}</div>').format(
                        route=page.route, to_html=page.renderer.to_html()
                    )
                )
        return Markup("<div {}>{}</div>").format(
            self._root_attributes(oob=oob), Markup("").join(slots)
        )

    def toolbar_html(self) -> Markup:
        links = Markup("").join(
            page.action.renderer.to_html()
            for page in self._view.pages
            if isinstance(page.action.renderer, WebActionRenderer)
        )
        # a row of its own under the brand on a narrow screen, next to it on a wider one
        return Markup(
            '<nav aria-label="Pages" data-cui="page_tabs" class="tabs tabs-box tabs-sm order-last'
            ' w-full flex-nowrap overflow-x-auto sm:order-none sm:w-auto">{}</nav>'
        ).format(links)


#: first segments of the backend's own addresses, which no page's address can take
RESERVED_ROUTES: Final = frozenset({"icon", "jobs", "reload", "state", "static", "style", "widget"})


def check_routes(main_view: MainView) -> None:
    """Raise `ValueError` if a page of the main view's router has an address the backend uses."""
    router = next((view for view in main_view.children_views if isinstance(view, Router)), None)
    reserved = sorted(
        page.route for page in (router.pages if router else []) if page.route in RESERVED_ROUTES
    )
    if len(reserved) > 0:
        msg = f"The web backend uses the address of the routes {reserved}: rename them."
        raise ValueError(msg)


def _theme_option(choice: str, text: str) -> Markup:
    # picked by `page.js`, which also closes the dropdown
    return Markup(
        '<li><button type="button" class="theme-option" data-theme-option="{}">{}</button></li>'
    ).format(choice, text)


#: the header's Theme menu: Light, Dark, or System (the browser's preference). Its button
#: shows the theme in use, the sun or the moon, however it was chosen
_THEME_MENU: Final = Markup(
    '<div class="dropdown dropdown-end">'
    '<div tabindex="0" role="button" class="theme-toggle btn btn-ghost btn-sm btn-square"'
    ' aria-label="Theme" title="Theme">'
    '<svg class="icon-sun size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41'
    'M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>'
    "</svg>"
    '<svg class="icon-moon size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg></div>'
    '<ul tabindex="0" class="menu dropdown-content z-30 mt-2 w-40 rounded-box border'
    ' border-base-300 bg-base-100 p-2 shadow-lg">'
    "{theme_option}{theme_option2}"
    "{theme_option3}</ul></div>"
).format(
    theme_option=_theme_option("composeui", "Light"),
    theme_option2=_theme_option("composeui-dark", "Dark"),
    theme_option3=_theme_option("system", "System"),
)


class WebMainRenderer(MainRenderer[MainView, str]):
    """Renders the whole page; never swapped itself, so its attributes are no-ops."""

    draws_on_main_thread = False
    saves_in_place = False  # `state_filepath` is the name of the user's file, not a path here

    def __init__(self, view: MainView) -> None:
        super().__init__(view)
        #: set by `MainView.close()` (the Exit action); the route then ends the session
        self.is_closed = False
        #: the files `MainView.download` gave, until the page fetches them
        self.downloads = Downloads()
        self._target: RenderTarget | None = None
        self._refresh_dispatcher.update(
            dict.fromkeys(
                (
                    "is_visible",
                    "is_enabled",
                    "minimum_width",
                    "minimum_height",
                    "state_filepath",
                    # in the page's header and `<title>`: the session swaps them
                    "title",
                ),
                self._noop,
            )
        )

    @property
    def router(self) -> Router | None:
        """The main view's router, whose pages have addresses; None without one."""
        return next((view for view in self._view.children_views if isinstance(view, Router)), None)

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = f"cui-{id(self._view)}-main"
            self._target = _RENDER_TARGET.get()
        check_routes(self._view)
        # the children are rendered first: hand the Open actions the file type they load
        views: list[View] = list(self._view.children_views)
        while len(views) > 0:
            view = views.pop()
            views.extend(view.children_views)
            if isinstance(view, OpenFileAction) and isinstance(view.renderer, WebActionRenderer):
                view.renderer.accept = self._view.extension

    @override
    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        call_in_session(self._target, callback)

    def page_html(
        self,
        reload_instance: str | None = None,
        *,
        session_tag: str = "",
        style_links: Markup = NO_LINKS,
    ) -> str:
        """Get the whole page; with `reload_instance`, it reloads once its server restarts.

        Its requests carry `session_tag`, the `WebSession.page_tag` of its session, if any.
        It loads the app's stylesheets of `style_links`.
        """
        menus: list[str] = []
        toolbars: list[str] = []
        content: list[str] = []
        status_bar = ""
        toolbar = ""
        sidebar: WebSidebarRenderer | None = None
        for child_view in self._view.children_views:
            if isinstance(child_view, FormRowView):
                content.append(_view_html(child_view))  # its parts, as a form shows them
                continue
            if not isinstance(child_view.renderer, WebRenderer):
                continue
            if isinstance(child_view, DialogView) or child_view is self._view.notification:
                continue  # see `_dialogs_html`, and `notification` below
            if isinstance(child_view, StatusBar):
                status_bar = child_view.renderer.to_html()
            elif isinstance(child_view, Menu):
                menus.append(child_view.renderer.to_html())
            elif isinstance(child_view, ToolBar):
                toolbars.append(child_view.renderer.to_html())
            elif isinstance(child_view.renderer, WebSidebarRenderer):
                sidebar = child_view.renderer
            else:
                if child_view is self.router and isinstance(child_view.renderer, WebRouterRenderer):
                    toolbar = child_view.renderer.toolbar_html()
                content.append(child_view.renderer.to_html())
        # the pages' toolbar wraps to a row of its own on a narrow screen
        wrap = " flex-wrap" if toolbar else ""
        bar = self._view.notification.renderer
        notification = bar.to_html() if isinstance(bar, WebRenderer) else Markup()
        # bottom padding keeps the last row clear of the fixed status bar; the notification
        # goes above the card, outside it: it isn't the page's content
        main = Markup(
            '<main data-cui="content" class="mx-auto {} px-4 pt-8 pb-20">'
            "{}"
            '<div data-cui="card" class="card border border-base-300 bg-base-100 shadow-md">'
            '<div class="card-body gap-6 p-6">'
            "{}"
            "</div></div></main>"
        ).format(
            {
                PageWidth.NARROW: "max-w-3xl",
                PageWidth.WIDE: "max-w-6xl",
                PageWidth.FULL: "max-w-none",
            }[self._view.width]
            + _MAIN_WIDTHS,
            notification,
            Markup("").join(content),
        )
        return get_page(
            self._view.title,
            # sticky: the menus stay at hand however long the form is
            Markup(
                '<header data-cui="header" class="navbar sticky top-0 z-20 min-h-14{wrap} gap-3'
                " border-b border-base-300"
                ' bg-base-100 px-4">'
                "{value}{brand_html}{toolbar}"
                '<nav class="ml-auto flex items-center gap-1">'
                "{join}{join2}</nav>"
                "{THEME_MENU}"
                "</header>"
                "{value2}"
                "{status_bar}{dialogs_html}"
            ).format(
                wrap=wrap,
                value=sidebar.toggle_html() if sidebar else "",
                brand_html=self.brand_html(),
                toolbar=toolbar,
                join=Markup("").join(toolbars),
                join2=Markup("").join(menus),
                THEME_MENU=_THEME_MENU,
                value2=sidebar.drawer_html(main) if sidebar else main,
                status_bar=status_bar,
                dialogs_html=self._dialogs_html(),
            ),
            self._view.language,
            pollers=jobs_poller(is_running=self._view.jobs.is_running)
            + reload_poller(reload_instance),
            max_upload_size=self._view.max_upload_size,
            session_tag=session_tag,
            icon=self._app_icon_url(),
            downloads=downloads_marker(self.downloads.tickets()),
            style_links=style_links,
        )

    def _app_icon_url(self) -> str | None:
        app_icon = self._view.app_icon
        return None if app_icon is None else icon_url(str(app_icon))

    def _dialogs_html(self) -> Markup:
        """Render every dialog of the tree, outside the pages hiding their content."""
        dialogs: list[str] = []
        views: list[View] = list(self._view.children_views)
        while len(views) > 0:
            view = views.pop(0)
            views.extend(view.children_views)
            if isinstance(view, DialogView) and isinstance(view.renderer, WebDialogRenderer):
                dialogs.append(view.renderer.to_html())
        return Markup("").join(dialogs)

    def brand_html(self, *, oob: bool = False) -> Markup:
        """Show the app's title after its icon, or a badge of its initial without one."""
        title = self._view.title
        url = self._app_icon_url()
        badge = (
            Markup(
                '<span aria-hidden="true" class="grid size-8 shrink-0 place-items-center'
                ' rounded-field bg-primary text-sm font-bold text-primary-content">{}</span>'
            ).format(title.strip()[:1].upper())
            if url is None
            else Markup(
                '<img src="{}" alt="" aria-hidden="true" class="size-8 shrink-0 object-contain">'
            ).format(url)
        )
        swap = Markup(' hx-swap-oob="true"') if oob else ""
        return (
            # on a narrow screen, the title gives way to the header's buttons rather than
            # pushing them to a row of their own
            Markup(
                '<div id="cui-brand"{swap} data-cui="brand" class="flex min-w-0 flex-1 basis-0'
                ' items-center gap-2 sm:flex-none sm:basis-auto">'
                "{badge}"
                '<h1 class="truncate text-lg font-semibold">{title}</h1></div>'
            ).format(swap=swap, badge=badge, title=title)
        )

    @override
    def close(self) -> None:
        self.is_closed = True

    @override
    def open_file(self) -> Path | None:
        # no browser-side path to return: the web backend uploads instead (M7), and
        # None is what `FileMenu`'s callbacks already treat as "cancelled"
        return None

    @override
    def save_file(self) -> Path | None:
        return None  # see `open_file`; saving is a browser download (M7)

    @override
    def download(self, file: DownloadedFile) -> None:
        # the session's next answer names it (`downloads_marker`)
        self.downloads.add(file)

    @staticmethod
    def _noop(_view: MainView, _rendered_object: str, _value: Any) -> None:
        pass
