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
from abc import abstractmethod
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Final, Generic, TypeVar

from typing_extensions import Protocol

from composeui.core.renderer import (
    MainRenderer,
    NoRenderedObjectError,
    Renderer,
    RendererContainer,
    ViewLike,
)
from composeui.core.view import (
    ActionView,
    FormLabelRowView,
    FormRowView,
    FormView,
    GroupFormView,
    LogMixin,
    LogType,
    MainView,
    Menu,
    OpenFileAction,
    SaveAction,
    SaveAsAction,
    SeparatorAction,
    StatusBar,
)
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
#: The session whose view tree is being rendered (see `rendering_into`).
_RENDER_TARGET: ContextVar[RenderTarget | None] = ContextVar(
    "composeui_web_render_target", default=None
)

_ID_PATTERN = re.compile(r'\sid="([^"]+)"')
#: seconds a status bar waits past its message's timeout before fetching itself again
_AUTO_CLEAR_MARGIN = 0.25


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


def handle_event(renderer: WebRenderer[Any], event: str, form: Mapping[str, str]) -> str:
    """Apply a browser event to `renderer`'s view and return the resulting OOB fragments."""
    with collect_dirty() as dirty:
        renderer.dispatch(event, form)
        return render_dirty(dirty)


class RenderTarget:
    """One session's view tree: its renderers by fragment id, and the lock guarding it.

    Renderers register here as they render (see `rendering_into`), so a widget id only
    resolves within the session that rendered it: ids derive from `id()` and are
    guessable, and must not reach another session's views.
    """

    def __init__(self) -> None:
        self.renderers: dict[str, WebRenderer[Any]] = {}
        #: serializes requests against the tree, and the `StatusBar` timer thread with
        #: them (see `WebRenderer.call_on_main_thread`)
        self.lock = threading.RLock()


@contextlib.contextmanager
def rendering_into(target: RenderTarget) -> Generator[None]:
    """Register every renderer rendered while the block runs into `target`."""
    token = _RENDER_TARGET.set(target)
    try:
        yield
    finally:
        _RENDER_TARGET.reset(token)


class WebRenderer(Renderer[TView, str]):
    #: distinguishes the renderers a `RendererContainer` binds to one same view
    _role: ClassVar[str]
    #: whether a `<label for=...>` can point at the root element (a `<div>` can't)
    is_labelable: ClassVar[bool] = True

    def __init__(self, view: TView) -> None:
        super().__init__(view)
        self._lock: threading.RLock | None = None
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
            target = _RENDER_TARGET.get()
            if target is not None:
                target.renderers[self._rendered_object] = self
                self._lock = target.lock

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        if self._lock is None:
            callback()  # rendered outside any session: nothing else touches the tree
            return
        with self._lock:
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

    def _row_attributes(self) -> str:
        """ARIA links from a form row's field to the row's log and label.

        The field is described by the log, read out with the field, and is
        `aria-invalid` while the log shows an error (the page script keeps that in step
        when only the log is swapped, see `page.py`). A field a `<label for>` can't name,
        a radio group, is labelled by the row's label instead. Nothing outside a row.
        """
        attributes: list[str] = []
        log_id = self._row_part_id("log")
        if log_id is not None:
            attributes.append(f'aria-describedby="{log_id}"')
            view = self._view
            if isinstance(view, LogMixin) and view.log_message and view.log_type is LogType.ERROR:
                attributes.append('aria-invalid="true"')
        label_id = None if self.is_labelable else self._row_part_id("label")
        if label_id is not None:
            attributes.append(f'aria-labelledby="{label_id}"')
        return "".join(f" {attribute}" for attribute in attributes)

    def _row_part_id(self, part: str) -> str | None:
        container = self._view.renderer  # type: ignore[attr-defined]
        if not isinstance(container, RendererContainer):
            return None
        try:
            renderer = container.get_renderer(part)
        except KeyError:
            return None
        if not isinstance(renderer, WebRenderer) or renderer is self:
            return None
        return renderer.widget_id

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
            f"<input {self._root_attributes(oob=oob)}{self._row_attributes()}"
            ' class="input w-full" type="text"'
            f' name="value" value="{html.escape(self._text())}"'
            f' placeholder="{html.escape(self._view.placeholder)}"{self._extra_attributes()}'
            f' hx-post="/widget/{self.widget_id}"'
            ' hx-trigger="input changed delay:300ms, change"'
            ' hx-vals="js:{event: event.type}" hx-swap="none" hx-sync="this:queue all"'
            # the browser must not refill the field on reload: the server's value wins
            ' autocomplete="off"'
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


