"""Web backend renderers: each view renders to an HTML fragment swapped in by htmx.

There is no live widget to mutate between requests, so a renderer's rendered object is
just the stable id of its fragment. Changing a view attribute marks the renderer dirty
in a request-scoped set (`collect_dirty`); the route then re-renders every dirty
fragment as an htmx out-of-band swap (`render_dirty`). A change made outside any request,
by a thread handing it over with `call_on_main_thread`, waits in its session's `pending`
for the next response.
"""

from __future__ import annotations

import contextlib
import datetime
import enum
import html
import json
import math
import re
import threading
from abc import abstractmethod
from collections import deque
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Final, Generic, TypeVar

from markdown_it import MarkdownIt
from typing_extensions import Protocol

from composeui.core import chartimage
from composeui.core.registry import RendererType
from composeui.core.renderer import (
    MainRenderer,
    NoRenderedObjectError,
    Renderer,
    RendererContainer,
    ViewLike,
)
from composeui.core.view import (
    ActionView,
    Align,
    ButtonVariant,
    ChartKind,
    ChartView,
    DialogKind,
    DialogView,
    ExitAppAction,
    ExpanderView,
    FormDialogView,
    FormLabelRowView,
    FormRowView,
    FormView,
    GridView,
    GroupFormView,
    HorizontalView,
    ListView,
    LogType,
    MainView,
    Menu,
    MetricView,
    NewAction,
    NodeMark,
    OpenFileAction,
    Orientation,
    PageView,
    PickFileAction,
    ProgressBarView,
    Router,
    SaveAction,
    SaveAsAction,
    SelectionMode,
    SeparatorAction,
    SidebarView,
    SliderMixin,
    SplitterView,
    StatusBar,
    TabPage,
    TabView,
    ToolBar,
    TreeView,
    VerticalView,
    View,
    as_pattern,
    date_hint,
    parse_date,
    replace_cell,
    split_pattern,
    walk_tree,
)
from composeui.webcore.icons import icon_url
from composeui.webcore.page import get_page

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Mapping
    from pathlib import Path

    from composeui.core.signal import Signal, SignalNoArgs
    from composeui.core.view import ReferenceLine, Series, TreeNode, TreePath

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
        #: the renderers changed outside any request (`call_on_main_thread` from another
        #: thread), to send with the next response: no response was there to carry them
        self.pending: dict[str, WebRenderer[Any]] = {}

    def take_pending(self) -> dict[str, WebRenderer[Any]]:
        """Get the renderers changed outside any request, sending them is then the caller's."""
        pending, self.pending = self.pending, {}
        return pending


def call_in_session(target: RenderTarget | None, callback: Callable[[], None]) -> None:
    """Run `callback` under `target`'s lock, keeping what it changes in its `pending`.

    The `call_on_main_thread` of every web renderer: a request alone touches a session's
    tree otherwise, and its response sends what it changed.
    """
    if target is None:
        callback()  # rendered outside any session: nothing else touches the tree
        return
    with target.lock, collect_dirty() as dirty:
        callback()
        target.pending.update(dirty)


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
        self._target: RenderTarget | None = None
        #: the container drawing this view, if it passes its enabled state on (`is_enabled`)
        self.parent: WebRenderer[Any] | None = None
        #: the renderers this one is the `parent` of
        self.children: list[WebRenderer[Any]] = []
        self._refresh_dispatcher.update(
            {
                "is_visible": self._mark_dirty,
                "is_enabled": self._refresh_enabled,
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
                self._target = target

    @property
    def is_enabled(self) -> bool:
        """Whether the view and every container around it are enabled.

        As disabling a Qt or Textual container disables its children; the container
        swaps whole, so its views come back disabled with it, and so do the dialogs
        drawn apart from it (see `_refresh_enabled`).
        """
        return self._view.is_enabled and (self.parent is None or self.parent.is_enabled)

    def _adopt(self, views: Iterable[View]) -> None:
        """Make this renderer the parent of `views`' renderers (see `is_enabled`)."""
        for view in views:
            renderer: Any = view.renderer
            children = renderer.renderers if isinstance(renderer, RendererContainer) else [renderer]
            for child in children:
                if isinstance(child, WebRenderer) and child not in self.children:
                    child.parent = self
                    self.children.append(child)

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        call_in_session(self._target, callback)

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

        The field is described by the row's help, if any, and its log, read out with the
        field, and is `aria-invalid` while the log shows an error (the page script keeps
        that in step when only the log is swapped, see `page.py`). A field a `<label for>`
        can't name, a radio group or a checkbox, is labelled by the row's label instead.
        Nothing outside a row.
        """
        attributes: list[str] = []
        log, label = self._row_renderer("log"), self._row_renderer("label")
        if log is not None:
            described_by = (
                f"{label.help_id} {log.widget_id}"
                if isinstance(label, WebFormLabelRenderer) and label.has_help()
                else log.widget_id
            )
            attributes.append(f'aria-describedby="{described_by}"')
            if isinstance(self._view, FormRowView) and self._view.is_invalid:
                attributes.append('aria-invalid="true"')
        if not self.is_labelable and isinstance(label, WebFormLabelRenderer):
            attributes.append(f'aria-labelledby="{label.text_id}"')
        return "".join(f" {attribute}" for attribute in attributes)

    def _row_renderer(self, part: str) -> WebRenderer[Any] | None:
        """Get another renderer of the view's row, e.g. its "log", if it has one."""
        container = self._view.renderer  # type: ignore[attr-defined]
        if not isinstance(container, RendererContainer):
            return None
        try:
            renderer = container.get_renderer(part)
        except KeyError:
            return None
        if not isinstance(renderer, WebRenderer) or renderer is self:
            return None
        return renderer

    def _refresh_enabled(self, view: TView, rendered_object: str, value: Any) -> None:
        self._mark_dirty(view, rendered_object, value)
        # the dialogs below, drawn at the end of the page rather than in this fragment
        dirty = _DIRTY.get()
        descendants = list(self.children)
        while dirty is not None and len(descendants) > 0:
            descendant = descendants.pop()
            descendants.extend(descendant.children)
            if isinstance(descendant, WebDialogRenderer):
                dirty[descendant.widget_id] = descendant

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
        disabled = "" if self.is_enabled else " disabled"
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


class _NumberFieldViewLike(TextFieldViewLike, Protocol):
    value: Any


TNumberField = TypeVar("TNumberField", bound=_NumberFieldViewLike)


class _WebNumberFieldRenderer(_WebTextFieldRenderer[TNumberField]):
    """A text field holding a number, parsed by `_parse`.

    Not `type="number"`: while typing e.g. "-5" its value reads "" for the transient
    "-", indistinguishable from a cleared field. A text field posts the raw text and
    unparsable text is ignored, the same as the Qt/Textual inputs. Like Textual,
    `minimum`/`maximum` (and `decimals`) are tracked on the view but not enforced on input.

    Leaving the field (`change`) with unparsable text puts the value back: Qt never
    lets such text in at all, and a field showing "4a" while the view (and its
    validators) still sees 4 would contradict every message around it.
    """

    def __init__(self, view: TNumberField) -> None:
        super().__init__(view)
        self._last_posted_text: str | None = None
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._mark_dirty,
                "minimum": self._mark_dirty,
                "maximum": self._mark_dirty,
            }
        )

    @staticmethod
    @abstractmethod
    def _parse(text: str) -> Any:
        """Parse a non-empty text into a value, raising `ValueError` if it can't."""

    def _is_acceptable(self, text: str) -> bool:
        """Whether `text` is an acceptable field value ("" meaning no value)."""
        if text == "":
            return True
        try:
            self._parse(text)
        except ValueError:
            return False
        return True

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event == "change" and not self._is_acceptable(form.get("value", "")):
            # no `editing_finished`, as Qt doesn't emit it for unacceptable text; the
            # field itself is swapped back, which is safe now that it has been left
            self._last_posted_text = None
            self._mark_dirty(self._view, self.widget_id, self._view.value)
            return
        super().dispatch(event, form)

    def _refresh_value(self, view: TNumberField, rendered_object: str, value: Any) -> None:
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
            self._view.value = self._parse(text) if text != "" else None


class FloatInputViewLike(_NumberFieldViewLike, Protocol):
    value: float | None
    minimum: float | None
    maximum: float | None
    decimals: int | None


#: an optionally signed decimal number, partial input ("-", "1.") included
_DECIMAL_PATTERN = r"[+\-]?[0-9]*([.][0-9]*)?([eE][+\-]?[0-9]*)?"


class WebFloatInputRenderer(_WebNumberFieldRenderer[FloatInputViewLike]):
    """A decimal text field."""

    _role = "float_input"

    def __init__(self, view: FloatInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher["decimals"] = self._mark_dirty

    @staticmethod
    def _parse(text: str) -> float:
        return float(text)

    def _extra_attributes(self) -> str:
        return f' inputmode="decimal" pattern="{_DECIMAL_PATTERN}"'


class IntInputViewLike(_NumberFieldViewLike, Protocol):
    value: int | None
    minimum: int | None
    maximum: int | None


#: an optionally signed whole number, partial input ("-") included
_INTEGER_PATTERN = r"[+\-]?[0-9]*"


class WebIntInputRenderer(_WebNumberFieldRenderer[IntInputViewLike]):
    """A whole number text field: a phone shows its digit keypad."""

    _role = "int_input"

    @staticmethod
    def _parse(text: str) -> int:
        return int(text)

    def _extra_attributes(self) -> str:
        return f' inputmode="numeric" pattern="{_INTEGER_PATTERN}"'


class DateInputViewLike(TextFieldViewLike, Protocol):
    value: datetime.date | None
    minimum: datetime.date | None
    maximum: datetime.date | None
    date_format: str
    pick_text: str
    previous_month_text: str
    next_month_text: str
    value_changed: Signal[datetime.date | None]

    def shown_text(self, value: datetime.date | None) -> str: ...


class WebDateInputRenderer(WebRenderer[DateInputViewLike]):
    """A text field typing the date as the view's `date_format` says, then a calendar button.

    The root is daisyUI's field holding both, so the button takes the field's colors in
    every theme, and the field's border marks the row invalid (see `css/app.css`); a row's
    label names the text field with `aria-labelledby`, as a `<div>` can't be labelled. The
    text posts like a number's (see `_WebNumberFieldRenderer`): never swapped back while
    typed in, text that isn't a date ignored. Left (`change`), it is swapped back showing
    the date as the format writes it, or the date back for text that isn't one.

    The button opens a popover holding Cally's calendar (`<calendar-date>`, which daisyUI
    styles in the theme's colors), its months and days in the page's language (see
    `page.py`); the date picked posts as its change (`pick`), in ISO 8601. Like the number
    fields, a date typed out of `minimum`/`maximum` isn't refused; the calendar offers only
    those in range.
    """

    _role = "date_input"
    is_labelable = False

    def __init__(self, view: DateInputViewLike) -> None:
        super().__init__(view)
        #: the text the field last posted, while it stays what the field shows
        self._last_posted_text: str | None = None
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._mark_dirty,
                "minimum": self._mark_dirty,
                "maximum": self._mark_dirty,
                "date_format": self._refresh_value,
                "pick_text": self._mark_dirty,
                "previous_month_text": self._mark_dirty,
                "next_month_text": self._mark_dirty,
                # the calendar names them, in the page's language (`Intl`'s names)
                "month_names": lambda _view, _rendered_object, _value: None,
                "day_names": lambda _view, _rendered_object, _value: None,
            }
        )

    def to_html(self, *, oob: bool = False) -> str:
        view = self._view
        disabled = "" if self.is_enabled else " disabled"
        pick = html.escape(view.pick_text)
        limits = "".join(
            f' {name}="{limit.isoformat()}"'
            for name, limit in (("min", view.minimum), ("max", view.maximum))
            if limit is not None
        )
        picked = "" if view.value is None else view.value.isoformat()
        calendar_id = f"{self.widget_id}-calendar"
        return (
            # daisyUI's field around both, its colors, focus ring and invalid border theirs
            f'<div {self._root_attributes(oob=oob)} class="input relative w-full pe-1">'
            f'<input id="{self.widget_id}-field"{self._row_attributes()}'
            ' class="min-w-0 grow" type="text" name="value"'
            f' value="{html.escape(view.shown_text(view.value))}"'
            f' placeholder="{html.escape(date_hint(view.placeholder, view.date_format))}"'
            f' hx-post="/widget/{self.widget_id}" hx-trigger="input changed delay:300ms, change"'
            ' hx-vals="js:{event: event.type}" hx-swap="none" hx-sync="this:queue all"'
            f' autocomplete="off"{disabled}>'
            f'<button id="{self.widget_id}-pick" type="button"'
            ' class="btn btn-ghost btn-sm btn-square"'
            f' aria-label="{pick}" title="{pick}" popovertarget="{calendar_id}"'
            f' style="anchor-name: --{self.widget_id}"{disabled}>'
            f"{_icon('calendar')}</button>"
            # in the top layer, under the button: Escape or a click beside it closes it
            f'<div id="{calendar_id}" popover data-date-button="{self.widget_id}-pick"'
            ' class="dropdown dropdown-end rounded-box bg-base-100 shadow-lg"'
            f' style="position-anchor: --{self.widget_id}">'
            f'<calendar-date class="cally" value="{picked}"{limits} data-date-calendar'
            f' hx-post="/widget/{self.widget_id}" hx-trigger="change"'
            """ hx-vals='js:{event: "pick", picked: event.target.value}' hx-swap="none">"""
            f'<span slot="previous" aria-label="{html.escape(view.previous_month_text)}">'
            f"{_icon('chevron', 'size-4 rotate-90')}</span>"
            f'<span slot="next" aria-label="{html.escape(view.next_month_text)}">'
            f"{_icon('chevron', 'size-4 -rotate-90')}</span>"
            "<calendar-month></calendar-month></calendar-date></div></div>"
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if not self.is_enabled or event not in ("input", "change", "pick"):
            super().dispatch(event, form)
        if event == "pick":
            with contextlib.suppress(ValueError):  # a date input posts a date, or nothing
                self._edit(datetime.date.fromisoformat(form.get("picked", "")))
            # the field shows it: swapped back, as the button had the focus, not the field
            self._refresh_value(self._view, self.widget_id, self._view.value)
            return
        # `change` carries the text too: it can overtake a still-debounced `input`, which
        # then posts the same text again and must not report it again
        text = form.get("value", "")
        if text != self._posted_text():
            self._last_posted_text = text
            if text.strip() == "":
                self._edit(None)
            else:
                with contextlib.suppress(ValueError):  # not a date yet, e.g. halfway
                    self._edit(parse_date(text, self._view.date_format))
            self._view.text_changed.emit(text)
            self._view.text_edited.emit(text)
        if event == "change":
            # left: the date as the format writes it, or back for text that isn't one
            self._refresh_value(self._view, self.widget_id, self._view.value)
            self._view.editing_finished.emit()

    def _edit(self, value: datetime.date | None) -> None:
        if value == self._view.value:
            return
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)

    def _posted_text(self) -> str:
        if self._last_posted_text is not None:
            return self._last_posted_text
        return self._view.shown_text(self._view.value)

    def _refresh_value(self, view: DateInputViewLike, rendered_object: str, value: Any) -> None:
        self._last_posted_text = None  # the server's date wins over what was typed
        self._mark_dirty(view, rendered_object, value)


