"""Web backend renderers: each view renders to an HTML fragment swapped in by htmx.

There is no live widget to mutate between requests, so a renderer's rendered object is
just the stable id of its fragment. Changing a view attribute marks the renderer dirty
in a request-scoped set (`collect_dirty`); the route then re-renders every dirty
fragment as an htmx out-of-band swap (`render_dirty`).
"""

from __future__ import annotations

import contextlib
import html
import re
import threading
import weakref
from abc import abstractmethod
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Final, TypeVar

from typing_extensions import Protocol

from composeui.core.renderer import MainRenderer, NoRenderedObjectError, Renderer, ViewLike
from composeui.core.view import MainView, StatusBar
from composeui.webcore.page import get_page

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping
    from pathlib import Path

    from composeui.core.signal import Signal, SignalNoArgs

TView = TypeVar("TView", bound=ViewLike)

#: Renderers dirtied during the current request, keyed by fragment id (insertion order
#: kept, duplicates collapsed); None outside a request, where marking is a no-op.
_DIRTY: ContextVar[dict[str, WebRenderer[Any]] | None] = ContextVar(
    "composeui_web_dirty", default=None
)
#: Fragment id -> renderer, filled at render time. Single served `MainView` for now;
#: becomes per session in M6.
_REGISTRY: weakref.WeakValueDictionary[str, WebRenderer[Any]] = weakref.WeakValueDictionary()
#: Serializes requests against the view tree, and the `StatusBar` timer thread with
#: them (see `WebRenderer.call_on_main_thread`).
_LOCK = threading.RLock()

_ID_PATTERN = re.compile(r'\sid="([^"]+)"')


class UnsupportedEventError(Exception):
    def __init__(self, renderer: WebRenderer[Any], event: str) -> None:
        super().__init__(f"{type(renderer).__name__} does not handle the event {event!r}")


@contextlib.contextmanager
def collect_dirty() -> Generator[dict[str, WebRenderer[Any]]]:
    """Collect the renderers whose view changed while the block runs."""
    dirty: dict[str, WebRenderer[Any]] = {}
    token = _DIRTY.set(dirty)
    try:
        yield dirty
    finally:
        _DIRTY.reset(token)


def render_dirty(dirty: Mapping[str, WebRenderer[Any]]) -> str:
    """Render every dirty fragment as an out-of-band swap.

    A fragment already contained in another dirty fragment (e.g. a row inside a group
    that also changed) is dropped, otherwise htmx would swap it twice.
    """
    fragments = {widget_id: renderer.to_html(oob=True) for widget_id, renderer in dirty.items()}
    nested = {
        nested_id
        for widget_id, fragment in fragments.items()
        for nested_id in _ID_PATTERN.findall(fragment)
        if nested_id != widget_id
    }
    return "".join(fragment for widget_id, fragment in fragments.items() if widget_id not in nested)


def get_renderer(widget_id: str) -> WebRenderer[Any] | None:
    return _REGISTRY.get(widget_id)


def handle_event(renderer: WebRenderer[Any], event: str, form: Mapping[str, str]) -> str:
    """Apply a browser event to `renderer`'s view and return the resulting OOB fragments."""
    with _LOCK, collect_dirty() as dirty:
        renderer.dispatch(event, form)
        return render_dirty(dirty)


def render_page(main_view: MainView) -> str:
    with _LOCK:
        if not isinstance(main_view.renderer, WebMainRenderer):
            raise NoRenderedObjectError
        return main_view.renderer.page_html()


class WebRenderer(Renderer[TView, str]):
    #: distinguishes the renderers a `RendererContainer` binds to one same view
    _role: ClassVar[str]

    def __init__(self, view: TView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "is_visible": self._mark_dirty,
                "is_enabled": self._mark_dirty,
            }
        )

    @property
    def widget_id(self) -> str:
        if self._rendered_object is None:
            raise NoRenderedObjectError
        return self._rendered_object

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = f"cui-{id(self._view)}-{self._role}"
            _REGISTRY[self._rendered_object] = self

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        with _LOCK:
            callback()

    @abstractmethod
    def to_html(self, *, oob: bool = False) -> str:
        """Render the view's fragment; `oob` marks it as an htmx out-of-band swap."""

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        """Apply a browser `event` (with its submitted `form` fields) to the view."""
        raise UnsupportedEventError(self, event)

    def _root_attributes(self, *, oob: bool) -> str:
        """Attributes of the fragment's root tag, kept even when hidden for later swaps."""
        attributes = [f'id="{self.widget_id}"']
        if not self._view.is_visible:
            attributes.append("hidden")
        if oob:
            attributes.append('hx-swap-oob="true"')
        return " ".join(attributes)

    def _mark_dirty(self, _view: TView, _rendered_object: str, _value: Any) -> None:
        dirty = _DIRTY.get()
        if dirty is not None:
            dirty[self.widget_id] = self

    @staticmethod
    def _update_state(view: TView, rendered_object: str) -> None:
        pass  # the browser posts its state with each event instead (see `dispatch`)