def _is_float(text: str) -> bool:
    """Whether `text` is an acceptable float field value ("" meaning no value)."""
    if text == "":
        return True
    try:
        float(text)
    except ValueError:
        return False
    return True


class WebFloatInputRenderer(_WebTextFieldRenderer[FloatInputViewLike]):
    """A decimal text field.

    Not `type="number"`: while typing e.g. "-5" its value reads "" for the transient
    "-", indistinguishable from a cleared field. A text field posts the raw text and
    unparsable text is ignored, the same as the Qt/Textual float inputs. Like Textual,
    `minimum`/`maximum`/`decimals` are tracked on the view but not enforced on input.

    Leaving the field (`change`) with unparsable text puts the value back: Qt's
    validator never lets such text in at all, and a field showing "4a" while the
    view (and its validators) still sees 4 would contradict every message around it.
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

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event == "change" and not _is_float(form.get("value", "")):
            # no `editing_finished`, as Qt doesn't emit it for unacceptable text; the
            # field itself is swapped back, which is safe now that it has been left
            self._last_posted_text = None
            self._mark_dirty(self._view, self.widget_id, self._view.value)
            return
        super().dispatch(event, form)

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


TValue = TypeVar("TValue")


class ValuesViewLike(ViewLike, Protocol, Generic[TValue]):
    value: TValue | None
    values: dict[str, TValue]
    value_changed: Signal[TValue | None]

    def serialize_value(self) -> str | None: ...

    def deserialize_value(self, label: str | None) -> TValue | None: ...


class _WebValuesRenderer(WebRenderer[ValuesViewLike[TValue]], Generic[TValue]):
    """A choice among `values`, identified on the wire by its label (its `values` key).

    Labels, not `str(value)`: the same convention as `serialize_value`/
    `deserialize_value`, which also turn a stale or bogus label into `None` with a
    warning instead of the `ValueError` `_check_value` would raise.
    """

    def __init__(self, view: ValuesViewLike[TValue]) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._mark_dirty,
                "values": self._mark_dirty,
            }
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "change":
            super().dispatch(event, form)
        # the field is named after the widget id, so two groups never share a radio set
        label = form.get(self.widget_id, "")
        value = None if label == "" else self._view.deserialize_value(label)
        if value == self._view.value:
            return
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)

    def _htmx_attributes(self) -> str:
        return (
            f' name="{self.widget_id}" hx-post="/widget/{self.widget_id}" hx-trigger="change"'
            ' hx-vals=\'{"event": "change"}\' hx-swap="none"'
        )


class WebRadioGroupRenderer(_WebValuesRenderer[TValue]):
    _role = "radio_group"
    is_labelable = False

    def to_html(self, *, oob: bool = False) -> str:
        selected = self._view.serialize_value()
        disabled = "" if self._view.is_enabled else " disabled"
        options = "".join(
            '<label class="label cursor-pointer gap-2 text-base-content">'
            f'<input type="radio" class="radio radio-sm" value="{html.escape(label)}"'
            f"{' checked' if label == selected else ''}{self._htmx_attributes()}"
            f' autocomplete="off"{disabled}>'
            f"{html.escape(label)}</label>"
            for label in self._view.values
        )
        return (
            f'<div {self._root_attributes(oob=oob)}{self._row_attributes()} role="radiogroup"'
            f' class="flex flex-wrap gap-x-6 gap-y-2">{options}</div>'
        )


class WebComboboxRenderer(_WebValuesRenderer[TValue]):
    _role = "combobox"

    def to_html(self, *, oob: bool = False) -> str:
        selected = self._view.serialize_value()
        disabled = "" if self._view.is_enabled else " disabled"
        # an empty choice only while nothing is selected, as Qt's combobox shows nothing
        empty = '<option value="" selected></option>' if selected is None else ""
        options = "".join(
            f'<option value="{html.escape(label)}"'
            f"{' selected' if label == selected else ''}>{html.escape(label)}</option>"
            for label in self._view.values
        )
        return (
            f"<select {self._root_attributes(oob=oob)}{self._row_attributes()}"
            ' class="select w-full"'
            f'{self._htmx_attributes()} autocomplete="off"{disabled}>{empty}{options}</select>'
        )


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
        field = self._field_renderer()
        # a radio group isn't labelable: its `role="radiogroup"` names itself instead
        target = f' for="{field.widget_id}"' if field.is_labelable else ""
        return (
            f"<label {self._root_attributes(oob=oob)}{target}"
            f' class="label text-sm font-medium">{html.escape(self._view.label)}</label>'
        )

    def _field_renderer(self) -> WebRenderer[Any]:
        if not isinstance(self._view.renderer, RendererContainer):
            raise NoRenderedObjectError
        field_renderer = self._view.renderer.get_renderer("field")
        if not isinstance(field_renderer, WebRenderer):
            raise NoRenderedObjectError
        return field_renderer


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
        # `pre-line`: `FormView.validate` joins its messages with newlines.
        # `data-log`: the page's stylesheet marks the field just before an error log
        return (
            f'<p {attributes} aria-live="polite" data-log="{self._view.log_type.name.lower()}"'
            f' class="text-sm whitespace-pre-line {_LOG_CLASSES[self._view.log_type]}">'
            f"{html.escape(self._view.log_message)}</p>"
        )


class WebFormRenderer(WebRenderer[FormView]):
    """A form: each row's label, field and log stacked together, then the form's log.

    A `<fieldset>`, so disabling the form disables every control in it, as disabling a
    Qt container disables its children. Rows have no fragment of their own: each of a
    row's renderers hides itself when the row does, and swaps on its own.
    """

    _role = "form"

    def to_html(self, *, oob: bool = False) -> str:
        return self._fieldset(oob=oob, classes="flex min-w-0 flex-col gap-4", legend="")

    def _fieldset(self, *, oob: bool, classes: str, legend: str) -> str:
        disabled = "" if self._view.is_enabled else " disabled"
        rows = "".join(self._row_html(row) for row in self._view.field_rows)
        return (
            f'<fieldset {self._root_attributes(oob=oob)} class="{classes}"{disabled}>'
            f"{legend}{rows}{self._fragment(self._view.log_view.renderer)}</fieldset>"
        )

    def _row_html(self, row: FormRowView | FormView) -> str:
        if isinstance(row, FormView):
            return self._fragment(row.renderer)
        if not isinstance(row.renderer, RendererContainer):
            return ""  # this backend doesn't support the row's field
        parts = ["label", "field", "log"] if isinstance(row, FormLabelRowView) else ["field", "log"]
        # field right before log: the page's stylesheet marks a field followed by an error
        return (
            '<div class="flex flex-col gap-1">'
            f"{''.join(self._row_part(row.renderer, part) for part in parts)}</div>"
        )

    def _row_part(self, row_renderer: RendererContainer[Any], part: str) -> str:
        try:
            renderer = row_renderer.get_renderer(part)
        except KeyError as e:
            msg = f"The {part} renderer is missing in a row of the form {self._view}"
            raise ValueError(msg) from e
        return self._fragment(renderer)

    @staticmethod
    def _fragment(renderer: Any) -> str:
        return renderer.to_html() if isinstance(renderer, WebRenderer) else ""


class WebGroupFormRenderer(WebFormRenderer):
    """A titled group of rows, e.g. `pipeform.py`'s "Main Pipe"."""

    _role = "group_form"

    def __init__(self, view: GroupFormView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> str:
        title = self._view.title if isinstance(self._view, GroupFormView) else ""
        return self._fieldset(
            oob=oob,
            classes="fieldset min-w-0 gap-4 rounded-box border border-base-300 bg-base-200 p-4",
            legend=f'<legend class="fieldset-legend">{html.escape(title)}</legend>',
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
            f"<footer {self._root_attributes(oob=oob)}{self._auto_clear_attributes()}"
            ' role="status" aria-live="polite"'
            ' class="fixed inset-x-0 bottom-0 min-h-8 border-t border-base-300 bg-base-100'
            ' px-4 py-1 text-sm">'
            f"{html.escape(self._view.message)}"
            "</footer>"
        )

    def _auto_clear_attributes(self) -> str:
        """Fetch the bar again once its message has timed out.

        `show_message`'s timer clears the message on the server outside any request,
        so no response ever tells the browser. Instead, a bar showing a message asks
        for its own current state once, just after `timeout`; by then the timer has
        cleared it. A message that was replaced or re-shown meanwhile comes back with
        its own fresh delay, so a stale fetch is harmless.
        """
        if self._view.message == "" or self._view.timeout <= 0:
            return ""
        # margin: the browser's delay starts after the server's timer did, but not by much
        delay_ms = round((self._view.timeout + _AUTO_CLEAR_MARGIN) * 1000)
        return (
            f' hx-get="/widget/{self.widget_id}" hx-trigger="load delay:{delay_ms}ms"'
            ' hx-swap="outerHTML"'
        )


#: closes an open daisyUI dropdown (it stays open while something in it has focus)
_CLOSE_DROPDOWN = 'hx-on:click="document.activeElement.blur()"'


def _web_shortcut(shortcut: str | None) -> tuple[str, str] | None:
    """Map a view's `Ctrl+<letter or digit>` shortcut to one the browser leaves free.

    Browsers keep most Ctrl shortcuts for themselves (Ctrl+N opens a window, Ctrl+O a
    file, Ctrl+S saves the page, Ctrl+Q quits Firefox on Linux), so `Ctrl+x` becomes
    `Alt+Shift+X`, the combination web apps use for their own shortcuts. Returns the
    label to show and the physical key (`KeyboardEvent.code`) the page's key handler
    matches (see `page.py`); None for any other shortcut, which has no free web
    equivalent (e.g. `Ctrl+Shift+s` would collide with `Ctrl+s`'s `Alt+Shift+S`).
    """
    match = re.fullmatch(r"ctrl\+([a-z0-9])", shortcut or "", flags=re.IGNORECASE)
    if match is None:
        return None
    key = match.group(1).upper()
    code = f"Key{key}" if key.isalpha() else f"Digit{key}"
    return f"Alt+Shift+{key}", code


class WebMenuRenderer(WebRenderer[Menu]):
    """A navbar dropdown of the menu's actions.

    `Menu.is_visible` means "popped up" (it starts False, a Qt notion): a dropdown is
    always shown and opens on click, so it is ignored here.
    """

    _role = "menu"

    def __init__(self, view: Menu) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "is_visible": self._ignore,
                "title": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> str:
        oob_attribute = ' hx-swap-oob="true"' if oob else ""
        items = "".join(
            child.renderer.to_html()
            for child in self._view.children_views
            if isinstance(child.renderer, WebRenderer)
        )
        return (
            f'<div id="{self.widget_id}"{oob_attribute} class="dropdown">'
            f'<div tabindex="0" role="button" class="btn btn-ghost btn-sm">'
            f"{html.escape(self._view.title)}</div>"
            '<ul tabindex="0" class="menu dropdown-content z-10 w-56 rounded-box bg-base-100'
            f' p-2 shadow-sm">{items}</ul></div>'
        )

    def _ignore(self, _view: Menu, _rendered_object: str, _value: Any) -> None:
        pass


class WebActionRenderer(WebRenderer[ActionView]):
    """A menu item posting `triggered`; Save/Open are a download link and an upload.

    Those two can't go through the generic widget event: a download has to be a plain
    link, and a file has to be uploaded. Both name the action (`trigger`), so its
    `triggered` still fires first, for whatever user code is connected to it.
    """

    _role = "action"

    def __init__(self, view: ActionView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("text", "icon", "data", "shortcut", "is_checkable", "is_checked"),
                self._mark_dirty,
            )
        )

    def to_html(self, *, oob: bool = False) -> str:
        view = self._view
        check = "✓ " if view.is_checkable and view.is_checked else ""
        shortcut = _web_shortcut(view.shortcut)
        kbd = f'<kbd class="kbd kbd-sm">{shortcut[0]}</kbd>' if shortcut else ""
        label = f"<span>{check}{html.escape(view.text)}</span>{kbd}"
        # on the element a click activates: the page's key handler clicks it
        key = f' data-shortcut="{shortcut[1]}"' if shortcut else ""
        if not view.is_enabled:
            item = f'<button type="button" class="justify-between" disabled>{label}</button>'
        elif isinstance(view, (SaveAction, SaveAsAction)):
            item = (
                f'<a class="justify-between" href="/state?trigger={self.widget_id}" download'
                f" {_CLOSE_DROPDOWN}{key}>{label}</a>"
            )
        elif isinstance(view, OpenFileAction):
            item = (
                f'<label class="justify-between">{label}<input type="file" name="file"'
                ' class="hidden" hx-post="/state" hx-encoding="multipart/form-data"'
                f' hx-trigger="change" hx-vals=\'{{"trigger": "{self.widget_id}"}}\''
                f' hx-swap="none" autocomplete="off" {_CLOSE_DROPDOWN}{key}></label>'
            )
        else:
            item = (
                f'<button type="button" class="justify-between"'
                f' hx-post="/widget/{self.widget_id}" hx-vals=\'{{"event": "triggered"}}\''
                f' hx-swap="none" {_CLOSE_DROPDOWN}{key}>{label}</button>'
            )
        menu_disabled = "" if view.is_enabled else ' class="menu-disabled"'
        return f"<li {self._root_attributes(oob=oob)}{menu_disabled}>{item}</li>"

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "triggered" or not self._view.is_enabled:
            super().dispatch(event, form)
        self._view.triggered.emit()


