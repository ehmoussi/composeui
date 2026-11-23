"""Textual main view, sidebar and router."""

from __future__ import annotations

import functools
import logging
from collections import deque
from typing import TYPE_CHECKING, Any, cast

from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import ContentSwitcher
from textual_fspicker import FileOpen, FileSave
from textual_fspicker.path_filters import Filter, Filters
from typing_extensions import override

from composeui.core._views.files import save_download
from composeui.core.renderer import MainRenderer
from composeui.core.view import (
    MainView,
    NotificationBar,
    Router,
    SidebarView,
    StatusBar,
    ToolBar,
    View,
)
from composeui.textualcore._renderers.actions import TextualActionRenderer, _ComposeUIApp
from composeui.textualcore._renderers.containers import TextualPageRenderer
from composeui.textualcore._renderers.dialogs import TextualDialogRenderer
from composeui.textualcore._renderers.files import _has_any_extension
from composeui.textualcore._renderers.forms import _widget_of
from composeui.textualcore.textualrenderer import TextualWidgetRenderer, _call_on_app_thread
from composeui.textualcore.widgets.composesidebar import ComposeSidebar
from composeui.textualcore.widgets.composetoolbar import (
    ComposeToolbar,
    ComposeToolbarButton,
    ComposeToolbars,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from textual.widget import Widget

    from composeui.core.view import DownloadedFile, StreamContent


LOGGER = logging.getLogger("COMPOSEUI")


def _logging_errors(callback: Callable[[], None]) -> None:
    """Call a job's `callback`, which no thread waits for: its error is only logged.

    Textual ends the app at an error in a message's handler; Qt, here, goes on.
    """
    try:
        callback()
    except Exception:
        LOGGER.exception("A job's callback failed")


class TextualSidebarRenderer(TextualWidgetRenderer[SidebarView, ComposeSidebar]):
    """A column on the screen's left: its title and an arrow retracting it, then its views."""

    def __init__(self, view: SidebarView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "toggle_text": self._refresh_toggle_text,
                "is_expanded": self._refresh_is_expanded,
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
            self._rendered_object = ComposeSidebar(*widgets)
            self._rendered_object.toggled.connect(self._update_expanded)

    @staticmethod
    def _refresh_title(_view: SidebarView, rendered_object: ComposeSidebar, value: str) -> None:
        rendered_object.set_title(value)

    @staticmethod
    def _refresh_toggle_text(
        _view: SidebarView, rendered_object: ComposeSidebar, value: str
    ) -> None:
        rendered_object.toggle.tooltip = Content(value)

    @staticmethod
    def _refresh_is_expanded(
        _view: SidebarView, rendered_object: ComposeSidebar, value: bool
    ) -> None:
        rendered_object.set_expanded(value)

    def _update_expanded(self, is_expanded: bool) -> None:
        with self.stop_refresh():
            self._view.is_expanded = is_expanded
        self._view.toggled.emit(is_expanded)


class TextualRouterRenderer(TextualWidgetRenderer[Router, ContentSwitcher]):
    """The pages, one shown at a time, and a toolbar of their actions docked at the top.

    Each page sits in a slot of its own: the switcher shows and hides its slots, which
    leaves the page's own `is_visible` to the page.
    """

    def __init__(self, view: Router) -> None:
        super().__init__(view)
        #: the toolbar of the pages' actions, docked by the main renderer
        self.toolbar: ComposeToolbar | None = None
        self._refresh_dispatcher.update({"current_route": self._refresh_current_route})

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            buttons: list[Widget] = []
            slots: list[Widget] = []
            for page in self._view.pages:
                assert isinstance(page.action.renderer, TextualActionRenderer)
                button = ComposeToolbarButton()
                button.triggered.connect(page.action.triggered.emit)
                page.action.renderer.button = button
                buttons.append(button)
                page_widgets = (
                    [page.renderer.widget]
                    if isinstance(page.renderer, TextualPageRenderer)
                    and page.renderer.widget is not None
                    else []
                )
                slot = Vertical(*page_widgets, id=_slot_id(page.route))
                slot.styles.height = "auto"
                slots.append(slot)
            self.toolbar = ComposeToolbar(*buttons)
            self._rendered_object = ContentSwitcher(
                *slots, initial=_slot_id(self._view.current_route)
            )

    @staticmethod
    def _refresh_current_route(_view: Router, rendered_object: ContentSwitcher, value: str) -> None:
        rendered_object.current = _slot_id(value)


def _slot_id(route: str) -> str:
    """Get the id of a page's slot in its router's switcher (routes are valid ids)."""
    return f"page-{route}"


class TextualMainRenderer(MainRenderer[MainView, _ComposeUIApp]):
    def __init__(self, view: MainView) -> None:
        super().__init__(view)
        #: the downloads not asked yet: each waits for the save dialog of the one before
        self._downloads: deque[DownloadedFile] = deque()
        self._is_asking = False
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "is_visible": self._noop,
                "is_enabled": self._noop,
                "minimum_width": self._noop,
                "minimum_height": self._noop,
                "state_filepath": self._noop,
            }
        )

    @property
    def app(self) -> _ComposeUIApp | None:
        return self._rendered_object

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = _ComposeUIApp(self._view, self._root_widget())
            views: deque[View] = deque(self._view.children_views)
            while views:
                view = views.popleft()
                if isinstance(view.renderer, TextualDialogRenderer):
                    view.renderer.app = self._rendered_object
                views.extend(view.children_views)
            self.refresh()

    def _root_widget(self) -> Widget:
        """Lay out the screen: the toolbars and the status bar docked, the rest scrolling.

        `StatusBar` is docked to the real bottom of the terminal (see
        `TextualStatusBarRenderer`) and the toolbars to the top. Everything else goes in
        a `VerticalScroll` so content taller than the screen stays reachable instead of
        clipped, beside the sidebar, if any, scrolling on its own. The notification goes
        above it: shown however far the content scrolls.
        """
        notifications: list[Widget] = []
        scrollable: list[Widget] = []
        toolbars: list[Widget] = []
        docked: list[Widget] = []
        sidebars: list[Widget] = []
        # not a view no widget shows, e.g. a menu: Textual has its actions' keys instead
        shown = [
            (child_view, widget)
            for child_view in self._view.children_views
            if (widget := _widget_of(child_view)) is not None
        ]
        for child_view, widget in shown:
            if isinstance(child_view, StatusBar):
                docked.append(widget)
            elif isinstance(child_view, NotificationBar):
                notifications.append(widget)
            elif isinstance(child_view, ToolBar):
                toolbars.append(widget)
            elif isinstance(child_view, SidebarView):
                sidebars.append(widget)
            elif isinstance(child_view.renderer, TextualRouterRenderer):
                assert child_view.renderer.toolbar is not None
                toolbars.append(child_view.renderer.toolbar)
                scrollable.append(widget)
            else:
                scrollable.append(widget)
        if len(toolbars) > 0:
            docked.append(ComposeToolbars(*toolbars))
        content: Widget = Vertical(*notifications, VerticalScroll(*scrollable))
        if len(sidebars) > 0:
            # beside the content, scrolling on its own: shown whatever the page
            content = Horizontal(*sidebars, content)
        return Vertical(content, *docked)

    @override
    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        _call_on_app_thread(self._rendered_object, callback)

    @override
    def post_on_main_thread(self, callback: Callable[[], None]) -> None:
        # `call_from_thread` waits for the callback: a job holding the model's lock, whose
        # callback asks for it, would stop both
        app = self._rendered_object
        if app is not None and app.is_running:
            app.call_later(functools.partial(_logging_errors, callback))
        else:
            _call_on_app_thread(app, callback)

    @override
    def refresh(self) -> None:
        # see `TextualWidgetRenderer.refresh` - same cross-thread hazard applies here.
        self.call_on_main_thread(super().refresh)

    @override
    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        self.call_on_main_thread(functools.partial(super().refresh_attribute, attr_name, value))

    @override
    def close(self) -> None:
        assert self._rendered_object is not None
        self._rendered_object.exit()

    @override
    def open_file(self) -> Path | None:
        """Return an existing file selected by the user.

        Must be called from a worker thread (see `_ComposeUIApp.action_trigger`).
        `call_from_thread` blocks the calling thread while the modal runs on the
        app's own thread, which would deadlock if they were the same thread.
        """
        assert self._rendered_object is not None
        app = self._rendered_object

        async def _show() -> Path | None:
            return await app.push_screen_wait(FileOpen(filters=self._build_filters()))

        # mypy can't resolve `call_from_thread`'s `CallThreadReturnType` from an async
        # callback; the return type is verified manually via `_show`'s own annotation.
        result = cast("Path | None", app.call_from_thread(_show))  # type: ignore[arg-type]
        return self._apply_default_extension(result)

    @override
    def save_file(self) -> Path | None:
        """Return a file path selected by the user to save to.

        See `open_file` for why this must be called from a worker thread.
        """
        assert self._rendered_object is not None
        app = self._rendered_object

        async def _show() -> Path | None:
            return await app.push_screen_wait(FileSave(filters=self._build_filters()))

        # mypy can't resolve `call_from_thread`'s `CallThreadReturnType` from an async
        # callback; the return type is verified manually via `_show`'s own annotation.
        result = cast("Path | None", app.call_from_thread(_show))  # type: ignore[arg-type]
        return self._apply_default_extension(result)

    @override
    def download(self, file: DownloadedFile) -> None:
        # from a file action's worker too (`_ComposeUIApp.trigger`)
        self.call_on_main_thread(functools.partial(self._queue_download, file))

    @override
    def open_url(self, url: str) -> bool:
        app = self._rendered_object
        if app is None or not app.is_web:
            return False  # in a terminal, the desktop's browser, if the app reaches it
        # in a browser (``textual-serve``), a new tab of it
        self.call_on_main_thread(functools.partial(app.open_url, url))
        return True

    def _queue_download(self, file: DownloadedFile) -> None:
        self._downloads.append(file)
        if not self._is_asking:
            self._ask_download()

    def _ask_download(self) -> None:
        """Ask where to save the oldest download waiting, if any."""
        app = self._rendered_object
        self._is_asking = len(self._downloads) > 0 and app is not None and app.is_running
        if self._is_asking:
            assert app is not None
            file = self._downloads.popleft()
            app.push_screen(
                FileSave(default_file=file.filename),
                functools.partial(self._save_download, file.content),
            )

    def _save_download(self, content: bytes | Path | StreamContent, path: Path | None) -> None:
        if path is not None:
            save_download(self._view, path, content)
        self._ask_download()

    def _build_filters(self) -> Filters:
        return Filters(
            *(
                Filter(name, functools.partial(_has_any_extension, extensions=extensions))
                for name, extensions in self._view.file_view.extensions.items()
            )
        )

    def _apply_default_extension(self, filepath: Path | None) -> Path | None:
        if filepath is None:
            return None
        all_extensions: tuple[str, ...] = tuple(
            e for exts in self._view.file_view.extensions.values() for e in exts
        )
        if all_extensions and not _has_any_extension(filepath, all_extensions):
            filepath = filepath.with_name(filepath.name + all_extensions[0])
        return filepath

    @staticmethod
    def _refresh_title(_view: MainView, rendered_object: _ComposeUIApp, value: str) -> None:
        rendered_object.title = value

    @staticmethod
    def _noop(_view: MainView, _rendered_object: _ComposeUIApp, _value: Any) -> None:
        pass