class CheckBoxViewLike(ViewLike, Protocol):
    text: str
    is_checked: bool
    toggled: Signal[bool]


class WebCheckBoxRenderer(WebRenderer[CheckBoxViewLike]):
    """A checkbox with its text, posting each toggle.

    The root is a `<div role="group">`, as for a radio group: the box's own `<label>`
    names it with its text, and a row's label names the group. Like a radio group,
    the box is never swapped back after a toggle; it is when the server changes it.
    """

    _role = "checkbox"
    is_labelable = False

    def __init__(self, view: CheckBoxViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._mark_dirty,
                "is_checked": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> str:
        checked = " checked" if self._view.is_checked else ""
        disabled = "" if self.is_enabled else " disabled"
        # an unchecked box posts no value at all: `checked` is told apart by its presence
        return (
            f'<div {self._root_attributes(oob=oob)}{self._row_attributes()} role="group"'
            ' class="flex">'
            '<label class="label cursor-pointer gap-2 text-base-content">'
            '<input type="checkbox" class="checkbox checkbox-sm checkbox-primary"'
            f' name="checked" value="on"{checked} hx-post="/widget/{self.widget_id}"'
            ' hx-trigger="change" hx-vals=\'{"event": "change"}\' hx-swap="none"'
            f' autocomplete="off"{disabled}>'
            f"{html.escape(self._view.text)}</label></div>"
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "change":
            super().dispatch(event, form)
        is_checked = "checked" in form
        if is_checked == self._view.is_checked:
            return
        with self.stop_refresh():
            self._view.is_checked = is_checked
        self._view.toggled.emit(is_checked)


class ButtonViewLike(ViewLike, Protocol):
    text: str
    variant: ButtonVariant
    clicked: SignalNoArgs


#: each button variant as daisyUI's
_BUTTON_CLASSES: Final[dict[ButtonVariant, str]] = {
    ButtonVariant.PRIMARY: "btn-primary",
    ButtonVariant.SECONDARY: "btn-soft",
    ButtonVariant.DANGER: "btn-error",
}


class WebButtonRenderer(WebRenderer[ButtonViewLike]):
    """A button posting each click; like every control, never swapped back after one."""

    _role = "button"

    def __init__(self, view: ButtonViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._mark_dirty, "variant": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> str:
        disabled = "" if self.is_enabled else " disabled"
        variant = _BUTTON_CLASSES[self._view.variant]
        # `self-start`: as wide as its text, not the page's whole column
        return (
            f'<button {self._root_attributes(oob=oob)} type="button"'
            f' class="btn {variant} self-start"'
            f' hx-post="/widget/{self.widget_id}" hx-vals=\'{{"event": "click"}}\''
            f' hx-swap="none"{disabled}>{html.escape(self._view.text)}</button>'
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a disabled button can't be clicked: a post saying otherwise is refused
        if event != "click" or not self.is_enabled:
            super().dispatch(event, form)
        self._view.clicked.emit()


class ProgressBarViewLike(ViewLike, Protocol):
    value: int
    maximum: int | None


class WebProgressBarRenderer(WebRenderer[ProgressBarViewLike]):
    """A `<progress>` bar; one with no value is the browser's own for a task of unknown length."""

    _role = "progress_bar"

    def __init__(self, view: ProgressBarViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"value": self._mark_dirty, "maximum": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> str:
        value, maximum = self._view.value, self._view.maximum
        clamped = ProgressBarView.clamp(value, maximum)
        progress = "" if maximum is None else f' value="{clamped}" max="{maximum}"'
        return (
            f'<progress {self._root_attributes(oob=oob)} class="progress progress-primary w-full"'
            f"{progress}></progress>"
        )


class SliderViewLike(ViewLike, Protocol):
    value: int
    minimum: int
    maximum: int
    step: int
    value_changed: Signal[int]


class WebSliderRenderer(WebRenderer[SliderViewLike]):
    """A range input posting the handle's moves, its value in an `<output>` on its right.

    The browser stops the handle on each step. The moves are posted debounced
    (`input`) and on release (`change`); meanwhile the page's script keeps the value
    in step (see `page.py`). Beside the track rather than above the handle, and in a
    slot as wide as the widest value, so the row is as tall as a text field's and the
    track keeps its length. The root is a `<div>` holding both, so a row's label names
    the input with `aria-labelledby`. Like every control, never swapped back after a
    move; it is when the server changes it.
    """

    _role = "slider"
    is_labelable = False

    def __init__(self, view: SliderViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._mark_dirty,
                "minimum": self._mark_dirty,
                "maximum": self._mark_dirty,
                "step": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> str:
        minimum, step = self._view.minimum, self._view.step
        last = SliderMixin.last_position(minimum, self._view.maximum, step)
        position = SliderMixin.position(self._view.value, minimum, self._view.maximum, step)
        value = minimum + position * step
        top = minimum + last * step
        digits = max(len(str(minimum)), len(str(top)))
        disabled = "" if self.is_enabled else " disabled"
        input_id = f"{self.widget_id}-input"
        return (
            f'<div {self._root_attributes(oob=oob)} class="cui-slider"'
            f' style="--slider-digits: {digits}">'
            f'<input id="{input_id}"{self._row_attributes()} type="range" data-slider'
            ' class="range range-primary" name="value"'
            f' min="{minimum}" max="{top}" step="{step}" value="{value}"'
            f' hx-post="/widget/{self.widget_id}" hx-trigger="input changed delay:150ms, change"'
            ' hx-vals="js:{event: event.type}" hx-swap="none" hx-sync="this:queue all"'
            f' autocomplete="off"{disabled}>'
            # read out by the input itself, as its value
            f'<output for="{input_id}" class="cui-slider-value" aria-hidden="true">{value}</output>'
            "</div>"
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event not in ("input", "change"):
            super().dispatch(event, form)
        try:
            posted = int(form.get("value", ""))
        except ValueError:
            return  # a range input always posts a number; nothing else is a move
        minimum, maximum, step = self._view.minimum, self._view.maximum, self._view.step
        value = minimum + SliderMixin.position(posted, minimum, maximum, step) * step
        # `change` posts the value of a still-debounced `input` too: emitted once
        if value == self._view.value:
            return
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


class ChartViewLike(ViewLike, Protocol):
    kind: ChartKind
    title: str
    x_title: str
    y_title: str
    x_unit: str
    y_unit: str
    series: list[Series]
    reference_lines: list[ReferenceLine]
    categories: list[str]
    x_log: bool
    y_log: bool
    save_image_text: str
    clicked: Signal[float, float]
    height: int | None


#: the points a series sends at most, about twice a wide chart's pixels: a longer one is
#: thinned to the extremes of each bucket of its points, so its peaks stay
CHART_MAX_POINTS: Final = 4000


def _json_number(value: float) -> float | None:
    """Get `value` for JSON, which has no NaN or infinity: None, uPlot's gap."""
    return value if math.isfinite(value) else None


def _thin(x: list[float], y: list[float], max_points: int) -> tuple[list[float], list[float]]:
    """Keep each bucket's lowest and highest point, and a gap it holds, of a long series."""
    if len(x) <= max_points:
        return x, y
    # two points a bucket, and room for a gap in some of them
    bucket_count = max(1, max_points // 3)
    kept: list[int] = []
    for bucket in range(bucket_count):
        start = bucket * len(x) // bucket_count
        end = (bucket + 1) * len(x) // bucket_count
        drawn = [index for index in range(start, end) if math.isfinite(y[index])]
        indexes = set()
        if len(drawn) > 0:
            indexes.add(min(drawn, key=y.__getitem__))
            indexes.add(max(drawn, key=y.__getitem__))
        if len(drawn) < end - start:
            indexes.add(next(i for i in range(start, end) if not math.isfinite(y[i])))
        kept.extend(sorted(indexes))
    return [x[index] for index in kept], [y[index] for index in kept]


def _chart_points(series: Series, *, x_log: bool, y_log: bool) -> tuple[list[float], list[float]]:
    """Get a series' points as uPlot draws them: by ascending x, thinned when long.

    A log axis' values it can't show are left out (`ChartView.drawn_points`).
    """
    xs, ys = ChartView.drawn_points(series, x_log=x_log, y_log=y_log)
    points = [(x, y) for x, y in zip(xs, ys) if math.isfinite(x)]
    if any(a[0] > b[0] for a, b in zip(points, points[1:])):
        points.sort(key=lambda point: point[0])
    x, y = [point[0] for point in points], [point[1] for point in points]
    return _thin(x, y, CHART_MAX_POINTS)


def _query_range(query: Mapping[str, str], axis: str) -> tuple[float, float] | None:
    """Get an axis' range from a query's `x_min` and `x_max` (or `y_...`), if it has one."""
    low, high = query.get(f"{axis}_min"), query.get(f"{axis}_max")
    if low is None or high is None:
        return None
    bounds = (float(low), float(high))  # a ValueError for text that isn't a number
    if not all(math.isfinite(bound) for bound in bounds):
        msg = f"Cannot draw the {axis} range {bounds}."
        raise ValueError(msg)
    return bounds


class WebChartRenderer(WebRenderer[ChartViewLike]):
    """A chart the page's script draws with uPlot, from the JSON in its `data-chart`.

    The user zooms by dragging across it, back out with a double click, and reads the
    values at the cursor in its legend; a series' legend entry hides or shows it. A new
    `series` list swaps the figure, the page keeping the user's zoom (see `page.py`).

    A click on the plot, rather than the end of a drag, posts its point: `clicked` emits
    it. Its corner downloads its image as a report's figure, in the format picked beside:
    matplotlib draws it from the view's data at the user's zoom (see `image`), the same
    file as Qt saves. Without matplotlib, the page draws a PNG of what it shows instead.
    """

    _role = "chart"
    is_labelable = False

    def __init__(self, view: ChartViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                (
                    "kind",
                    "title",
                    "x_title",
                    "y_title",
                    "x_unit",
                    "y_unit",
                    "series",
                    "reference_lines",
                    "categories",
                    "x_log",
                    "y_log",
                    "save_image_text",
                    "height",
                ),
                self._mark_dirty,
            )
        )

    def chart_json(self) -> str:
        """Get what the page's script draws, as JSON."""
        view = self._view
        x_unit, y_unit = view.x_unit, view.y_unit
        spec: dict[str, Any] = {
            "title": view.title,
            "x": {
                "label": ChartView.axis_label(view.x_title, x_unit),
                "unit": x_unit,
                # a bar chart's x is its categories, never a log axis
                "log": view.x_log and view.kind is not ChartKind.BAR,
            },
            "y": {
                "label": ChartView.axis_label(view.y_title, y_unit),
                "unit": y_unit,
                "log": view.y_log,
            },
            "series": [
                {
                    "name": series.name,
                    "kind": ChartView.kind_of(series, view.kind).name.lower(),
                    # None: the theme's
                    "color": series.color,
                    "fill": series.fill,
                    "step": series.step,
                }
                for series in view.series
            ],
            "lines": [
                # a color of None: the theme's text
                {
                    "value": line.value,
                    "label": line.label,
                    "vertical": line.vertical,
                    "color": line.color,
                    "style": line.style.name.lower(),
                }
                for line in ChartView.drawn_lines(
                    view.reference_lines,
                    x_log=view.x_log and view.kind is not ChartKind.BAR,
                    y_log=view.y_log,
                )
            ],
        }
        if view.kind is ChartKind.BAR:
            self._add_bars(spec)
            return json.dumps(spec, allow_nan=False, separators=(",", ":"))
        points = [
            _chart_points(series, x_log=view.x_log, y_log=view.y_log) for series in view.series
        ]
        if len(points) > 0 and all(x == points[0][0] for x, _y in points):
            # uPlot's own columns: the x shared, then each series' y
            spec["data"] = [points[0][0], *([_json_number(v) for v in y] for _x, y in points)]
        else:
            # each series by its own x, joined in the browser
            spec["pairs"] = [[x, [_json_number(v) for v in y]] for x, y in points]
        return json.dumps(spec, allow_nan=False, separators=(",", ":"))

    def _add_bars(self, spec: dict[str, Any]) -> None:
        """Add a bar chart's categories, and its bars: their heights, offsets and widths."""
        view = self._view
        count = len(view.categories)
        spec["categories"] = view.categories
        # x, the categories' indexes, shared; each series' height in each of them
        spec["data"] = [
            list(range(count)),
            *(
                [
                    _json_number(height)
                    for height in ChartView.bar_heights(series, count, y_log=view.y_log)
                ]
                for series in view.series
            ),
        ]
        for index, series_spec in enumerate(spec["series"]):
            offset, width = ChartView.bar_slot(index, len(view.series))
            series_spec.update({"offset": offset, "width": width})

    def _description(self) -> str:
        """Describe the chart to a screen reader, which can't read its canvas."""
        view = self._view
        names = ", ".join(series.name for series in view.series)
        if view.kind is ChartKind.BAR:
            x_label, link = ", ".join(view.categories), "for"
        else:
            x_label, link = ChartView.axis_label(view.x_title, view.x_unit), "against"
        description = f"{names} {link} {x_label}" if names and x_label else names or x_label
        labels = ", ".join(line.label for line in view.reference_lines if line.label)
        description = (
            f"{description}; {labels}" if description and labels else description or labels
        )
        return f"{view.title}: {description}" if view.title and description else view.title

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a click on the plot (see `page.py`), at a point in the axes' values
        if event != "click" or not self.is_enabled:
            super().dispatch(event, form)
        try:
            x, y = float(form.get("x", "")), float(form.get("y", ""))
        except ValueError:
            super().dispatch(event, form)
        if not (math.isfinite(x) and math.isfinite(y)):
            super().dispatch(event, form)
        self._view.clicked.emit(x, y)

    def image(self, image_format: str, query: Mapping[str, str]) -> tuple[str, bytes]:
        """Draw the chart's image, e.g. at the zoom in `query` (`x_min`, `x_max`...).

        Returns the file's name and content; raises `ValueError` for a format or a
        range it can't draw, and `ImportError` without matplotlib.
        """
        view = self._view
        if not isinstance(view, ChartView):
            raise TypeError(type(view).__name__)
        options = chartimage.ImageOptions(
            x_range=_query_range(query, "x"), y_range=_query_range(query, "y")
        )
        content = chartimage.chart_image_bytes(view, image_format, options)
        return chartimage.image_name(view.title, image_format.lower()), content

    def to_html(self, *, oob: bool = False) -> str:
        title = self._view.title
        # the corner's controls at the end of the row, the title in the middle of the rest
        caption = (
            '<figcaption class="min-w-0 flex-1 text-center font-semibold">'
            f"{html.escape(title)}</figcaption>"
            if title
            else '<span class="flex-1"></span>'
        )
        return (
            # a column: a card's figures are rows of images otherwise (daisyUI's `card`)
            f'<figure {self._root_attributes(oob=oob)} class="flex w-full flex-col gap-2">'
            f'<div class="flex w-full items-center gap-2">{caption}{self._save_image_html()}</div>'
            f'<div id="{self.widget_id}-plot" data-chart="{html.escape(self.chart_json())}"'
            f' role="img" aria-label="{html.escape(self._description())}"'
            f"{self._height_attributes()}></div></figure>"
        )

    def _height_attributes(self) -> str:
        """Get the plot's height: the view's, or the page's own (the script fits it to it)."""
        height = self._view.height
        if height is None:
            return ' class="h-72 w-full"'
        return f' class="w-full" style="height: {int(height)}px"'

    def _save_image_html(self) -> str:
        """Get the figure's corner: its image's download, in a format picked beside it."""
        text = html.escape(self._view.save_image_text)
        if not chartimage.is_available():
            # no matplotlib: the page draws what it shows, as a PNG
            name = html.escape(chartimage.image_name(self._view.title, "png"))
            return (
                f'<button type="button" class="btn btn-ghost btn-xs" data-chart-png="{name}">'
                f"{text} (PNG)</button>"
            )
        options = "".join(
            f'<option value="{image_format}">{image_format.upper()}</option>'
            for image_format in ("pdf", "svg", "png")
        )
        # a plain link: htmx can't start a download. The page's script adds the zoom
        return (
            '<div class="join">'
            '<select class="select select-xs join-item w-auto" aria-label="Image format"'
            f" data-chart-format>{options}</select>"
            f'<a class="btn btn-ghost btn-xs join-item" data-chart-image download'
            f' href="/widget/{self.widget_id}/image?format=pdf">{text}</a></div>'
        )


class MetricViewLike(ViewLike, Protocol):
    label: str
    value: str
    delta: float | None
    delta_text: str


class WebMetricRenderer(WebRenderer[MetricViewLike]):
    """A daisyUI stat: its label, its value, and its change as a badge colored by its sign."""

    _role = "metric"

    def __init__(self, view: MetricViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._mark_dirty,
                "value": self._mark_dirty,
                "delta": self._mark_dirty,
                "delta_text": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> str:
        delta = self._view.delta
        badge = ""
        if delta is not None:
            color = "badge-success" if delta > 0 else "badge-error" if delta < 0 else "badge-ghost"
            text = html.escape(MetricView.badge(delta, self._view.delta_text))
            badge = (
                f'<div class="stat-desc"><span class="badge badge-soft {color}">{text}</span></div>'
            )
        return (
            f'<div {self._root_attributes(oob=oob)} class="stat px-0">'
            f'<div class="stat-title">{html.escape(self._view.label)}</div>'
            f'<div class="stat-value">{html.escape(self._view.value)}</div>{badge}</div>'
        )


class TableViewLike(ViewLike, Protocol):
    headers: list[str]
    filter_texts: dict[str, str]
    selection_mode: SelectionMode
    rows: list[list[str]]
    sortable_columns: list[int]
    filterable_columns: list[int]
    sort_column: int | None
    sort_descending: bool
    search: str
    filters: dict[int, str]
    selected_rows: list[int]
    shown_rows: list[int]
    selection_changed: Signal[list[int]]
    editable_columns: list[int]
    cell_edited: Signal[int, int, str]

    def emit_cell_edited(self, row: int, column: int, text: str) -> None: ...
    def sort_by(self, column: int) -> None: ...
    def filter_error(self, column: int, text: str) -> str | None: ...
    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str: ...
    def filter_takes_pattern(self, column: int) -> bool: ...
    def filter_chip(self, column: int) -> str: ...


#: the order a sortable column's header shows, as `aria-sort` says it
_ARIA_SORT: Final[dict[bool | None, str]] = {None: "none", False: "ascending", True: "descending"}


class WebTableRenderer(WebRenderer[TableViewLike]):
    """A table under its filter bar, scrolling sideways on its own when wider than the page.

    Clicking a row, or pressing Enter on it, selects it; the table is swapped back to
    show it selected, each row keeping its own id so htmx gives the focus back to the
    row that had it. Selecting one row, it is the current one (`aria-current`).
    Selecting several, the table is a grid whose rows are each selected or not
    (`aria-selected`), and a click adds or removes its row.

    Double clicking a cell of `editable_columns`, or pressing F2 on its row (see
    `page.py`), edits it: the table comes back with a field in the cell, named by its
    header, its text selected. Enter or leaving the field posts the text, Escape puts the
    old text back first; either way the cell is text again. The page keeps the text the
    user is typing through a swap of the table, e.g. answering the double click's clicks.

    The table shows `shown_rows`, each row keeping the id of its index in `rows`. A
    sortable column's header is a button sorting by it. While a column filters, the bar
    above the table has a search, posted as the user types, and "+ Filter", opening an
    editor in the bar: a column, a value and Add. The filters show as chips. A sort, a
    search or a filter swaps only what it changes (the headers, the body, the count, the
    bar), never the field the user types in; a value that can't filter swaps only its
    message in, the page marking the field invalid.
    """

    _role = "table"

    def __init__(self, view: TableViewLike) -> None:
        super().__init__(view)
        #: the cell the user is editing, by row and column
        self._editing: tuple[int, int] | None = None
        #: the filter editor, while open: its column (None for the first) and its text
        self._editor: tuple[int | None, str] | None = None
        #: why the editor's text can't filter, once the user added it
        self._editor_error: str | None = None
        #: whether "+ Filter" takes the focus back, the editor or a chip just gone
        self._focus_add_filter = False
        #: the column whose chip takes the focus, its filter just added: Enter reopens it
        self._focused_chip: int | None = None
        #: the parts to swap, unless the whole table is (`_mark_dirty`)
        self._dirty_parts: set[str] = set()
        self._is_whole_dirty = False
        self._refresh_dispatcher.update(
            {
                "headers": self._mark_dirty,
                "filter_texts": self._mark_dirty,
                "selection_mode": self._mark_dirty,
                "rows": self._refresh_rows,
                "sortable_columns": self._mark_dirty,
                "filterable_columns": self._mark_dirty,
                "sort_column": self._part_marker("head"),
                "sort_descending": self._part_marker("head"),
                "search": self._part_marker("bar"),
                "filters": self._part_marker("bar"),
                "selected_rows": self._mark_dirty,
                "shown_rows": self._part_marker("body", "count"),
                "editable_columns": self._mark_dirty,
            }
        )

    def _refresh_rows(self, view: TableViewLike, rendered_object: str, value: Any) -> None:
        self._editing = None  # its row may have moved, or be gone
        self._mark_dirty(view, rendered_object, value)

    def _mark_dirty(self, view: TableViewLike, rendered_object: str, value: Any) -> None:
        self._is_whole_dirty = True
        super()._mark_dirty(view, rendered_object, value)

    def _part_marker(self, *parts: str) -> Callable[[TableViewLike, str, Any], None]:
        def mark(_view: TableViewLike, _rendered_object: str, _value: Any) -> None:
            self._mark_parts(*parts)

        return mark

    def _mark_parts(self, *parts: str) -> None:
        dirty = _DIRTY.get()
        if dirty is not None:
            self._dirty_parts.update(parts)
            dirty[self.widget_id] = self

    def to_html(self, *, oob: bool = False) -> str:
        parts, self._dirty_parts = self._dirty_parts, set()
        is_whole, self._is_whole_dirty = self._is_whole_dirty or not oob or not parts, False
        if not is_whole:
            if "bar" in parts:
                parts.discard("count")  # in the bar
            renders = {
                "bar": self._bar_html,
                "head": self._head_html,
                "body": self._body_html,
                "count": self._count_html,
                "error": self._error_html,
            }
            # the bar last: it may hold the element that sent the request, which htmx
            # swaps nothing more from once it's gone
            order = ("head", "body", "count", "error", "bar")
            fragments = "".join(renders[part](oob=True) for part in order if part in parts)
            self._focus_add_filter, self._focused_chip = False, None
            return fragments
        grid = ' role="grid" aria-multiselectable="true"' if self._is_multiple() else ""
        html_ = (
            f'<div {self._root_attributes(oob=oob)} class="flex flex-col gap-2">'
            f"{self._bar_html()}"
            '<div class="overflow-x-auto rounded-box border border-base-300">'
            f'<table class="table table-zebra table-sm"{grid}>'
            f"<thead>{self._head_html()}</thead>{self._body_html()}</table></div></div>"
        )
        self._focus_add_filter, self._focused_chip = False, None
        return html_

    def _oob(self, *, oob: bool) -> str:
        return ' hx-swap-oob="true"' if oob else ""

    def _post(self, values: Mapping[str, str | int]) -> str:
        """Attributes posting an event of the table, without swapping its element back."""
        return (
            f" hx-post=\"/widget/{self.widget_id}\" hx-vals='{html.escape(json.dumps(values))}'"
            ' hx-swap="none"'
        )

    def _head_html(self, *, oob: bool = False) -> str:
        cells = []
        for column, header in enumerate(self._view.headers):
            if column not in self._view.sortable_columns:
                cells.append(f"<th>{html.escape(header)}</th>")
                continue
            order = self._view.sort_descending if self._view.sort_column == column else None
            arrow = {None: "", False: " ▲", True: " ▼"}[order]
            disabled = "" if self.is_enabled else " disabled"
            cells.append(
                f'<th aria-sort="{_ARIA_SORT[order]}" class="p-0">'
                f'<button type="button" class="btn btn-ghost btn-sm w-full justify-start'
                f' font-semibold"{self._post({"event": "sort", "column": column})}{disabled}>'
                f'{html.escape(header)}<span aria-hidden="true">{arrow}</span></button></th>'
            )
        return self._table_part(
            f'<tr id="{self.widget_id}-head"{self._oob(oob=oob)}>{"".join(cells)}</tr>', oob=oob
        )

    def _body_html(self, *, oob: bool = False) -> str:
        shown = self._view.shown_rows
        rows = "".join(self._row_html(index, self._view.rows[index]) for index in shown)
        if len(shown) == 0 and len(self._view.rows) > 0:
            no_match = html.escape(self._view.filter_texts.get("no_match", ""))
            columns = max(len(self._view.headers), 1)
            rows = (
                f'<tr><td colspan="{columns}" class="text-center opacity-70">{no_match}</td></tr>'
            )
        return self._table_part(
            f'<tbody id="{self.widget_id}-body"{self._oob(oob=oob)}>{rows}</tbody>', oob=oob
        )

    @staticmethod
    def _table_part(markup: str, *, oob: bool) -> str:
        """Wrap a part of the `<table>` swapped out of band in a `<template>` of its own.

        htmx parses an answer as a template's content: a `<tr>` or a `<tbody>` among the
        rest would switch the parser to a table's rules for what follows, mangling the
        next fragments, e.g. another table swapped whole.
        """
        return f"<template>{markup}</template>" if oob else markup

    def _count_html(self, *, oob: bool = False) -> str:
        shown, total = len(self._view.shown_rows), len(self._view.rows)
        text = ""
        if shown != total:
            text = self._view.filter_texts.get("count", "").format(shown=shown, total=total)
        return (
            f'<span id="{self.widget_id}-count" class="ms-auto text-sm opacity-70"'
            f' aria-live="polite"{self._oob(oob=oob)}>{html.escape(text)}</span>'
        )

    def _filterable_columns(self) -> list[int]:
        return [
            column for column in self._view.filterable_columns if column < len(self._view.headers)
        ]

    def _bar_html(self, *, oob: bool = False) -> str:
        bar_id = f"{self.widget_id}-bar"
        if len(self._filterable_columns()) == 0:
            return f'<div id="{bar_id}" hidden{self._oob(oob=oob)}></div>'
        texts = self._view.filter_texts
        disabled = "" if self.is_enabled else " disabled"
        search_label = html.escape(texts.get("search", ""))
        search = (
            '<label class="input input-sm w-56">'
            f'{_icon("search")}<input id="{self.widget_id}-search" type="search"'
            f' name="search" value="{html.escape(self._view.search)}"'
            f' placeholder="{search_label}" aria-label="{search_label}"'
            f' hx-post="/widget/{self.widget_id}" hx-trigger="input changed delay:300ms, search"'
            """ hx-vals='{"event": "search"}' hx-swap="none" hx-sync="this:queue last\""""
            f' autocomplete="off"{disabled}></label>'
        )
        if self._editor is None:
            focus = " autofocus" if self._focus_add_filter else ""
            editor = (
                f'<button id="{self.widget_id}-add-filter" type="button"'
                f' class="btn btn-sm btn-soft"{self._post({"event": "open_editor"})}'
                f"{focus}{disabled}>{html.escape(texts.get('add_filter', ''))}</button>"
            )
        else:
            editor = self._editor_html()
        chips = "".join(self._chip_html(column) for column in sorted(self._view.filters))
        clear = ""
        if len(self._view.filters) >= 2:  # noqa: PLR2004
            clear = (
                f'<button type="button" class="btn btn-sm btn-ghost"'
                f"{self._post({'event': 'clear_filters'})}{disabled}>"
                f"{html.escape(texts.get('clear', ''))}</button>"
            )
        return (
            f'<div id="{bar_id}" role="search" class="flex flex-wrap items-center gap-2"'
            f"{self._oob(oob=oob)}>{search}{editor}{chips}{clear}{self._count_html()}</div>"
        )

    def _editor_html(self) -> str:
        assert self._editor is not None
        texts = self._view.filter_texts
        columns = self._filterable_columns()
        column, typed = self._editor
        chosen = column if column in columns else columns[0]
        text, is_pattern = split_pattern(typed)
        takes_pattern = self._view.filter_takes_pattern(chosen)
        is_pattern = is_pattern and takes_pattern
        options = "".join(
            f'<option value="{option}"'
            f' data-placeholder="{html.escape(self._view.filter_placeholder(option))}"'
            f' data-pattern-placeholder="{html.escape(self._pattern_placeholder(option))}"'
            f"{' selected' if option == chosen else ''}>"
            f"{html.escape(self._view.headers[option])}</option>"
            for option in columns
        )
        value_id = f"{self.widget_id}-value"
        value_label = html.escape(texts.get("value", ""))
        pattern_label = html.escape(texts.get("pattern", ""))
        placeholder = self._view.filter_placeholder(chosen, is_pattern=is_pattern)
        # a checkbox drawn as a button: on, the value is a regular expression; the page
        # shows it only for a column a pattern filters, and hints at what to type
        pattern = (
            '<label class="btn btn-sm btn-soft font-mono has-checked:btn-primary"'
            f' title="{pattern_label}" data-filter-pattern{"" if takes_pattern else " hidden"}>'
            f'<input type="checkbox" name="pattern" value="1" class="sr-only"'
            f' aria-label="{pattern_label}"{" checked" if is_pattern else ""}>.*</label>'
        )
        return (
            f'<form id="{self.widget_id}-editor" class="flex flex-wrap items-center gap-2"'
            f"{self._post({'event': 'add_filter'})}>"
            f'<select name="column" class="select select-sm w-auto" data-filter-column'
            f' aria-label="{html.escape(texts.get("column", ""))}">{options}</select>'
            f"{pattern}"
            f'<input id="{value_id}" name="value" class="input input-sm w-60" type="text"'
            f' value="{html.escape(text)}" aria-label="{value_label}"'
            f' placeholder="{html.escape(placeholder)}"'
            f' aria-describedby="{value_id}-error" autocomplete="off" autofocus'
            f' hx-post="/widget/{self.widget_id}" hx-trigger="keydown[key==&apos;Escape&apos;]"'
            """ hx-vals='{"event": "close_editor"}' hx-swap="none">"""
            f"{self._error_html()}"
            f'<button type="submit" class="btn btn-sm btn-primary">'
            f"{html.escape(texts.get('add', ''))}</button></form>"
        )

    def _pattern_placeholder(self, column: int) -> str:
        """Hint at a regular expression filtering `column`, or "" if none does."""
        if not self._view.filter_takes_pattern(column):
            return ""
        return self._view.filter_placeholder(column, is_pattern=True)

    def _error_html(self, *, oob: bool = False) -> str:
        """Render the editor's message, why its text can't filter; the page marks the field."""
        error = self._editor_error
        hidden = "" if error else " hidden"
        return (
            f'<span id="{self.widget_id}-value-error" class="text-sm text-error" data-log="error"'
            f"{hidden}{self._oob(oob=oob)}>{html.escape(error or '')}</span>"
        )

    def _chip_html(self, column: int) -> str:
        if column >= len(self._view.headers):
            return ""
        texts, header = self._view.filter_texts, self._view.headers[column]
        remove = texts.get("remove", "{header}").format(header=header)
        edit = texts.get("edit", "{header}").format(header=header)
        disabled = "" if self.is_enabled else " disabled"
        focus = " autofocus" if self._focused_chip == column else ""
        # named by its text, the filter; the pencil and the tooltip say it edits it
        return (
            '<span class="badge badge-soft badge-primary gap-1 pe-0">'
            f'<button id="{self.widget_id}-chip-{column}" type="button"'
            ' class="inline-flex cursor-pointer items-center gap-1 hover:underline"'
            f' title="{html.escape(edit)}"'
            f"{self._post({'event': 'open_editor', 'column': column})}{focus}{disabled}>"
            f"{html.escape(self._view.filter_chip(column))}{_icon('pencil', 'size-3')}</button>"
            f'<button type="button" class="btn btn-ghost btn-xs btn-circle"'
            f' aria-label="{html.escape(remove)}" title="{html.escape(remove)}"'
            f"{self._post({'event': 'remove_filter', 'column': column})}{disabled}>\u00d7</button>"
            "</span>"
        )

    def _row_html(self, index: int, row: list[str]) -> str:
        # a row short of an editable cell still gets the cell, empty
        width = max(len(row), *(column + 1 for column in self._editable_columns()), 0)
        cells = "".join(
            self._cell_html(index, column, row[column] if column < len(row) else "")
            for column in range(width)
        )
        is_selected = index in self._view.selected_rows
        if self._is_multiple():
            selected = f' aria-selected="{"true" if is_selected else "false"}"'
        else:
            selected = ' aria-current="true"' if is_selected else ""
        if not self.is_enabled:
            return f"<tr{selected}>{cells}</tr>"
        return (
            f'<tr id="{self.widget_id}-row-{index}" class="cursor-pointer" tabindex="0"'
            f'{selected} hx-post="/widget/{self.widget_id}"'
            # not from a cell's field, which takes its own clicks and Enter
            ' hx-trigger="click[target.tagName!=&apos;INPUT&apos;],'
            ' keydown[key==&apos;Enter&apos;&amp;&amp;target.tagName!=&apos;INPUT&apos;]"'
            f""" hx-vals='{{"event": "select", "row": "{index}"}}' hx-swap="none">"""
            f"{cells}</tr>"
        )

    def _cell_html(self, row: int, column: int, text: str) -> str:
        if column not in self._editable_columns() or not self.is_enabled:
            return f"<td>{html.escape(text)}</td>"

        def post(event: str) -> str:
            return (
                f' hx-post="/widget/{self.widget_id}" hx-swap="none"'
                f""" hx-vals='{{"event": "{event}", "row": "{row}", "column": "{column}"}}'"""
            )

        if self._editing != (row, column):
            return (
                f'<td data-edit hx-trigger="dblclick"{post("start_edit")}>{html.escape(text)}</td>'
            )
        header = html.escape(self._view.headers[column])
        # its own id, so htmx gives it the focus back when the table is swapped
        return (
            f'<td class="p-0"><input id="{self.widget_id}-cell-{row}-{column}" type="text"'
            ' class="input input-ghost input-sm w-full min-w-0" name="text" data-cell'
            f' value="{html.escape(text)}" data-original="{html.escape(text)}"'
            f' aria-label="{header}" autocomplete="off" autofocus'
            ' hx-trigger="keydown[key==&apos;Enter&apos;], blur"'
            f"{post('edit')}></td>"
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a disabled table can't be clicked: a post saying otherwise is refused
        if not self.is_enabled:
            super().dispatch(event, form)
        if event in ("start_edit", "edit"):
            self._edit(event, form)
            return
        handlers = {
            "sort": self._sort,
            "search": self._search,
            "open_editor": self._open_editor,
            "close_editor": self._close_editor,
            "add_filter": self._add_filter,
            "remove_filter": self._remove_filter,
            "clear_filters": self._clear_filters,
        }
        if event in handlers:
            handlers[event](form)
            return
        if event != "select":
            super().dispatch(event, form)
        row = form.get("row", "")
        if not row.isdigit() or int(row) not in self._view.shown_rows:
            # a row a stale page still shows: swap the table back as it now is
            self._mark_dirty(self._view, self.widget_id, self._view.rows)
            return
        if self._is_multiple():
            rows = sorted(set(self._view.selected_rows) ^ {int(row)})
        elif self._view.selected_rows == [int(row)]:
            return
        else:
            rows = [int(row)]
        self._view.selected_rows = rows
        self._view.selection_changed.emit(rows)

    def _column(self, form: Mapping[str, str], columns: list[int]) -> int | None:
        """Get the column posted, if one of `columns`: a stale page may post another."""
        column = form.get("column", "")
        return int(column) if column.isdigit() and int(column) in columns else None

    def _sort(self, form: Mapping[str, str]) -> None:
        column = self._column(form, self._view.sortable_columns)
        if column is None:
            self._mark_parts("head", "body")  # as it now is
            return
        self._view.sort_by(column)

    def _search(self, form: Mapping[str, str]) -> None:
        # not swapped back: the user is typing in it
        with self.stop_refresh():
            self._view.search = form.get("search", "")

    def _open_editor(self, form: Mapping[str, str]) -> None:
        column = self._column(form, self._filterable_columns())
        text = self._view.filters.get(column, "") if column is not None else ""
        self._editor, self._editor_error = (column, text), None
        self._mark_parts("bar")

    def _close_editor(self, _form: Mapping[str, str]) -> None:
        self._editor, self._editor_error = None, None
        self._focus_add_filter = True
        self._mark_parts("bar")

    def _add_filter(self, form: Mapping[str, str]) -> None:
        column = self._column(form, self._filterable_columns())
        if column is None or self._editor is None:
            self._mark_parts("bar")  # a stale page: the bar as it now is
            return
        text = form.get("value", "")
        if form.get("pattern") == "1" and self._view.filter_takes_pattern(column):
            text = as_pattern(text)
        error = self._view.filter_error(column, text)
        if error is not None:
            # the field keeps the text typed: only its message is swapped in
            self._editor, self._editor_error = (column, text), error
            self._mark_parts("error")
            return
        self._close_editor(form)
        self._focus_add_filter, self._focused_chip = False, column
        self._view.filters = {**self._view.filters, column: text}

    def _remove_filter(self, form: Mapping[str, str]) -> None:
        column = self._column(form, list(self._view.filters))
        self._focus_add_filter = True
        self._mark_parts("bar")
        if column is not None:
            self._view.filters = {
                other: text for other, text in self._view.filters.items() if other != column
            }

    def _clear_filters(self, _form: Mapping[str, str]) -> None:
        self._focus_add_filter = True
        self._mark_parts("bar")
        self._view.filters = {}

    def _edit(self, event: str, form: Mapping[str, str]) -> None:
        """Start editing a cell, or end it with the text posted."""
        # either way the table comes back: with the field, or with the cell's text
        self._mark_dirty(self._view, self.widget_id, self._view.rows)
        row, column = form.get("row", ""), form.get("column", "")
        if (
            not row.isdigit()
            or int(row) not in self._view.shown_rows
            or not column.isdigit()
            or int(column) not in self._editable_columns()
        ):
            return  # a cell a stale page still shows
        cell = (int(row), int(column))
        if event == "start_edit":
            self._editing = cell
            return
        if self._editing != cell:
            return  # a field already gone, e.g. leaving it after Enter
        self._editing = None
        cells, text = self._view.rows[cell[0]], form.get("text", "")
        if text == (cells[cell[1]] if cell[1] < len(cells) else ""):
            return
        rows = self._view.rows
        self._view.emit_cell_edited(*cell, text)
        # unless the app answered with its own rows, which it has marked to show
        if self._view.rows is rows:
            with self.stop_refresh():
                self._view.rows = replace_cell(rows, *cell, text)

    def _editable_columns(self) -> list[int]:
        """`editable_columns` the table has a header for."""
        return [
            column
            for column in self._view.editable_columns
            if 0 <= column < len(self._view.headers)
        ]

    def _is_multiple(self) -> bool:
        return self._view.selection_mode is SelectionMode.MULTIPLE


TValue = TypeVar("TValue")


class ValuesViewLike(ViewLike, Protocol, Generic[TValue]):
    value: TValue | None
    values: dict[str, TValue]
    value_changed: Signal[TValue | None]

    @property
    def options(self) -> list[tuple[str, str]]: ...

    def serialize_value(self) -> str | None: ...

    def deserialize_value(self, key: str | None) -> TValue | None: ...


class _WebValuesRenderer(WebRenderer[ValuesViewLike[TValue]], Generic[TValue]):
    """A choice among `values`, identified on the wire by its key (see `options`).

    The same key as `serialize_value`/`deserialize_value`, which also turn a stale or
    bogus key into `None` with a warning instead of the `ValueError` `_check_value`
    would raise.
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
        key = form.get(self.widget_id, "")
        value = None if key == "" else self._view.deserialize_value(key)
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
        disabled = "" if self.is_enabled else " disabled"
        options = "".join(
            '<label class="label cursor-pointer gap-2 text-base-content">'
            f'<input type="radio" class="radio radio-sm radio-primary" value="{html.escape(key)}"'
            f"{' checked' if key == selected else ''}{self._htmx_attributes()}"
            f' autocomplete="off"{disabled}>'
            f"{html.escape(label)}</label>"
            for key, label in self._view.options
        )
        return (
            f'<div {self._root_attributes(oob=oob)}{self._row_attributes()} role="radiogroup"'
            f' class="flex flex-wrap gap-x-6 gap-y-2">{options}</div>'
        )


class WebComboboxRenderer(_WebValuesRenderer[TValue]):
    _role = "combobox"

    def to_html(self, *, oob: bool = False) -> str:
        selected = self._view.serialize_value()
        disabled = "" if self.is_enabled else " disabled"
        # an empty choice only while nothing is selected, as Qt's combobox shows nothing
        empty = '<option value="" selected></option>' if selected is None else ""
        options = "".join(
            f'<option value="{html.escape(key)}"'
            f"{' selected' if key == selected else ''}>{html.escape(label)}</option>"
            for key, label in self._view.options
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


class MarkdownViewLike(ViewLike, Protocol):
    text: str


class WebMarkdownRenderer(WebRenderer[MarkdownViewLike]):
    """Markdown as HTML, tables included, as Qt and Textual show them.

    Raw HTML is off: the text can't inject markup (and markdown-it refuses `javascript:`
    links).
    """

    _role = "markdown"

    def __init__(self, view: MarkdownViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> str:
        parser = MarkdownIt("commonmark", {"html": False}).enable("table")
        return (
            f'<div {self._root_attributes(oob=oob)} class="cui-markdown">'
            f"{parser.render(self._view.text)}</div>"
        )


class WebFormLabelRenderer(WebRenderer[FormLabelRowView]):
    """The label of a form row, pointing at the row's field for clicks/screen readers.

    With help, a "?" button beside the label opens it in a popover: a click, a tap, or
    Enter once Tab reached it, as hovering can't on a phone. The button is outside the
    `<label>`, so it isn't part of the field's name.
    """

    _role = "form_label"

    def __init__(self, view: FormLabelRowView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._mark_dirty,
                "help": self._refresh_help,
                "help_button_text": self._mark_dirty,
            }
        )

    @property
    def text_id(self) -> str:
        """Id of the `<label>` itself, which names a field `<label for>` can't."""
        return f"{self.widget_id}-text"

    @property
    def help_id(self) -> str:
        """Id of the row's help, which describes the field while there is help."""
        return f"{self.widget_id}-help"

    def has_help(self) -> bool:
        return self._view.help != ""

    def to_html(self, *, oob: bool = False) -> str:
        field = self._field_renderer()
        # a radio group or a checkbox is a `<div>`, which isn't labelable: its
        # `aria-labelledby` names it instead
        target = f' for="{field.widget_id}"' if field.is_labelable else ""
        return (
            f'<div {self._root_attributes(oob=oob)} class="flex items-center gap-1">'
            f'<label id="{self.text_id}"{target}'
            ' class="label text-sm font-medium text-base-content"'
            f">{html.escape(self._view.label)}</label>{self._help_html()}</div>"
        )

    def _help_html(self) -> str:
        """Render the "?" button and the help it opens, which also describes the field.

        Closed, the popover is hidden, which `aria-describedby` still reads. The page's
        script places it beside the button (see `page.py`).
        """
        if not self.has_help():
            return ""
        return (
            f'<button type="button" popovertarget="{self.help_id}"'
            ' class="inline-flex cursor-pointer rounded-full text-base-content/40'
            " transition-colors hover:text-primary focus-visible:text-primary"
            ' focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"'
            f' aria-label="{html.escape(self._view.help_button_text)}">{_icon("help")}</button>'
            # `cui-help`: the arrow pointing at the button, see `css/app.css`
            f'<div id="{self.help_id}" popover data-help class="cui-help m-0 w-max max-w-80'
            " rounded-field border border-base-300 bg-base-100 px-3 py-2 text-xs"
            ' leading-relaxed text-base-content shadow-lg">'
            f"{html.escape(self._view.help)}</div>"
        )

    def _refresh_help(self, view: FormLabelRowView, rendered_object: str, value: str) -> None:
        self._mark_dirty(view, rendered_object, value)
        dirty = _DIRTY.get()
        if dirty is not None and (view.help == "") != (value == ""):
            # its `aria-describedby` gains or loses the help
            field = self._field_renderer()
            dirty[field.widget_id] = field

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
        if isinstance(view, FormRowView):
            # carried by the log, not the field: swapping a field being typed in would
            # reset its caret
            self._refresh_dispatcher["has_form_error"] = self._mark_dirty

    def to_html(self, *, oob: bool = False) -> str:
        attributes = self._root_attributes(oob=oob)
        if self._view.is_visible and self._view.log_message == "":
            attributes += " hidden"  # same as Qt/Textual: an empty log takes no room
        if isinstance(self._view, FormRowView) and self._view.has_form_error:
            attributes += " data-form-error"  # a check of the form failed on this row
        # `pre-line`: `FormView.validate` joins its messages with newlines.
        # `data-log`, `data-form-error`: the page's stylesheet and script mark the field
        # just before the log as invalid
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

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> str:
        return self._fieldset(oob=oob, classes="flex min-w-0 flex-col gap-5", legend="")

    def _fieldset(self, *, oob: bool, classes: str, legend: str) -> str:
        disabled = "" if self.is_enabled else " disabled"
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
            classes="fieldset form-grid min-w-0 gap-4 rounded-box border border-base-300"
            " bg-base-200 p-4",
            legend=(
                '<legend class="fieldset-legend px-1 text-sm font-semibold text-primary">'
                f"{html.escape(title)}</legend>"
            ),
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
            ' class="status-bar fixed inset-x-0 bottom-0 z-20 flex min-h-9 items-center gap-2'
            ' border-t border-base-300 px-4 text-sm">'
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


#: a header button's icon, by the kind of action it runs (Lucide's, inlined: no CDN)
_ICONS: Final[dict[str, str]] = {
    "new": '<path d="M12 5v14M5 12h14"/>',
    "open": '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
    "save": '<path d="M12 3v12M7 10l5 5 5-5"/>'
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/>'
    '<circle cx="19" cy="12" r="1"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "help": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
    '<path d="M12 17h.01"/>',
    "pencil": '<path d="M21.17 6.81a1 1 0 0 0-3.98-3.98L3.84 16.17a2 2 0 0 0-.5.83l-1.32'
    ' 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z"/><path d="m15 5 4 4"/>',
    "sidebar": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>',
    "calendar": (
        '<rect x="3" y="4" width="18" height="18" rx="2"/>'
        '<path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>'
    ),
    "circle-check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "circle-alert": '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    "circle-x": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
}

#: a tree node's mark: its icon and its color, as a log's are colored
_MARK_ICONS: Final = {
    NodeMark.DONE: ("circle-check", "text-success"),
    NodeMark.WARNING: ("circle-alert", "text-warning"),
    NodeMark.ERROR: ("circle-x", "text-error"),
}


def _icon(name: str, size: str = "size-4") -> str:
    return (
        f'<svg class="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{_ICONS[name]}</svg>"
    )


def _file_icon(icon: str | None) -> str:
    """Show an action's icon file, or nothing without one (see `icons.py`).

    An SVG is drawn in the text's color, as the built-in icons are, so it follows the
    theme: only its shape counts. Any other image shows as it is.
    """
    url = None if icon is None else icon_url(icon)
    if url is None:
        return ""
    if url.endswith(".svg"):
        mask = f"url('{url}') center / contain no-repeat"
        return (
            '<span aria-hidden="true" class="size-4 shrink-0 bg-current"'
            f' style="mask: {mask}; -webkit-mask: {mask}"></span>'
        )
    return f'<img src="{url}" alt="" aria-hidden="true" class="size-4 shrink-0 object-contain">'


class Placement(enum.Enum):
    """Where a menu's action shows in the header (see `WebMenuRenderer`)."""

    ITEM = "item"  # an item of a dropdown
    BUTTON = "button"  # a button of its own
    PAGE = "page"  # a link to a page, in the header's toolbar of pages
    TOOL = "tool"  # a button of a `ToolBar`
    OMITTED = "omitted"  # not shown: Save As next to Save (both download), Exit


def _between_items(items: list[tuple[bool, str]]) -> list[tuple[bool, str]]:
    """Keep only the separators between two items: the others separated buttons."""
    kept: list[tuple[bool, str]] = []
    for is_separator, item in items:
        if is_separator and (len(kept) == 0 or kept[-1][0]):
            continue
        kept.append((is_separator, item))
    if len(kept) > 0 and kept[-1][0]:
        kept.pop()
    return kept


class WebMenuRenderer(WebRenderer[Menu]):
    """A menu in the header, shaped like a web app's rather than a desktop menu bar.

    A menu with New, Open or Save actions (`FileMenu`) puts them in plain sight as
    header buttons, Save highlighted, and any other action in a "⋯" dropdown named after
    the menu. Save As is left out next to Save, as in a browser both download the same
    file, and so is Exit: a web page is left by closing its tab, and New already starts
    over. Any other menu is a dropdown under its title.

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
        has_save = any(isinstance(child, SaveAction) for child in self._view.children_views)
        buttons: list[str] = []
        items: list[tuple[bool, str]] = []  # (is a separator, its html)
        for child in self._view.children_views:
            renderer = child.renderer
            if not isinstance(renderer, WebRenderer):
                continue
            if isinstance(renderer, WebActionRenderer):
                renderer.placement = self._placement(child, has_save=has_save)
                if renderer.placement is not Placement.ITEM:
                    buttons.append(renderer.to_html())
                    continue
            items.append((isinstance(child, SeparatorAction), renderer.to_html()))
        items = _between_items(items)
        title = html.escape(self._view.title)
        if len(buttons) == 0:
            # a chevron: it opens a menu, unlike the header buttons next to it
            trigger = (
                '<div tabindex="0" role="button" class="btn btn-ghost btn-sm gap-1 pr-2"'
                ' aria-haspopup="menu">'
                f'{title}<span class="opacity-60">{_icon("chevron")}</span></div>'
            )
        else:
            trigger = (
                '<div tabindex="0" role="button" class="btn btn-ghost btn-sm btn-square"'
                f' aria-label="{title}" title="{title}">{_icon("more")}</div>'
            )
        dropdown = (
            '<div class="dropdown dropdown-end">'
            f"{trigger}"
            # as wide as its longest item, its text and shortcut on one line
            '<ul tabindex="0" class="menu dropdown-content z-30 mt-2 w-max min-w-56'
            ' rounded-box border border-base-300 bg-base-100 p-2 shadow-lg">'
            f"{''.join(item for _, item in items)}</ul></div>"
            if len(items) > 0
            else ""
        )
        return (
            f'<div id="{self.widget_id}"{oob_attribute} class="flex items-center gap-1">'
            f"{''.join(buttons)}{dropdown}</div>"
        )

    @staticmethod
    def _placement(action: View, *, has_save: bool) -> Placement:
        if isinstance(action, SaveAsAction):
            return Placement.OMITTED if has_save else Placement.BUTTON
        if isinstance(action, ExitAppAction):
            return Placement.OMITTED
        if isinstance(action, (NewAction, SaveAction, OpenFileAction)):
            return Placement.BUTTON
        return Placement.ITEM

    def _ignore(self, _view: Menu, _rendered_object: str, _value: Any) -> None:
        pass


class WebActionRenderer(WebRenderer[ActionView]):
    """A menu or toolbar action posting `triggered`; Save/Open are a download and an upload.

    Those two can't go through the generic widget event: a download has to be a plain
    link, and a file has to be uploaded. Both name the action (`trigger`), so its
    `triggered` still fires first, for whatever user code is connected to it.
    """

    _role = "action"

    def __init__(self, view: ActionView) -> None:
        super().__init__(view)
        #: the file types Open's picker offers, e.g. ".hello"; an action doesn't know its
        #: main view, so `WebMainRenderer.render` sets it
        self.accept: str | None = None
        #: set by its menu or toolbar: kept for when the action is swapped on its own
        self.placement = Placement.ITEM
        #: the address of the page a page's action shows, set by `WebRouterRenderer`
        self.href: str | None = None
        #: whether the page has it: a menu, a toolbar or a router put it there
        self._is_shown = False
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("text", "icon", "data", "shortcut", "is_checkable", "is_checked"),
                self._mark_dirty,
            )
        )
        if isinstance(view, PickFileAction):
            self._refresh_dispatcher["extensions"] = self._mark_dirty  # the picker's types

    def _mark_dirty(self, view: ActionView, rendered_object: str, value: Any) -> None:
        # e.g. the entry of a page outside a router: no element on the page to swap
        if self._is_shown:
            super()._mark_dirty(view, rendered_object, value)

    def to_html(self, *, oob: bool = False) -> str:
        self._is_shown = True
        if self.placement is Placement.OMITTED:
            return f"<span {self._root_attributes(oob=oob)} hidden></span>"
        if self.placement is Placement.BUTTON:
            return self._button_html(oob=oob)
        if self.placement is Placement.PAGE:
            return self._page_link_html(oob=oob)
        if self.placement is Placement.TOOL:
            return self._tool_html(oob=oob)
        view = self._view
        check = "✓ " if view.is_checkable and view.is_checked else ""
        shortcut = _web_shortcut(view.shortcut)
        # the shortcut a hint, lighter than the action's text and kept apart from it
        kbd = (
            f'<kbd class="ml-6 font-sans text-xs text-base-content/50">{shortcut[0]}</kbd>'
            if shortcut
            else ""
        )
        label = (
            '<span class="flex items-center gap-2 whitespace-nowrap">'
            f"{_file_icon(view.icon)}{check}{html.escape(view.text)}</span>{kbd}"
        )
        key = f' data-shortcut="{shortcut[1]}"' if shortcut else ""
        if not view.is_enabled:
            item = f'<button type="button" class="justify-between" disabled>{label}</button>'
        else:
            item = self._active_html('class="justify-between"', label, key)
        menu_disabled = "" if view.is_enabled else ' class="menu-disabled"'
        return f"<li {self._root_attributes(oob=oob)}{menu_disabled}>{item}</li>"

    def _button_html(self, *, oob: bool) -> str:
        """Render a header button: Save the highlighted one, its shortcut in the tooltip."""
        view = self._view
        shortcut = _web_shortcut(view.shortcut)
        text = html.escape(view.text)
        tooltip = f"{text} ({shortcut[0]})" if shortcut else text
        style = "btn-primary" if isinstance(view, SaveAction) else "btn-ghost"
        icon = _file_icon(view.icon)
        if icon == "":
            if isinstance(view, NewAction):
                icon = _icon("new")
            else:
                icon = _icon("open" if isinstance(view, OpenFileAction) else "save")
        attributes = (
            f'{self._root_attributes(oob=oob)} class="btn btn-sm {style}" title="{tooltip}"'
        )
        label = f'{icon}<span class="toolbar-label">{text}</span>'
        if not view.is_enabled:
            return f'<button {attributes} type="button" disabled>{label}</button>'
        key = f' data-shortcut="{shortcut[1]}"' if shortcut else ""
        return self._active_html(attributes, label, key)

    def _tool_html(self, *, oob: bool) -> str:
        """Render a toolbar button, pressed while checked, its shortcut in the tooltip.

        With an icon, it keeps only the icon on a phone, as the header's buttons do: the
        tooltip then names it.
        """
        view = self._view
        shortcut = _web_shortcut(view.shortcut)
        text = html.escape(view.text)
        icon = _file_icon(view.icon)
        label = f'{icon}<span class="toolbar-label">{text}</span>' if icon else text
        if shortcut:
            tooltip = f' title="{text} ({shortcut[0]})"'
        else:
            tooltip = f' title="{text}"' if icon else ""
        is_checked = view.is_checkable and view.is_checked
        active = " btn-active" if is_checked else ""
        pressed = f' aria-pressed="{str(is_checked).lower()}"' if view.is_checkable else ""
        attributes = (
            f'{self._root_attributes(oob=oob)} class="btn btn-ghost btn-sm{active}"'
            f"{tooltip}{pressed}"
        )
        if not self.is_enabled:
            return f'<button {attributes} type="button" disabled>{label}</button>'
        key = f' data-shortcut="{shortcut[1]}"' if shortcut else ""
        return self._active_html(attributes, label, key)

    def _page_link_html(self, *, oob: bool) -> str:
        """Render a toolbar link to a page: still a link to its address, for a new tab.

        A click posts `triggered` instead of following the link: the router navigates,
        and the response puts the page's address in the browser's history.
        """
        view = self._view
        is_current = view.is_checkable and view.is_checked
        shortcut = _web_shortcut(view.shortcut)
        text = html.escape(view.text)
        tooltip = f' title="{text} ({shortcut[0]})"' if shortcut else ""
        icon = _file_icon(view.icon)
        label = f"{icon}{text}"
        gap = " gap-2" if icon else ""
        classes = f"tab tab-active{gap}" if is_current else f"tab{gap}"
        current = ' aria-current="page"' if is_current else ""
        if not view.is_enabled:
            return (
                f'<a {self._root_attributes(oob=oob)} class="tab tab-disabled{gap}"'
                f' aria-disabled="true"{tooltip}>{label}</a>'
            )
        key = f' data-shortcut="{shortcut[1]}"' if shortcut else ""
        href = html.escape(self.href or "")
        return (
            f'<a {self._root_attributes(oob=oob)} class="{classes}" href="{href}"{current}'
            f'{tooltip} hx-post="/widget/{self.widget_id}"'
            f""" hx-vals='{{"event": "triggered"}}' hx-swap="none"{key}>{label}</a>"""
        )

    def _active_html(self, attributes: str, label: str, key: str) -> str:
        """Render the element a click (or the page's key handler, through `key`) activates."""
        view = self._view
        if isinstance(view, (SaveAction, SaveAsAction)):
            return (
                f'<a {attributes} href="/state?trigger={self.widget_id}" download'
                f" {_CLOSE_DROPDOWN}{key}>{label}</a>"
            )
        if isinstance(view, OpenFileAction):
            accept = "" if self.accept is None else f' accept="{html.escape(self.accept)}"'
            return (
                f'<label {attributes}>{label}<input type="file" name="file"{accept}'
                ' class="hidden" hx-post="/state" hx-encoding="multipart/form-data"'
                f' hx-trigger="change" hx-vals=\'{{"trigger": "{self.widget_id}"}}\''
                f' hx-swap="none" autocomplete="off" {_CLOSE_DROPDOWN}{key}></label>'
            )
        if isinstance(view, PickFileAction):
            types = ",".join(self.file_types)
            accept = f' accept="{html.escape(types)}"' if types else ""
            # emptied once sent: picking the same file again is a change too
            return (
                f'<label {attributes}>{label}<input type="file" name="file"{accept}'
                f' class="hidden" hx-post="/widget/{self.widget_id}/file"'
                ' hx-encoding="multipart/form-data" hx-trigger="change" hx-swap="none"'
                ' hx-on::after-request="this.value = \'\'" autocomplete="off"'
                f" {_CLOSE_DROPDOWN}{key}></label>"
            )
        return (
            f'<button {attributes} type="button"'
            f' hx-post="/widget/{self.widget_id}" hx-vals=\'{{"event": "triggered"}}\''
            f' hx-swap="none" {_CLOSE_DROPDOWN}{key}>{label}</button>'
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # `is_enabled`: an action of a disabled toolbar is disabled with it
        if event != "triggered" or not self.is_enabled:
            super().dispatch(event, form)
        self._view.triggered.emit()

    @property
    def file_types(self) -> list[str]:
        """Get the file types a `PickFileAction` offers, e.g. [".md"]; empty for any."""
        view = self._view
        if not isinstance(view, PickFileAction):
            return []
        return list(dict.fromkeys(t.lower() for ts in view.extensions.values() for t in ts))

    def pick_file(self, path: Path) -> None:
        """Hand the file a `PickFileAction`'s picker uploaded to its `file_picked`.

        Its `triggered` first, as on the other backends (its own picker answers nothing
        on the web). Raises `UnsupportedEventError` for any other action.
        """
        view = self._view
        if not isinstance(view, PickFileAction) or not self.is_enabled:
            raise UnsupportedEventError(self, "file")
        view.triggered.emit()
        view.file_picked.emit(path)


class WebSeparatorRenderer(WebRenderer[SeparatorAction]):
    _role = "separator"

    def __init__(self, view: SeparatorAction) -> None:
        super().__init__(view)
        #: set by its toolbar: a bar between buttons rather than a menu's line
        self.is_in_toolbar = False

    def to_html(self, *, oob: bool = False) -> str:
        if self.is_in_toolbar:
            return (
                f'<div {self._root_attributes(oob=oob)} role="separator"'
                ' aria-orientation="vertical" class="mx-1 h-5 w-px bg-base-300"></div>'
            )
        return (
            f'<li {self._root_attributes(oob=oob)} role="separator">'
            '<hr class="my-1 border-base-300 p-0"></li>'
        )


class WebToolBarRenderer(WebRenderer[ToolBar]):
    """A row of buttons in the header, one per action, posting `triggered`."""

    _role = "toolbar"

    def __init__(self, view: ToolBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._mark_dirty})

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)
        # the children are rendered first: make them a toolbar's
        for child in self._view.children_views:
            if isinstance(child.renderer, WebActionRenderer):
                child.renderer.placement = Placement.TOOL
            elif isinstance(child.renderer, WebSeparatorRenderer):
                child.renderer.is_in_toolbar = True

    def to_html(self, *, oob: bool = False) -> str:
        items = _between_items(
            [
                (isinstance(child, SeparatorAction), child.renderer.to_html())
                for child in self._view.children_views
                if isinstance(child.renderer, WebRenderer)
            ]
        )
        title = html.escape(self._view.title)
        label = f' aria-label="{title}"' if title else ""
        return (
            f'<div {self._root_attributes(oob=oob)} role="toolbar"{label}'
            ' class="flex items-center gap-1">'
            f"{''.join(item for _, item in items)}</div>"
        )


class WebDialogRenderer(WebRenderer[DialogView]):
    """A modal `<dialog>`, opened by the page's script once swapped in shown.

    The main renderer puts every dialog at the end of the page, outside any page's
    slot, which hides its content. A button closes the dialog in the browser, so focus
    goes back where it was, then posts its answer; Escape posts a dismissal. The
    server then swaps the dialog closed: it isn't the button's own fragment, and is
    closed already.
    """

    _role = "dialog"

    def __init__(self, view: DialogView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(("title", "text", "kind", "accept_text", "reject_text"), self._mark_dirty)
        )

    def to_html(self, *, oob: bool = False) -> str:
        view = self._view
        title_id = f"{self.widget_id}-title"
        text_id = f"{self.widget_id}-text"
        disabled = "" if self.is_enabled else " disabled"
        reject = (
            self._button_html("reject", view.reject_text, "btn", disabled)
            if view.kind is DialogKind.CONFIRM
            else ""
        )
        accept = self._button_html("accept", view.accept_text, "btn btn-primary", disabled)
        # a disabled dialog can't be closed: its answer would be ignored
        cancel = (
            f' hx-post="/widget/{self.widget_id}" hx-trigger="cancel"'
            """ hx-vals='{"event": "dismiss"}'"""
            if self.is_enabled
            else ' oncancel="event.preventDefault()"'
        )
        title = (
            f'<h2 id="{title_id}" class="text-lg font-bold">{html.escape(view.title)}</h2>'
            if view.title
            else ""
        )
        labelledby = f' aria-labelledby="{title_id}"' if view.title else ""
        return (
            f'<dialog {self._root_attributes(oob=oob)} class="modal" data-dialog'
            f'{labelledby} aria-describedby="{text_id}"{cancel} hx-swap="none">'
            f'<div class="modal-box">{title}'
            f'<p id="{text_id}" class="py-4 whitespace-pre-line">{html.escape(view.text)}</p>'
            f'<div class="modal-action">{reject}{accept}</div></div></dialog>'
        )

    def _button_html(self, event: str, text: str, classes: str, disabled: str) -> str:
        # the dialog's own `close`, not `cancel`: no dismissal posted on top of the answer
        autofocus = " autofocus" if event == "accept" else ""
        return (
            f'<button type="button" class="{classes}" hx-post="/widget/{self.widget_id}"'
            f""" hx-vals='{{"event": "{event}"}}'"""
            f""" onclick="this.closest('dialog').close()"{autofocus}{disabled}>"""
            f"{html.escape(text)}</button>"
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        answers = {
            "accept": self._view.accept,
            "reject": self._view.reject,
            "dismiss": self._view.dismiss,
        }
        answer = answers.get(event)
        if answer is None:
            super().dispatch(event, form)
            return
        if self.is_enabled:
            answer()


class WebFormDialogRenderer(WebDialogRenderer):
    """A modal `<dialog>` holding its form, then Cancel and OK.

    OK is disabled while a check of the form fails, and only it swaps when that changes:
    the dialog itself, swapped while open, would take back what the user is typing.
    Unlike a message's, OK doesn't close the dialog in the browser: the form may refuse
    it, the dialog then staying open with its checks shown; the server swaps it closed
    once accepted. Cancel and Escape close it first, as for any dialog.
    """

    _role = "form_dialog"

    def __init__(self, view: FormDialogView) -> None:
        super().__init__(view)
        self._form_view = view
        #: whether more than OK changed since the dialog was last sent: then it swaps whole
        self._is_whole = False
        self._refresh_dispatcher["is_accept_enabled"] = self._refresh_accept

    def render(self) -> None:
        super().render()
        self._adopt([self._form_view.form])

    @property
    def accept_id(self) -> str:
        return f"{self.widget_id}-accept"

    def to_html(self, *, oob: bool = False) -> str:
        is_whole, self._is_whole = self._is_whole, False
        if oob and not is_whole:
            return self._accept_html(oob=True)
        view = self._form_view
        title_id = f"{self.widget_id}-title"
        text_id = f"{self.widget_id}-text"
        disabled = "" if self.is_enabled else " disabled"
        reject = self._button_html("reject", view.reject_text, "btn", disabled)
        cancel = (
            f' hx-post="/widget/{self.widget_id}" hx-trigger="cancel"'
            """ hx-vals='{"event": "dismiss"}'"""
            if self.is_enabled
            else ' oncancel="event.preventDefault()"'
        )
        title = (
            f'<h2 id="{title_id}" class="text-lg font-bold">{html.escape(view.title)}</h2>'
            if view.title
            else ""
        )
        text = (
            f'<p id="{text_id}" class="whitespace-pre-line">{html.escape(view.text)}</p>'
            if view.text
            else ""
        )
        labelledby = f' aria-labelledby="{title_id}"' if view.title else ""
        describedby = f' aria-describedby="{text_id}"' if view.text else ""
        form = view.form.renderer
        form_html = form.to_html() if isinstance(form, WebRenderer) else ""
        return (
            f'<dialog {self._root_attributes(oob=oob)} class="modal" data-dialog'
            f'{labelledby}{describedby}{cancel} hx-swap="none">'
            f'<div class="modal-box flex flex-col gap-4">{title}{text}{form_html}'
            f'<div class="modal-action">{reject}{self._accept_html(oob=False)}</div>'
            "</div></dialog>"
        )

    def _accept_html(self, *, oob: bool) -> str:
        swap = ' hx-swap-oob="true"' if oob else ""
        disabled = "" if self.is_enabled and self._form_view.is_accept_enabled else " disabled"
        return (
            f'<button id="{self.accept_id}" type="button" class="btn btn-primary"{swap}'
            f' hx-post="/widget/{self.widget_id}"'
            f""" hx-vals='{{"event": "accept"}}'{disabled}>"""
            f"{html.escape(self._form_view.accept_text)}</button>"
        )

    def _refresh_accept(self, view: DialogView, rendered_object: str, value: Any) -> None:
        super()._mark_dirty(view, rendered_object, value)

    def _mark_dirty(self, view: DialogView, rendered_object: str, value: Any) -> None:
        self._is_whole = True
        super()._mark_dirty(view, rendered_object, value)


class WebPageRenderer(WebRenderer[PageView]):
    """A page's views in a column, like the main view's own."""

    _role = "page"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.content_views)

    def to_html(self, *, oob: bool = False) -> str:
        content = "".join(
            view.renderer.to_html()
            for view in self._view.content_views
            # at the end of the page instead (see `WebDialogRenderer`)
            if isinstance(view.renderer, WebRenderer) and not isinstance(view, DialogView)
        )
        return (
            f"<section {self._root_attributes(oob=oob)}"
            f' data-width="{self._view.width.name.lower()}" class="flex flex-col gap-6">'
            f"{content}</section>"
        )


class WebHorizontalRenderer(WebRenderer[HorizontalView]):
    """Views side by side, each as wide as its share of the row.

    Each view sits in a cell carrying its share, an inline style rather than a class
    per share; the cell hides with its view, which swaps on its own. A row narrower than
    42rem stacks its views instead, as a column, unless none has a share (e.g. buttons):
    the share is a variable only the wide row's cells use.
    """

    _role = "horizontal"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> str:
        stretched_views = self._view.stretched_views
        if not any(stretch > 0 for _, stretch in stretched_views):
            # as wide as their content: a container query would measure them as 0 wide
            cells = "".join(
                '<div class="min-w-0 has-[>[hidden]]:hidden" style="flex: none">'
                f"{view.renderer.to_html()}</div>"
                for view, _ in stretched_views
                if isinstance(view.renderer, WebRenderer)
            )
            align = " justify-end" if self._view.align is Align.END else ""
            return f'<div {self._root_attributes(oob=oob)} class="flex gap-6{align}">{cells}</div>'
        cells = "".join(
            '<div class="min-w-0 has-[>[hidden]]:hidden @2xl:flex-(--share)"'
            # no share: as wide as its content
            f' style="--share: {f"{stretch} 1 0%" if stretch > 0 else "none"}">'
            f"{view.renderer.to_html()}</div>"
            for view, stretch in stretched_views
            if isinstance(view.renderer, WebRenderer)
        )
        # the row's own width is queried from its root, the views laid out inside it
        return (
            f'<div {self._root_attributes(oob=oob)} class="@container">'
            f'<div class="flex flex-col gap-6 @2xl:flex-row">{cells}</div></div>'
        )


class WebVerticalRenderer(WebRenderer[VerticalView]):
    """Views one above the other, at the top of the column, like a page's."""

    _role = "vertical"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> str:
        content = "".join(
            view.renderer.to_html()
            for view in self._view.children_views
            if isinstance(view.renderer, WebRenderer)
        )
        return f'<div {self._root_attributes(oob=oob)} class="flex flex-col gap-6">{content}</div>'


class WebSplitterRenderer(WebRenderer[SplitterView]):
    """Panes side by side, each in a cell as wide as its share, a border between two.

    A border is an ARIA window splitter (a focusable separator) the user drags, or moves
    with the arrow keys; the browser shares the width between the panes beside it at
    once (see `page.py`), then posts every pane's width (`resize`): like every control,
    the splitter is never swapped back after one. A splitter narrower than 42rem stacks
    its panes, as a row does, without borders; side by side, a pane is at least 12rem
    wide, for its text to be read. A border shows only between panes shown (see
    `app.css`), as a pane hides and swaps on its own. Vertical, the panes share its
    height, 32rem, one above the other, each scrolling within its share.
    """

    _role = "splitter"

    def __init__(self, view: SplitterView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["sizes"] = self._mark_dirty

    def render(self) -> None:
        super().render()
        self._adopt(self._view.panes)

    def to_html(self, *, oob: bool = False) -> str:
        view = self._view
        is_vertical = view.orientation is Orientation.VERTICAL
        shown = sum(size for pane, size in zip(view.panes, view.sizes) if pane.is_visible) or 1
        disabled = "" if self.is_enabled else ' aria-disabled="true"'
        # a separator's orientation is its line's: across the splitter
        border_orientation = "horizontal" if is_vertical else "vertical"
        pane_class = (
            "min-h-0 overflow-auto has-[>[hidden]]:hidden flex-(--share)"
            if is_vertical
            # side by side, each wide enough to read its text (`page.py` reads it too)
            else "min-w-0 has-[>[hidden]]:hidden @2xl:min-w-48 @2xl:flex-(--share)"
        )
        cells: list[str] = []
        before = 0  # the length of the panes shown before the border, in percent
        for index, (pane, size) in enumerate(zip(view.panes, view.sizes)):
            if not isinstance(pane.renderer, WebRenderer):
                continue
            pane_id = f"{self.widget_id}-pane-{index}"
            if index > 0:
                cells.append(
                    f'<div class="cui-splitter-border" role="separator"'
                    f' aria-orientation="{border_orientation}" aria-controls="{pane_id}"'
                    f' aria-label="{html.escape(view.border_text)}" aria-valuemin="0"'
                    f' aria-valuemax="100" aria-valuenow="{round(100 * before / shown)}"'
                    f' tabindex="{0 if self.is_enabled else -1}"{disabled}></div>'
                )
            if pane.is_visible:
                before += size
            cells.append(
                f'<div id="{pane_id}" data-pane class="{pane_class}"'
                f' style="--share: {size} 1 0%">{pane.renderer.to_html()}</div>'
            )
        if is_vertical:
            return (
                f"<div {self._root_attributes(oob=oob)} data-splitter>"
                f'<div class="flex h-128 flex-col">{"".join(cells)}</div></div>'
            )
        # the splitter's own width is queried from its root, the panes laid out inside it
        return (
            f'<div {self._root_attributes(oob=oob)} class="@container" data-splitter>'
            '<div class="flex flex-col gap-6 @2xl:flex-row @2xl:gap-0">'
            f"{''.join(cells)}</div></div>"
        )

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
    `toggle`; like every control, it is never swapped back after one, only when the
    server changes it. Its views swap on their own, shown or not. Disabled, its title
    can't be clicked or focused, as a disabled Qt button can't be pressed.
    """

    _role = "expander"

    def __init__(self, view: ExpanderView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {"title": self._mark_dirty, "is_expanded": self._mark_dirty}
        )

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> str:
        is_open = " open" if self._view.is_expanded else ""
        summary_attributes = "" if self.is_enabled else ' tabindex="-1" aria-disabled="true"'
        summary_classes = "" if self.is_enabled else " pointer-events-none opacity-50"
        content = "".join(
            view.renderer.to_html()
            for view in self._view.children_views
            if isinstance(view.renderer, WebRenderer)
        )
        # `toggle` also fires when the server swaps it in open: posting the state the
        # server already has, which `dispatch` ignores
        return (
            f"<details {self._root_attributes(oob=oob)}{is_open}"
            ' class="collapse collapse-arrow rounded-box border border-base-300 bg-base-100"'
            f' hx-post="/widget/{self.widget_id}" hx-trigger="toggle"'
            ' hx-vals="js:{event: event.type, open: event.target.open}" hx-swap="none">'
            f'<summary class="collapse-title font-semibold{summary_classes}"{summary_attributes}>'
            f"{html.escape(self._view.title)}</summary>"
            f'<div class="collapse-content flex flex-col gap-6">{content}</div></details>'
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "toggle":
            super().dispatch(event, form)
        is_expanded = form.get("open") == "true"
        if is_expanded == self._view.is_expanded:
            return
        with self.stop_refresh():
            self._view.is_expanded = is_expanded
        self._view.toggled.emit(is_expanded)


class WebTreeRenderer(WebRenderer[TreeView]):
    """Nested lists of the nodes, each a button selecting it after an arrow toggling it.

    A click or Enter on a node selects it (`aria-current`), on its arrow expands or
    collapses it (`aria-expanded`); a collapsed node's children are left out. Either way
    the tree is swapped back, each button keeping its own id, its node's position depth
    first, so htmx gives the focus back to the button that had it, as a table's rows do.
    A button posts its node's path: a node a stale page still shows swaps the tree back.
    """

    _role = "tree"

    def __init__(self, view: TreeView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "nodes": self._mark_dirty,
                "expanded": self._mark_dirty,
                "selected": self._mark_dirty,
                "done_text": self._mark_dirty,
                "warning_text": self._mark_dirty,
                "error_text": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> str:
        positions = {
            path: position for position, (path, _node) in enumerate(walk_tree(self._view.nodes))
        }
        # clipped to a pane too narrow for it, the focus rings at its edges left whole
        return (
            f"<ul {self._root_attributes(oob=oob)}"
            ' class="flex flex-col gap-0.5 overflow-clip [overflow-clip-margin:4px]">'
            f"{self._nodes_html(self._view.nodes, (), positions)}</ul>"
        )

    def _nodes_html(
        self, nodes: Iterable[TreeNode], parent: TreePath, positions: Mapping[TreePath, int]
    ) -> str:
        disabled = "" if self.is_enabled else " disabled"
        items: list[str] = []
        for node in nodes:
            path = (*parent, node.key)
            position, label = positions[path], html.escape(node.label)
            children = ""
            if len(node.children) == 0:
                toggle = '<span class="size-6 shrink-0" aria-hidden="true"></span>'
            else:
                is_expanded = path in self._view.expanded
                turn = "" if is_expanded else " -rotate-90"
                # named by its node, which `aria-expanded` says it expands or collapses
                toggle = (
                    f'<button id="{self.widget_id}-toggle-{position}" type="button"'
                    ' class="btn btn-ghost btn-xs btn-square"'
                    f' aria-expanded="{str(is_expanded).lower()}" aria-label="{label}"'
                    f"{self._post('toggle', path, expanded=not is_expanded)}{disabled}>"
                    f"{_icon('chevron', 'size-3' + turn)}</button>"
                )
                if is_expanded:
                    children = (
                        '<ul class="ms-3 flex flex-col gap-0.5 border-s border-base-300 ps-1">'
                        f"{self._nodes_html(node.children, path, positions)}</ul>"
                    )
            is_selected = path == self._view.selected
            selected = ' aria-current="true"' if is_selected else ""
            variant = "btn-soft btn-primary" if is_selected else "btn-ghost"
            mark_id = f"{self.widget_id}-mark-{position}"
            described = "" if node.mark is None else f' aria-describedby="{mark_id}"'
            items.append(
                f'<li><div class="flex items-center gap-1">{toggle}'
                f'<button id="{self.widget_id}-node-{position}" type="button"'
                f' class="btn btn-sm {variant} min-w-0 shrink justify-start font-normal"'
                f"{selected}{described}"
                f"{self._post('select', path)}{disabled}>{self._node_content(node, mark_id)}"
                f"</button></div>{children}</li>"
            )
        return "".join(items)

    def _node_content(self, node: TreeNode, mark_id: str) -> str:
        """Show a node's icon, its label as bold or underlined as it says, then its mark.

        The mark's icon is hidden from screen readers, which read its name (at `mark_id`)
        as the button's description, after the label naming it.
        """
        # a label too long for the pane cut short, the icon and the mark kept whole
        styles = [
            style
            for style, is_on in (("font-bold", node.is_bold), ("underline", node.is_underlined))
            if is_on
        ]
        label = f'<span class="{" ".join(["truncate", *styles])}">{html.escape(node.label)}</span>'
        mark = ""
        if node.mark is not None:
            icon, color = _MARK_ICONS[node.mark]
            text = html.escape(self._view.mark_text(node.mark))
            mark = (
                f'<span class="shrink-0 {color}">{_icon(icon)}</span>'
                f'<span id="{mark_id}" hidden>{text}</span>'
            )
        return f"{_file_icon(node.icon)}{label}{mark}"

    def _post(self, event: str, path: TreePath, *, expanded: bool = False) -> str:
        """Attributes posting an event of the node at `path`, without swapping it back."""
        values = {"event": event, "path": json.dumps(list(path))}
        if event == "toggle":
            values["expanded"] = str(expanded).lower()
        return (
            f" hx-post=\"/widget/{self.widget_id}\" hx-vals='{html.escape(json.dumps(values))}'"
            ' hx-swap="none"'
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a disabled tree can't be clicked: a post saying otherwise is refused
        if not self.is_enabled or event not in ("select", "toggle"):
            super().dispatch(event, form)
        path = self._posted_path(form.get("path", ""))
        if path is None or (event == "toggle" and len(self._view.node(path).children) == 0):
            # a node a stale page still shows: swap the tree back as it now is
            self._mark_dirty(self._view, self.widget_id, self._view.nodes)
            return
        if event == "select":
            if path != self._view.selected:
                self._view.selected = path
                self._view.selection_changed.emit(path)
            return
        is_expanded = form.get("expanded") == "true"
        if is_expanded != (path in self._view.expanded):
            self._view.expanded = self._view.expanded_with(path, is_expanded=is_expanded)
            self._view.toggled.emit(path, is_expanded)

    def _posted_path(self, posted: str) -> TreePath | None:
        """Get the path a button posted, if a node of the tree is there."""
        try:
            keys = json.loads(posted)
        except ValueError:
            return None
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            return None
        path = tuple(keys)
        return path if path in {path for path, _node in walk_tree(self._view.nodes)} else None


class WebSidebarRenderer(WebRenderer[SidebarView]):
    """An `<aside>`: its title, then its views in a column, left of the pages.

    The main renderer wraps it in a daisyUI drawer (`drawer_html`): a column beside the
    pages on a wide screen, and on a phone a drawer over them, closed by a click beside
    it. A button in the header (`toggle_html`; see `page.py`) retracts and expands the
    column, which the browser does before posting it (`toggle`), like every control
    never swapped back after one; on a phone, it shows and hides the drawer instead.
    The button isn't in the aside's fragment: a swap of the aside brings it along.
    """

    _role = "sidebar"

    def __init__(self, view: SidebarView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(("title", "toggle_text", "is_expanded"), self._mark_dirty)
        )

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    @property
    def drawer_id(self) -> str:
        """The drawer's checkbox, checked while the drawer shows on a phone."""
        return f"{self.widget_id}-drawer"

    def to_html(self, *, oob: bool = False) -> str:
        title = html.escape(self._view.title)
        heading = f'<h2 class="font-semibold text-primary">{title}</h2>' if title else ""
        content = "".join(
            view.renderer.to_html()
            for view in self._view.children_views
            if isinstance(view.renderer, WebRenderer)
        )
        name = title or html.escape(self._view.toggle_text)
        retracted = "" if self._view.is_expanded else " data-retracted"
        # bottom padding keeps the last view clear of the fixed status bar
        aside = (
            f'<aside {self._root_attributes(oob=oob)}{retracted} aria-label="{name}"'
            ' class="cui-sidebar flex min-h-full w-80 max-w-[85vw] flex-col gap-6 border-r'
            f' border-base-300 bg-base-100 p-4 pb-20">{heading}{content}</aside>'
        )
        return aside + self.toggle_html(oob=True) if oob else aside

    def toggle_html(self, *, oob: bool = False) -> str:
        """Get the header's button retracting and expanding the sidebar.

        `aria-expanded` tells whether the column shows; the page's script keeps it
        telling whether the drawer shows on a phone.
        """
        swap = ' hx-swap-oob="true"' if oob else ""
        expanded = "true" if self._view.is_expanded else "false"
        text = html.escape(self._view.toggle_text)
        # posted by the page's script on a wide screen only, once the column has changed
        is_expanded = f'!document.getElementById("{self.widget_id}").hasAttribute("data-retracted")'
        return (
            f'<button id="{self.widget_id}-toggle" type="button"{swap}'
            ' class="btn btn-ghost btn-square btn-sm"'
            f' data-sidebar-toggle="{self.drawer_id}" aria-controls="{self.widget_id}"'
            f' aria-expanded="{expanded}" aria-label="{text}" title="{text}"'
            f' hx-post="/widget/{self.widget_id}" hx-trigger="sidebar-toggle"'
            f' hx-vals=\'js:{{event: "toggle", expanded: {is_expanded}}}\' hx-swap="none">'
            f"{_icon('sidebar', 'size-5')}</button>"
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "toggle":
            super().dispatch(event, form)
        is_expanded = form.get("expanded") == "true"
        if is_expanded == self._view.is_expanded:
            return
        with self.stop_refresh():
            self._view.is_expanded = is_expanded
        self._view.toggled.emit(is_expanded)

    def drawer_html(self, content: str) -> str:
        """Lay out `content`, the pages' column, beside the sidebar, in a drawer on a phone."""
        return (
            '<div class="cui-drawer drawer lg:drawer-open">'
            f'<input id="{self.drawer_id}" type="checkbox" class="drawer-toggle"'
            ' tabindex="-1" aria-hidden="true">'
            f'<div class="drawer-content">{content}</div>'
            '<div class="drawer-side z-30">'
            f'<label for="{self.drawer_id}" class="drawer-overlay"'
            f' aria-label="{html.escape(self._view.toggle_text)}"></label>'
            f"{self.to_html()}</div></div>"
        )


class WebListRenderer(WebRenderer["ListView[Any]"]):
    """The records' views one above the other, each in an item of its own.

    As the records change, the response swaps only the items that changed: an item gone
    is deleted and a new one goes in after its neighbour, so the items kept, the one the
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

    def render(self) -> None:
        super().render()
        self._render_items(self._view.item_views)

    def _render_items(self, views: list[View]) -> None:
        """Render the views built since the list was, into the session, and adopt them all."""
        built_since = [view for view in views if view.renderer is None]
        in_session = (
            contextlib.nullcontext() if self._target is None else rendering_into(self._target)
        )
        with in_session:
            for view in built_since:
                view.render(RendererType.WEB)
        self._adopt(views)

    def _item_id(self, view: View) -> str:
        return f"{self.widget_id}-item-{id(view)}"

    def _item_html(self, view: View) -> str:
        content = view.renderer.to_html() if isinstance(view.renderer, WebRenderer) else ""
        return f'<div id="{self._item_id(view)}">{content}</div>'

    def to_html(self, *, oob: bool = False) -> str:
        views = self._view.item_views
        sent, self._sent = self._sent, list(views)
        is_whole, self._is_whole = self._is_whole, False
        if oob and not is_whole and sent is not None:
            kept = [view for view in sent if view in views]
            if kept == [view for view in views if view in sent]:
                return self._changes_html(sent, views)
        items = "".join(self._item_html(view) for view in views)
        # `cui-list`: its expanders join in one box (see `css/app.css`)
        return (
            f'<div {self._root_attributes(oob=oob)} class="cui-list flex flex-col gap-3">'
            f"{items}</div>"
        )

    def _changes_html(self, sent: list[View], views: list[View]) -> str:
        """Delete the items gone and put each new one after its neighbour, in order."""
        fragments = [
            f'<div id="{self._item_id(view)}" hx-swap-oob="delete"></div>'
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
            fragments.append(f'<div hx-swap-oob="{place}">{self._item_html(view)}</div>')
        return "".join(fragments)

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
            for child in renderers:
                if not isinstance(child, WebRenderer) or child._rendered_object is None:  # noqa: SLF001
                    continue
                if child in self.children:
                    self.children.remove(child)
                if self._target is not None:
                    self._target.renderers.pop(child.widget_id, None)
                    self._target.pending.pop(child.widget_id, None)

    def _mark_dirty(self, view: ListView[Any], rendered_object: str, value: Any) -> None:
        self._is_whole = True
        super()._mark_dirty(view, rendered_object, value)


class WebTabPageRenderer(WebRenderer[TabPage]):
    """A tab's views in a column, which its tabs put in a panel under its tab.

    Its title, visibility and enabled state are its tab's too: a change swaps its tabs.
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

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> str:
        content = "".join(
            view.renderer.to_html()
            for view in self._view.children_views
            if isinstance(view.renderer, WebRenderer)
        )
        return f'<div {self._root_attributes(oob=oob)} class="flex flex-col gap-6">{content}</div>'

    def _refresh_tab(self, view: TabPage, rendered_object: str, value: Any) -> None:
        self._refresh_enabled(view, rendered_object, value)
        dirty = _DIRTY.get()
        if dirty is not None and self.parent is not None:
            dirty[self.parent.widget_id] = self.parent


class WebTabsRenderer(WebRenderer[TabView]):
    """A row of tabs (an ARIA tab list), then a panel per tab, only the current one shown.

    The browser shows the tab picked, by a click or the arrow keys (see `page.py`),
    before posting it (`select`): like every control, the tabs are never swapped back
    after a pick, only when the server changes them.
    """

    _role = "tabs"

    def __init__(self, view: TabView) -> None:
        super().__init__(view)
        self._refresh_dispatcher["current_index"] = self._mark_dirty

    def render(self) -> None:
        super().render()
        self._adopt(self._view.tabs)

    def to_html(self, *, oob: bool = False) -> str:
        current = self._view.current_index
        tabs: list[str] = []
        panels: list[str] = []
        for index, tab in enumerate(self._view.tabs):
            if not isinstance(tab.renderer, WebRenderer):
                continue
            tab_id, panel_id = f"{self.widget_id}-tab-{index}", f"{self.widget_id}-panel-{index}"
            is_current = index == current
            active = " tab-active" if is_current else ""
            hidden = "" if tab.is_visible else " hidden"
            disabled = "" if tab.is_enabled and self.is_enabled else " disabled"
            # only the current tab in the tab order: the arrow keys move between them
            tabs.append(
                f'<button type="button" role="tab" id="{tab_id}" aria-controls="{panel_id}"'
                f' aria-selected="{str(is_current).lower()}" tabindex="{0 if is_current else -1}"'
                f' class="tab{active}" data-tab hx-post="/widget/{self.widget_id}"'
                f""" hx-vals='{{"event": "select", "index": "{index}"}}' hx-swap='none'"""
                f"{hidden}{disabled}>{html.escape(tab.title)}</button>"
            )
            panels.append(
                f'<div role="tabpanel" id="{panel_id}" aria-labelledby="{tab_id}"'
                f"{'' if is_current else ' hidden'}>{tab.renderer.to_html()}</div>"
            )
        return (
            f'<div {self._root_attributes(oob=oob)} class="flex flex-col gap-4">'
            f'<div role="tablist" class="tabs tabs-border">{"".join(tabs)}</div>'
            f"{''.join(panels)}</div>"
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "select":
            super().dispatch(event, form)
        try:
            index = int(form.get("index", ""))
        except ValueError:
            return
        if not 0 <= index < len(self._view.tabs) or index == self._view.current_index:
            return
        with self.stop_refresh():
            self._view.current_index = index
        self._view.current_changed.emit(index)


class WebGridRenderer(WebRenderer[GridView]):
    """Views in a grid's cells: equally wide columns, rows as tall as their views.

    The columns and each view's cell are variables rather than a class per count; a cell
    placed rather than flowed stays where it is when an earlier one hides. A grid
    narrower than 42rem stacks its views instead, in one column, row by row: only the
    wide grid uses the variables.
    """

    _role = "grid"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> str:
        cells = "".join(
            '<div class="min-w-0 has-[>[hidden]]:hidden @2xl:[grid-area:var(--area)]"'
            f' style="--area: {row + 1} / {column + 1} / span {row_span} / span {column_span}">'
            f"{view.renderer.to_html()}</div>"
            for view, (row, column, row_span, column_span) in self._view.positioned_views
            if isinstance(view.renderer, WebRenderer)
        )
        columns = f"repeat({self._view.column_count}, minmax(0, 1fr))"
        # the grid's own width is queried from its root, the views laid out inside it
        return (
            f'<div {self._root_attributes(oob=oob)} class="@container">'
            '<div class="grid grid-cols-1 items-start gap-6 @2xl:grid-cols-(--columns)"'
            f' style="--columns: {columns}">{cells}</div></div>'
        )


#: the main column's width, following the shown page's `PageView.width`: switching pages
#: only swaps the router, so CSS picks the width from the page neither hidden nor in a
#: hidden slot
_MAIN_WIDTHS = (
    "max-w-3xl"
    " has-[[data-width=wide]:not([hidden],[hidden]_*)]:max-w-6xl"
    " has-[[data-width=full]:not([hidden],[hidden]_*)]:max-w-none"
)


def page_path(route: str) -> str:
    """Get the address of the page on `route` (routes are made to fit in one)."""
    return f"/{route}"


class WebRouterRenderer(WebRenderer[Router]):
    """The pages, only the current one shown, and the toolbar of their links.

    Each page sits in a slot of its own, hidden unless current, which leaves the page's
    own `is_visible` to the page. The toolbar has no fragment of its own: the main
    renderer puts it in the header, and each link swaps on its own.
    """

    _role = "router"

    def __init__(self, view: Router) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"current_route": self._mark_dirty})

    def render(self) -> None:
        super().render()
        # not the toolbar: apart from the pages, like Qt's, it still switches them
        self._adopt(self._view.pages)
        # the children are rendered first: make each page's action a link to it
        for page in self._view.pages:
            if isinstance(page.action.renderer, WebActionRenderer):
                page.action.renderer.placement = Placement.PAGE
                page.action.renderer.href = page_path(page.route)

    def to_html(self, *, oob: bool = False) -> str:
        slots: list[str] = []
        for page in self._view.pages:
            if not isinstance(page.renderer, WebRenderer):
                continue
            hidden = "" if page.route == self._view.current_route else " hidden"
            slots.append(
                f'<div data-route="{html.escape(page.route)}"{hidden}>'
                f"{page.renderer.to_html()}</div>"
            )
        return f"<div {self._root_attributes(oob=oob)}>{''.join(slots)}</div>"

    def toolbar_html(self) -> str:
        links = "".join(
            page.action.renderer.to_html()
            for page in self._view.pages
            if isinstance(page.action.renderer, WebActionRenderer)
        )
        # a row of its own under the brand on a narrow screen, next to it on a wider one
        return (
            '<nav aria-label="Pages" class="tabs tabs-box tabs-sm order-last w-full'
            f' flex-nowrap overflow-x-auto sm:order-none sm:w-auto">{links}</nav>'
        )


#: first segments of the backend's own addresses, which no page's address can take
RESERVED_ROUTES: Final = frozenset({"icon", "jobs", "state", "static", "widget"})


def check_routes(main_view: MainView) -> None:
    """Raise `ValueError` if a page of the main view's router has an address the backend uses."""
    router = next((view for view in main_view.children_views if isinstance(view, Router)), None)
    reserved = sorted(
        page.route for page in (router.pages if router else []) if page.route in RESERVED_ROUTES
    )
    if len(reserved) > 0:
        msg = f"The web backend uses the address of the routes {reserved}: rename them."
        raise ValueError(msg)


def _theme_option(choice: str, text: str) -> str:
    # `setTheme` in `page.py`; the blur closes the dropdown
    return (
        f'<li><button type="button" class="theme-option" data-theme-option="{choice}"'
        f""" onclick="setTheme('{choice}'); document.activeElement.blur()">{text}</button></li>"""
    )


#: the header's Theme menu: Light, Dark, or System (the browser's preference). Its button
#: shows the theme in use, the sun or the moon, however it was chosen
_THEME_MENU: Final = (
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
    f"{_theme_option('composeui', 'Light')}{_theme_option('composeui-dark', 'Dark')}"
    f"{_theme_option('system', 'System')}</ul></div>"
)


class WebMainRenderer(MainRenderer[MainView, str]):
    """Renders the whole page; never swapped itself, so its attributes are no-ops."""

    def __init__(self, view: MainView) -> None:
        super().__init__(view)
        #: set by `MainView.close()` (the Exit action); the route then ends the session
        self.is_closed = False
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

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        call_in_session(self._target, callback)

    def page_html(self) -> str:
        menus: list[str] = []
        toolbars: list[str] = []
        content: list[str] = []
        status_bar = ""
        toolbar = ""
        sidebar: WebSidebarRenderer | None = None
        for child_view in self._view.children_views:
            if not isinstance(child_view.renderer, WebRenderer):
                continue
            if isinstance(child_view, DialogView):
                continue  # see `_dialogs_html`
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
        # bottom padding keeps the last row clear of the fixed status bar
        main = (
            f'<main class="mx-auto {_MAIN_WIDTHS} px-4 pt-8 pb-20">'
            '<div class="card border border-base-300 bg-base-100 shadow-md">'
            '<div class="card-body gap-6 p-6">'
            f"{''.join(content)}"
            "</div></div></main>"
        )
        return get_page(
            self._view.title,
            # sticky: the menus stay at hand however long the form is
            f'<header class="navbar sticky top-0 z-20 min-h-14{wrap} gap-3 border-b'
            " border-base-300"
            ' bg-base-100 px-4">'
            f"{sidebar.toggle_html() if sidebar else ''}{self.brand_html()}{toolbar}"
            '<nav class="ml-auto flex items-center gap-1">'
            f"{''.join(toolbars)}{''.join(menus)}</nav>"
            f"{_THEME_MENU}"
            "</header>"
            f"{sidebar.drawer_html(main) if sidebar else main}"
            f"{status_bar}{self._dialogs_html()}",
            self._view.language,
            jobs_running=self._view.jobs.is_running,
        )

    def _dialogs_html(self) -> str:
        """Render every dialog of the tree, outside the pages hiding their content."""
        dialogs: list[str] = []
        views: list[View] = list(self._view.children_views)
        while len(views) > 0:
            view = views.pop(0)
            views.extend(view.children_views)
            if isinstance(view, DialogView) and isinstance(view.renderer, WebDialogRenderer):
                dialogs.append(view.renderer.to_html())
        return "".join(dialogs)

    def brand_html(self, *, oob: bool = False) -> str:
        """Show the app's title after a badge of its initial, standing in for an app icon."""
        title = self._view.title
        initial = html.escape(title.strip()[:1].upper())
        swap = ' hx-swap-oob="true"' if oob else ""
        return (
            # on a narrow screen, the title gives way to the header's buttons rather than
            # pushing them to a row of their own
            f'<div id="cui-brand"{swap} class="flex min-w-0 flex-1 basis-0 items-center gap-2'
            ' sm:flex-none sm:basis-auto">'
            '<span aria-hidden="true" class="grid size-8 shrink-0 place-items-center'
            ' rounded-field bg-primary text-sm font-bold text-primary-content">'
            f"{initial}</span>"
            f'<h1 class="truncate text-lg font-semibold">{html.escape(title)}</h1></div>'
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
    "button": WebButtonRenderer,
    "chart": WebChartRenderer,
    "checkbox": WebCheckBoxRenderer,
    "combobox": WebComboboxRenderer,
    "date_input": WebDateInputRenderer,
    "dialog": WebDialogRenderer,
    "expander": WebExpanderRenderer,
    "float_input": WebFloatInputRenderer,
    "int_input": WebIntInputRenderer,
    "form": WebFormRenderer,
    "form_dialog": WebFormDialogRenderer,
    "form_label": WebFormLabelRenderer,
    "grid": WebGridRenderer,
    "group_form": WebGroupFormRenderer,
    "horizontal": WebHorizontalRenderer,
    "input": WebInputRenderer,
    "label": WebLabelRenderer,
    "list": WebListRenderer,
    "log": WebLogRenderer,
    "main": WebMainRenderer,
    "markdown": WebMarkdownRenderer,
    "menu": WebMenuRenderer,
    "metric": WebMetricRenderer,
    "page": WebPageRenderer,
    "progress_bar": WebProgressBarRenderer,
    "slider": WebSliderRenderer,
    "radio_group": WebRadioGroupRenderer,
    "router": WebRouterRenderer,
    "separator": WebSeparatorRenderer,
    "sidebar": WebSidebarRenderer,
    "splitter": WebSplitterRenderer,
    "status_bar": WebStatusBarRenderer,
    "table": WebTableRenderer,
    "tab_page": WebTabPageRenderer,
    "tabs": WebTabsRenderer,
    "toolbar": WebToolBarRenderer,
    "tree": WebTreeRenderer,
    "vertical": WebVerticalRenderer,
}
