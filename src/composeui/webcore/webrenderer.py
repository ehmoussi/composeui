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

from composeui.core.renderer import (
    MainRenderer,
    NoRenderedObjectError,
    Renderer,
    RendererContainer,
    ViewLike,
)
from composeui.core.view import FormLabelRowView, LogType, MainView, StatusBar
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


class TextFieldViewLike(ViewLike, Protocol):
    placeholder: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


TTextField = TypeVar("TTextField", bound=TextFieldViewLike)


class _WebTextFieldRenderer(WebRenderer[TTextField]):
    """A text field posting debounced edits (`input`) and committed edits (`change`)."""

    def to_html(self, *, oob: bool = False) -> str:
        # `hx-swap="none"`: the field being typed in is never swapped back (it would
        # reset the caret); everything else arrives out of band. `queue all` keeps a
        # `change` from being dropped behind an in-flight debounced edit.
        disabled = "" if self._view.is_enabled else " disabled"
        return (
            f'<input {self._root_attributes(oob=oob)} class="input validator w-full" type="text"'
            f' name="value" value="{html.escape(self._text())}"'
            f' placeholder="{html.escape(self._view.placeholder)}"{self._extra_attributes()}'
            f' hx-post="/widget/{self.widget_id}"'
            ' hx-trigger="input changed delay:300ms, change"'
            ' hx-vals="js:{event: event.type}" hx-swap="none" hx-sync="this:queue all"'
            f"{disabled}>"
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event not in ("input", "change"):
            super().dispatch(event, form)
        # `change` carries the text too: it can overtake a still-debounced `input`,
        # which then posts the same text again and must not re-emit
        text = form.get("value", "")
        if text != self._posted_text():
            self._apply_text(text)
            self._view.text_changed.emit(text)
            self._view.text_edited.emit(text)
        if event == "change":
            self._view.editing_finished.emit()

    @abstractmethod
    def _text(self) -> str:
        """Text to show in the field, from the view's state."""

    @abstractmethod
    def _posted_text(self) -> str:
        """Text the browser last posted (or was last shown)."""

    @abstractmethod
    def _apply_text(self, text: str) -> None:
        """Store the browser's `text` into the view, without refreshing the field."""

    def _extra_attributes(self) -> str:
        return ""


class InputViewLike(TextFieldViewLike, Protocol):
    text: str


class WebInputRenderer(_WebTextFieldRenderer[InputViewLike]):
    _role = "input"

    def __init__(self, view: InputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._mark_dirty,
                "placeholder": self._mark_dirty,
            }
        )

    def _text(self) -> str:
        return self._view.text

    def _posted_text(self) -> str:
        return self._view.text

    def _apply_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text


class FloatInputViewLike(TextFieldViewLike, Protocol):
    value: float | None
    minimum: float | None
    maximum: float | None
    decimals: int | None


#: an optionally signed decimal number, partial input ("-", "1.") included
_DECIMAL_PATTERN = r"[+\-]?[0-9]*([.][0-9]*)?([eE][+\-]?[0-9]*)?"


class WebFloatInputRenderer(_WebTextFieldRenderer[FloatInputViewLike]):
    """A decimal text field.

    Not `type="number"`: while typing e.g. "-5" its value reads "" for the transient
    "-", indistinguishable from a cleared field. A text field posts the raw text and
    unparsable text is ignored, the same as the Qt/Textual float inputs. Like Textual,
    `minimum`/`maximum`/`decimals` are tracked on the view but not enforced on input.
    """

    _role = "float_input"

    def __init__(self, view: FloatInputViewLike) -> None:
        super().__init__(view)
        self._last_posted_text: str | None = None
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._mark_dirty,
                "minimum": self._mark_dirty,
                "maximum": self._mark_dirty,
                "decimals": self._mark_dirty,
            }
        )

    def _refresh_value(self, view: FloatInputViewLike, rendered_object: str, value: Any) -> None:
        self._last_posted_text = None  # the server's value wins over what was typed
        self._mark_dirty(view, rendered_object, value)

    def _text(self) -> str:
        return str(self._view.value) if self._view.value is not None else ""

    def _posted_text(self) -> str:
        return self._last_posted_text if self._last_posted_text is not None else self._text()

    def _apply_text(self, text: str) -> None:
        self._last_posted_text = text
        # transient invalid text while typing (e.g. "-", "1e"); ignore it
        with self.stop_refresh(), contextlib.suppress(ValueError):
            self._view.value = float(text) if text != "" else None

    def _extra_attributes(self) -> str:
        return f' inputmode="decimal" pattern="{_DECIMAL_PATTERN}"'


class LabelViewLike(ViewLike, Protocol):
    text: str


class WebLabelRenderer(WebRenderer[LabelViewLike]):
    _role = "label"

    def __init__(self, view: LabelViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> str:
        return f"<span {self._root_attributes(oob=oob)}>{html.escape(self._view.text)}</span>"


class WebFormLabelRenderer(WebRenderer[FormLabelRowView]):
    """The label of a form row, pointing at the row's field for clicks/screen readers."""

    _role = "form_label"

    def __init__(self, view: FormLabelRowView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"label": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> str:
        return (
            f'<label {self._root_attributes(oob=oob)} for="{self._field_id()}"'
            f' class="label text-sm font-medium">{html.escape(self._view.label)}</label>'
        )

    def _field_id(self) -> str:
        if not isinstance(self._view.renderer, RendererContainer):
            raise NoRenderedObjectError
        field_renderer = self._view.renderer.get_renderer("field")
        if not isinstance(field_renderer, WebRenderer):
            raise NoRenderedObjectError
        return field_renderer.widget_id


class LogViewLike(ViewLike, Protocol):
    log_message: str
    log_type: LogType


_LOG_CLASSES: Final[dict[LogType, str]] = {
    LogType.ERROR: "text-error",
    LogType.WARNING: "text-warning",
    LogType.INFO: "text-info",
}


class WebLogRenderer(WebRenderer[LogViewLike]):
    _role = "log"

    def __init__(self, view: LogViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "log_message": self._mark_dirty,
                "log_type": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> str:
        attributes = self._root_attributes(oob=oob)
        if self._view.is_visible and self._view.log_message == "":
            attributes += " hidden"  # same as Qt/Textual: an empty log takes no room
        # `pre-line`: `FormView.validate` joins its messages with newlines
        return (
            f'<p {attributes} aria-live="polite"'
            f' class="text-sm whitespace-pre-line {_LOG_CLASSES[self._view.log_type]}">'
            f"{html.escape(self._view.log_message)}</p>"
        )


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
    "float_input": WebFloatInputRenderer,
    "form_label": WebFormLabelRenderer,
    "input": WebInputRenderer,
    "label": WebLabelRenderer,
    "log": WebLogRenderer,
    "main": WebMainRenderer,
    "status_bar": WebStatusBarRenderer,
}
