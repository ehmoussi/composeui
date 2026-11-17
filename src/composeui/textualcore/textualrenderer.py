"""The Textual renderer base and shared thread and mount helpers."""

from __future__ import annotations

import functools
from collections import deque
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from textual.types import NoActiveAppError

from composeui.core.renderer import Renderer, RendererContainer, ViewLike
from composeui.core.view import FormRowView, View

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import App
    from textual.widget import Widget


TView = TypeVar("TView", bound=ViewLike)


TWidget = TypeVar("TWidget", bound="Widget")


def _app_of(widget: Widget) -> App[Any] | None:
    """Get the app running `widget`, or None before it is mounted."""
    try:
        return widget.app
    except NoActiveAppError:
        return None


def _call_on_app_thread(app: App[Any] | None, callback: Callable[[], None]) -> None:
    """Marshal `callback` onto the thread running `app`'s event loop.

    `App.call_from_thread` raises `RuntimeError` both when the app isn't running yet
    and when it's called from the app's own thread (nothing to marshal in either
    case). Both fall back to calling directly, matching `Renderer`'s default. A
    `RuntimeError` of the callback itself goes to the caller: it never runs twice.
    """
    if app is None:
        callback()
        return
    started = False

    def run() -> None:
        nonlocal started
        started = True
        callback()

    try:
        app.call_from_thread(run)
    except RuntimeError:
        if started:
            raise
        callback()


#: the class a row's field widget has while the row is invalid (`FormRowView.is_invalid`),
#: styled by the composeui widgets. Not Textual's own `-invalid`: `Input` resets that one
#: from its validators on every keystroke
ROW_INVALID_CLASS = "-row-invalid"


class TextualWidgetRenderer(Renderer[TView, TWidget]):
    #: whether the widget is a form row's field, showing the row as invalid
    _marks_invalid: ClassVar[bool] = False

    def __init__(self, view: TView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "is_visible": self._refresh_visible,
                "is_enabled": self._refresh_enabled,
            }
        )
        if self._marks_invalid and isinstance(view, FormRowView):
            # only a row has these: the same renderer also draws a standalone field
            self._refresh_dispatcher.update(
                {
                    name: self._invalid_refresher(name)
                    for name in ("log_message", "log_type", "has_form_error")
                }
            )

    @property
    def widget(self) -> TWidget | None:
        return self._rendered_object

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        _call_on_app_thread(self._get_app(), callback)

    def _get_app(self) -> App[Any] | None:
        if self._rendered_object is None:
            return None
        return _app_of(self._rendered_object)

    def refresh(self) -> None:
        # Textual widgets aren't thread-safe (see `App.call_from_thread`'s own
        # docstring) - state can legitimately change from a non-main thread (e.g.
        # `MainView.load_state` running as part of a worker-dispatched file-open
        # action, see `_ComposeUIApp.action_trigger`). `call_on_main_thread` already
        # falls back to a direct call when we're already on the right thread, so this
        # is a no-op in the common case.
        self.call_on_main_thread(self._refresh_if_mounted)

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        self.call_on_main_thread(
            functools.partial(self._refresh_attribute_if_mounted, attr_name, value)
        )

    def _is_waiting_to_mount(self) -> bool:
        """Tell whether the app runs but hasn't mounted the widget yet, e.g. on a screen not shown.

        Some widgets refuse their state until mounted (a `Select` its options). Whatever
        mounts them later gives them their state then: the app's own mount, a list's new
        item, a form dialog's screen.
        """
        widget = self._rendered_object
        if widget is None or widget.is_attached:
            return False
        app = _app_of(widget)
        return app is not None and app.is_running

    def _refresh_if_mounted(self) -> None:
        if not self._is_waiting_to_mount():
            super().refresh()

    def _refresh_attribute_if_mounted(self, attr_name: str, value: Any) -> None:
        if not self._is_waiting_to_mount():
            super().refresh_attribute(attr_name, value)

    @staticmethod
    def _refresh_visible(_view: TView, rendered_object: TWidget, value: bool) -> None:
        rendered_object.display = value

    @staticmethod
    def _refresh_enabled(_view: TView, rendered_object: TWidget, value: bool) -> None:
        rendered_object.disabled = not value

    @staticmethod
    def _invalid_refresher(name: str) -> Callable[[TView, TWidget, Any], None]:
        """Mark the field once the row's attribute `name` changes to the given value."""

        def refresh(view: TView, rendered_object: TWidget, value: Any) -> None:
            is_invalid = isinstance(view, FormRowView) and view.is_invalid_once(name, value)
            rendered_object.set_class(is_invalid, ROW_INVALID_CLASS)

        return refresh


def _refresh_tree(root: View) -> None:
    """Push each view's current state into its already-built (default) widget.

    Widgets are constructed bottom-up before the app runs (mirroring the Qt
    backend), but Textual reactives like `Input.value` need a running app to be
    *set* at all. So unlike Qt, the initial state can't be pushed in during that
    same construction pass. This walks the tree once the app has mounted, when it's
    finally safe to do so.
    """
    views: deque[View] = deque([root])
    while views:
        current = views.popleft()
        if isinstance(current.renderer, (Renderer, RendererContainer)):
            current.renderer.refresh()
        views.extend(current.children_views)