class InputViewLike(ViewLike, Protocol):
    placeholder: str
    text: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


class WebInputRenderer(WebRenderer[InputViewLike]):
    _role = "input"

    def __init__(self, view: InputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._mark_dirty,
                "placeholder": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> str:
        # `hx-swap="none"`: the field being typed in is never swapped back (it would
        # reset the caret); everything else arrives out of band. `queue all` keeps a
        # `change` from being dropped behind an in-flight debounced edit.
        disabled = "" if self._view.is_enabled else " disabled"
        return (
            f'<input {self._root_attributes(oob=oob)} class="input w-full" type="text" name="value"'
            f' value="{html.escape(self._view.text)}"'
            f' placeholder="{html.escape(self._view.placeholder)}"'
            f' hx-post="/widget/{self.widget_id}"'
            ' hx-trigger="input changed delay:300ms, change"'
            ' hx-vals="js:{event: event.type}" hx-swap="none" hx-sync="this:queue all"'
            f"{disabled}>"
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event not in ("input", "change"):
            super().dispatch(event, form)
        # `change` carries the value too: it can overtake a still-debounced `input`
        self._apply_text(form.get("value", ""))
        if event == "change":
            self._view.editing_finished.emit()

    def _apply_text(self, text: str) -> None:
        if text == self._view.text:
            return
        with self.stop_refresh():
            self._view.text = text
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)


class WebStatusBarRenderer(WebRenderer[StatusBar]):
    _role = "status_bar"

    def __init__(self, view: StatusBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "message": self._mark_dirty,
                "timeout": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> str:
        # docked like Qt/Textual's status bar; an empty message leaves a quiet empty line
        return (
            f'<footer {self._root_attributes(oob=oob)} role="status" aria-live="polite"'
            ' class="fixed inset-x-0 bottom-0 min-h-8 border-t border-base-300 bg-base-100'
            ' px-4 py-1 text-sm">'
            f"{html.escape(self._view.message)}"
            "</footer>"
        )


class WebMainRenderer(MainRenderer[MainView, str]):
    """Renders the whole page; never swapped itself, so its attributes are no-ops."""

    def __init__(self, view: MainView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                (
                    "is_visible",
                    "is_enabled",
                    "minimum_width",
                    "minimum_height",
                    "state_filepath",
                ),
                self._noop,
            )
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = f"cui-{id(self._view)}-main"

    def page_html(self) -> str:
        content: list[str] = []
        status_bar = ""
        for child_view in self._view.children_views:
            if not isinstance(child_view.renderer, WebRenderer):
                continue
            if isinstance(child_view, StatusBar):
                status_bar = child_view.renderer.to_html()
            else:
                content.append(child_view.renderer.to_html())
        # bottom padding keeps the last row clear of the fixed status bar
        return get_page(
            self._view.title,
            '<header class="navbar bg-base-100 px-4 shadow-sm">'
            f'<h1 class="text-lg font-semibold">{html.escape(self._view.title)}</h1>'
            "</header>"
            '<main class="mx-auto max-w-3xl p-4 pb-16">'
            '<div class="card bg-base-100 shadow-sm"><div class="card-body gap-4">'
            f"{''.join(content)}"
            "</div></div></main>"
            f"{status_bar}",
        )

    def close(self) -> None:
        pass  # sessions land in M6; nothing to close until then

    def open_file(self) -> Path | None:
        # no browser-side path to return: the web backend uploads instead (M7), and
        # None is what `FileMenu`'s callbacks already treat as "cancelled"
        return None

    def save_file(self) -> Path | None:
        return None  # see `open_file`; saving is a browser download (M7)

    @staticmethod
    def _noop(_view: MainView, _rendered_object: str, _value: Any) -> None:
        pass

    @staticmethod
    def _update_state(view: MainView, rendered_object: str) -> None:
        pass


#: renderer keys of the web backend, looked up by `composeui.core.registry.create_renderer`
RENDERERS: Final[dict[str, Callable[[Any], Renderer[Any, Any]]]] = {
    "input": WebInputRenderer,
    "main": WebMainRenderer,
    "status_bar": WebStatusBarRenderer,
}