class WebSeparatorRenderer(WebRenderer[SeparatorAction]):
    _role = "separator"

    def to_html(self, *, oob: bool = False) -> str:
        return (
            f'<li {self._root_attributes(oob=oob)} role="separator">'
            '<hr class="my-1 border-base-300 p-0"></li>'
        )


class WebMainRenderer(MainRenderer[MainView, str]):
    """Renders the whole page; never swapped itself, so its attributes are no-ops."""

    def __init__(self, view: MainView) -> None:
        super().__init__(view)
        #: set by `MainView.close()` (the Exit action); the route then ends the session
        self.is_closed = False
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
        menus: list[str] = []
        content: list[str] = []
        status_bar = ""
        for child_view in self._view.children_views:
            if not isinstance(child_view.renderer, WebRenderer):
                continue
            if isinstance(child_view, StatusBar):
                status_bar = child_view.renderer.to_html()
            elif isinstance(child_view, Menu):
                menus.append(child_view.renderer.to_html())
            else:
                content.append(child_view.renderer.to_html())
        # bottom padding keeps the last row clear of the fixed status bar
        return get_page(
            self._view.title,
            '<header class="navbar gap-2 bg-base-100 px-4 shadow-sm">'
            f"{''.join(menus)}"
            f'<h1 class="text-lg font-semibold">{html.escape(self._view.title)}</h1>'
            "</header>"
            '<main class="mx-auto max-w-3xl p-4 pb-16">'
            '<div class="card bg-base-100 shadow-sm"><div class="card-body gap-4">'
            f"{''.join(content)}"
            "</div></div></main>"
            f"{status_bar}",
        )

    def close(self) -> None:
        self.is_closed = True

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
    "action": WebActionRenderer,
    "combobox": WebComboboxRenderer,
    "float_input": WebFloatInputRenderer,
    "form": WebFormRenderer,
    "form_label": WebFormLabelRenderer,
    "group_form": WebGroupFormRenderer,
    "input": WebInputRenderer,
    "label": WebLabelRenderer,
    "log": WebLogRenderer,
    "main": WebMainRenderer,
    "menu": WebMenuRenderer,
    "radio_group": WebRadioGroupRenderer,
    "separator": WebSeparatorRenderer,
    "status_bar": WebStatusBarRenderer,
}
