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
import json
import math
import re
import threading
from abc import abstractmethod
from collections import deque
from contextvars import ContextVar
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Final, Generic, TypeVar

import attrs
from markdown_it import MarkdownIt
from markupsafe import Markup, escape
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
    CHECKED_TEXTS,
    PLAIN_CELL,
    SEARCH_DELAY_MS,
    ActionView,
    Align,
    ButtonVariant,
    CellKind,
    ChartKind,
    ChartView,
    DialogKind,
    DialogView,
    ExitAppAction,
    ExpanderView,
    FormLabelRowView,
    FormRowView,
    FormView,
    GridView,
    GroupFormView,
    HorizontalView,
    ListView,
    LogType,
    MainView,
    MapPoint,
    MapView,
    Menu,
    MetricView,
    NewAction,
    NodeMark,
    OpenFileAction,
    Orientation,
    PageView,
    PageWidth,
    PickFileAction,
    ProgressBarView,
    Router,
    SaveAction,
    SaveAsAction,
    SelectionMode,
    SeparatorAction,
    SidebarView,
    SliderMixin,
    SourceTableByPosition,
    SplitterView,
    StatusBar,
    TabPage,
    TabView,
    ToolBar,
    TreeView,
    TypedFormDialogView,
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
from composeui.webcore.page import SAVE_FORM_ID, get_page, jobs_poller, reload_poller

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Iterator, Mapping
    from pathlib import Path

    from composeui.core.signal import Signal, SignalNoArgs
    from composeui.core.view import (
        CellStyle,
        CellWidget,
        HeaderGroup,
        ReferenceLine,
        Series,
        TreeNode,
        TreePath,
    )

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
#: the rows of a large table the page draws at once, around those scrolled to
SOURCE_TABLE_WINDOW_ROWS = 100
#: the rows of a large table that the scroll bar's height can stand for at most, 2.25rem
#: each: past them, a scroll position maps to a row by its ratio, as browsers cap an
#: element's height (about 33M pixels in Chrome, 17M in Firefox)
SOURCE_TABLE_SCROLLED_ROWS = 400_000
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


def render_dirty(dirty: Mapping[str, WebRenderer[Any]]) -> Markup:
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
    return Markup("").join(
        fragment for widget_id, fragment in fragments.items() if widget_id not in nested
    )


def handle_event(renderer: WebRenderer[Any], event: str, form: Mapping[str, str]) -> Markup:
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
    def to_html(self, *, oob: bool = False) -> Markup:
        """Render the view's fragment; `oob` marks it as an htmx out-of-band swap."""

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        """Apply a browser `event` (with its submitted `form` fields) to the view."""
        raise UnsupportedEventError(self, event)

    def _root_attributes(self, *, oob: bool) -> Markup:
        """Get the attributes of the fragment's root tag, kept even when hidden for later swaps."""
        attributes = [Markup('id="{}"').format(self.widget_id)]
        if not self._view.is_visible:
            attributes.append(Markup("hidden"))
        if oob:
            attributes.append(Markup('hx-swap-oob="true"'))
        return Markup(" ").join(attributes)

    def _row_attributes(self) -> Markup:
        """ARIA links from a form row's field to the row's log and label.

        The field is described by the row's help, if any, and its log, read out with the
        field, and is `aria-invalid` while the log shows an error (the page script keeps
        that in step when only the log is swapped, see `page.js`). A field a `<label for>`
        can't name, a radio group or a checkbox, is labelled by the row's label instead.
        Nothing outside a row.
        """
        attributes: list[Markup] = []
        log, label = self._row_renderer("log"), self._row_renderer("label")
        if log is not None:
            described_by = (
                f"{label.help_id} {log.widget_id}"
                if isinstance(label, WebFormLabelRenderer) and label.has_help()
                else log.widget_id
            )
            attributes.append(Markup('aria-describedby="{}"').format(described_by))
            if isinstance(self._view, FormRowView) and self._view.is_invalid:
                attributes.append(Markup('aria-invalid="true"'))
        if not self.is_labelable and isinstance(label, WebFormLabelRenderer):
            attributes.append(Markup('aria-labelledby="{}"').format(label.text_id))
        return Markup("").join(Markup(" {}").format(attribute) for attribute in attributes)

    def _row_renderer(self, part: str) -> WebRenderer[Any] | None:
        """Get another renderer of the view's row, e.g. its "log", if it has one."""
        container = self._view.renderer  # type: ignore[attr-defined]
        if not isinstance(container, RendererContainer):
            return None
        try:
            renderer = container.get_renderer(part)
        except KeyError:
            return None
        assert isinstance(renderer, WebRenderer)  # a row's part, rendered by this backend
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


class TextFieldViewLike(ViewLike, Protocol):
    placeholder: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


TTextField = TypeVar("TTextField", bound=TextFieldViewLike)


class _WebTextFieldRenderer(WebRenderer[TTextField]):
    """A text field posting debounced edits (`input`) and committed edits (`change`)."""

    def to_html(self, *, oob: bool = False) -> Markup:
        # `hx-swap="none"`: the field being typed in is never swapped back (it would
        # reset the caret); everything else arrives out of band. `queue all` keeps a
        # `change` from being dropped behind an in-flight debounced edit.
        disabled = "" if self.is_enabled else " disabled"
        return Markup(
            "<input {root_attributes}{row_attributes}"
            ' class="input w-full" type="text"'
            ' name="value" value="{text}"'
            ' placeholder="{placeholder}"{extra_attributes}'
            ' hx-post="/widget/{widget_id}"'
            ' hx-trigger="input changed delay:300ms, change"'
            ' data-post-event hx-swap="none" hx-sync="this:queue all"'
            # the browser must not refill the field on reload: the server's value wins
            ' autocomplete="off"'
            "{disabled}>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            text=self._text(),
            placeholder=self._view.placeholder,
            extra_attributes=self._extra_attributes(),
            widget_id=self.widget_id,
            disabled=disabled,
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
        """Get the text to show in the field, from the view's state."""

    @abstractmethod
    def _posted_text(self) -> str:
        """Get the text the browser last posted (or was last shown)."""

    @abstractmethod
    def _apply_text(self, text: str) -> None:
        """Store the browser's `text` into the view, without refreshing the field."""

    def _extra_attributes(self) -> Markup:
        return Markup()


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
        """Tell whether `text` is an acceptable field value ("" meaning no value)."""
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

    def shown_text(self, value: float | None, decimals: int | None) -> str: ...


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

    def _text(self) -> str:
        return self._view.shown_text(self._view.value, self._view.decimals)

    def _extra_attributes(self) -> Markup:
        return Markup(' inputmode="decimal" pattern="{}"').format(_DECIMAL_PATTERN)


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

    def _extra_attributes(self) -> Markup:
        return Markup(' inputmode="numeric" pattern="{}"').format(_INTEGER_PATTERN)


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
    `page.js`); the date picked posts as its change (`pick`), in ISO 8601. Like the number
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

    def to_html(self, *, oob: bool = False) -> Markup:
        view = self._view
        disabled = "" if self.is_enabled else " disabled"
        pick = view.pick_text
        limits = Markup("").join(
            Markup(' {}="{}"').format(name, limit.isoformat())
            for name, limit in (("min", view.minimum), ("max", view.maximum))
            if limit is not None
        )
        picked = "" if view.value is None else view.value.isoformat()
        calendar_id = f"{self.widget_id}-calendar"
        return (
            # daisyUI's field around both, its colors, focus ring and invalid border theirs
            Markup(
                '<div {root_attributes} class="input relative w-full pe-1">'
                '<input id="{widget_id}-field"{row_attributes}'
                ' class="min-w-0 grow" type="text" name="value"'
                ' value="{shown_text}"'
                ' placeholder="{date_hint}"'
                ' hx-post="/widget/{widget_id}" hx-trigger="input changed delay:300ms, change"'
                ' data-post-event hx-swap="none" hx-sync="this:queue all"'
                ' autocomplete="off"{disabled}>'
                '<button id="{widget_id}-pick" type="button"'
                ' class="btn btn-ghost btn-sm btn-square"'
                ' aria-label="{pick}" title="{pick}" popovertarget="{calendar_id}"'
                ' style="anchor-name: --{widget_id}"{disabled}>'
                "{calendar_icon}</button>"
                # in the top layer, under the button: Escape or a click beside it closes it
                '<div id="{calendar_id}" popover data-date-button="{widget_id}-pick"'
                ' class="dropdown dropdown-end rounded-box bg-base-100 shadow-lg"'
                ' style="position-anchor: --{widget_id}">'
                '<calendar-date class="cally" value="{picked}"{limits} data-date-calendar'
                ' hx-post="/widget/{widget_id}" hx-trigger="change"'
                """ hx-vals='{{"event": "pick"}}' data-post-picked hx-swap="none">"""
                '<span slot="previous" aria-label="{previous_month_text}">'
                "{chevron_icon}</span>"
                '<span slot="next" aria-label="{next_month_text}">'
                "{chevron_icon2}</span>"
                "<calendar-month></calendar-month></calendar-date></div></div>"
            ).format(
                root_attributes=self._root_attributes(oob=oob),
                widget_id=self.widget_id,
                row_attributes=self._row_attributes(),
                shown_text=view.shown_text(view.value),
                date_hint=date_hint(view.placeholder, view.date_format),
                disabled=disabled,
                pick=pick,
                calendar_id=calendar_id,
                calendar_icon=_icon("calendar"),
                picked=picked,
                limits=limits,
                previous_month_text=view.previous_month_text,
                chevron_icon=_icon("chevron", "size-4 rotate-90"),
                next_month_text=view.next_month_text,
                chevron_icon2=_icon("chevron", "size-4 -rotate-90"),
            )
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


def _file_types(extensions: dict[str, tuple[str, ...]]) -> list[str]:
    """Get the file types a picker offers, e.g. [".md", ".markdown"]; empty for any."""
    return list(dict.fromkeys(t.lower() for ts in extensions.values() for t in ts))


class FilePathInputViewLike(InputViewLike, Protocol):
    extensions: dict[str, tuple[str, ...]]
    has_reload: bool
    browse_text: str
    reload_text: str
    path_picked: Signal[Path]
    reload_clicked: SignalNoArgs


class WebFilePathInputRenderer(_WebTextFieldRenderer[FilePathInputViewLike]):
    """A text field typing a file's path, then a "…" button uploading one, and a reload button.

    The field posts as a text input's (see `_WebTextFieldRenderer`). The browser can't
    hand a page its files' paths: the button opens the browser's picker, a hidden file
    input beside it (see `page.js`) uploading the file picked (`/widget/{id}/file`), and
    the session keeps a copy (see `WebSession.pick_file`), whose path the field then
    shows. The root is a `<div>` holding them, so a row's label names the field with
    `aria-labelledby`.
    """

    _role = "file_path_input"
    is_labelable = False

    def __init__(self, view: FilePathInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("text", "placeholder", "extensions", "has_reload", "browse_text", "reload_text"),
                self._mark_dirty,
            )
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        view = self._view
        disabled = "" if self.is_enabled else " disabled"
        browse, reload = view.browse_text, view.reload_text
        types = ",".join(self.file_types)
        accept = Markup(' accept="{}"').format(types) if types else ""
        reload_button = (
            Markup(
                '<button id="{widget_id}-reload" type="button" class="btn btn-square"'
                ' aria-label="{reload}" title="{reload}" hx-post="/widget/{widget_id}"'
                """ hx-vals='{{"event": "reload"}}' hx-swap="none"{disabled}>"""
                "{reload_icon}</button>"
            ).format(
                widget_id=self.widget_id,
                reload=reload,
                disabled=disabled,
                reload_icon=_icon("reload"),
            )
            if view.has_reload
            else ""
        )
        return Markup(
            '<div {root_attributes} class="flex gap-1" data-file-path>'
            '<input id="{widget_id}-field"{row_attributes}'
            ' class="input w-full" type="text" name="value"'
            ' value="{text}" placeholder="{placeholder}"'
            ' hx-post="/widget/{widget_id}" hx-trigger="input changed delay:300ms, change"'
            ' data-post-event hx-swap="none" hx-sync="this:queue all"'
            ' autocomplete="off"{disabled}>'
            '<button id="{widget_id}-browse" type="button" class="btn btn-square"'
            ' aria-label="{browse}" title="{browse}" data-file-browse{disabled}>…</button>'
            # emptied once sent: picking the same file again is a change too
            '<input type="file" name="file"{accept} class="hidden" tabindex="-1"'
            ' aria-hidden="true" hx-post="/widget/{widget_id}/file"'
            ' hx-encoding="multipart/form-data" hx-trigger="change" hx-swap="none"'
            ' data-clear-after-post autocomplete="off"'
            "{disabled}>{reload_button}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            widget_id=self.widget_id,
            row_attributes=self._row_attributes(),
            text=self._text(),
            placeholder=view.placeholder,
            disabled=disabled,
            browse=browse,
            accept=accept,
            reload_button=reload_button,
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event != "reload":
            super().dispatch(event, form)
        elif not self.is_enabled or not self._view.has_reload:
            raise UnsupportedEventError(self, event)
        else:
            self._view.reload_clicked.emit()

    @property
    def file_types(self) -> list[str]:
        """Get the file types the picker offers, e.g. [".csv"]; empty for any."""
        return _file_types(self._view.extensions)

    def pick_file(self, path: Path) -> None:
        """Show the path of the file the picker uploaded, and hand it to `path_picked`.

        Raises `UnsupportedEventError` while the field is disabled.
        """
        if not self.is_enabled:
            raise UnsupportedEventError(self, "file")
        text = str(path)
        # swapped back: the field shows the path, though its picker sent the request
        self._view.text = text
        self._view.text_changed.emit(text)
        self._view.path_picked.emit(path)

    def _text(self) -> str:
        return self._view.text

    def _posted_text(self) -> str:
        return self._view.text

    def _apply_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text


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

    def to_html(self, *, oob: bool = False) -> Markup:
        checked = " checked" if self._view.is_checked else ""
        disabled = "" if self.is_enabled else " disabled"
        # an unchecked box posts no value at all: `checked` is told apart by its presence
        return Markup(
            '<div {root_attributes}{row_attributes} role="group"'
            ' class="flex">'
            '<label class="label cursor-pointer gap-2 text-base-content">'
            '<input type="checkbox" class="checkbox checkbox-sm checkbox-primary"'
            ' name="checked" value="on"{checked} hx-post="/widget/{widget_id}"'
            ' hx-trigger="change" hx-vals=\'{{"event": "change"}}\' hx-swap="none"'
            ' autocomplete="off"{disabled}>'
            "{text}</label></div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            checked=checked,
            widget_id=self.widget_id,
            disabled=disabled,
            text=self._view.text,
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

    def to_html(self, *, oob: bool = False) -> Markup:
        disabled = "" if self.is_enabled else " disabled"
        variant = _BUTTON_CLASSES[self._view.variant]
        # `self-start`: as wide as its text, not the page's whole column
        return Markup(
            '<button {root_attributes} type="button"'
            ' class="btn {variant} self-start"'
            """ hx-post="/widget/{widget_id}" hx-vals='{{"event": "click"}}'"""
            ' hx-swap="none"{disabled}>{text}</button>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            variant=variant,
            widget_id=self.widget_id,
            disabled=disabled,
            text=self._view.text,
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

    def to_html(self, *, oob: bool = False) -> Markup:
        value, maximum = self._view.value, self._view.maximum
        clamped = ProgressBarView.clamp(value, maximum)
        progress = (
            "" if maximum is None else Markup(' value="{}" max="{}"').format(clamped, maximum)
        )
        return Markup('<progress {} class="progress progress-primary w-full"{}></progress>').format(
            self._root_attributes(oob=oob), progress
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
    in step (see `page.js`). Beside the track rather than above the handle, and in a
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

    def to_html(self, *, oob: bool = False) -> Markup:
        minimum, step = self._view.minimum, self._view.step
        last = SliderMixin.last_position(minimum, self._view.maximum, step)
        position = SliderMixin.position(self._view.value, minimum, self._view.maximum, step)
        value = minimum + position * step
        top = minimum + last * step
        digits = max(len(str(minimum)), len(str(top)))
        disabled = "" if self.is_enabled else " disabled"
        input_id = f"{self.widget_id}-input"
        return Markup(
            '<div {root_attributes} class="cui-slider"'
            ' style="--slider-digits: {digits}">'
            '<input id="{input_id}"{row_attributes} type="range" data-slider'
            ' class="range range-primary" name="value"'
            ' min="{minimum}" max="{top}" step="{step}" value="{value}"'
            ' hx-post="/widget/{widget_id}" hx-trigger="input changed delay:150ms, change"'
            ' data-post-event hx-swap="none" hx-sync="this:queue all"'
            ' autocomplete="off"{disabled}>'
            # read out by the input itself, as its value
            '<output for="{input_id}" class="cui-slider-value" aria-hidden="true">{value}</output>'
            "</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            digits=digits,
            input_id=input_id,
            row_attributes=self._row_attributes(),
            minimum=minimum,
            top=top,
            step=step,
            value=value,
            widget_id=self.widget_id,
            disabled=disabled,
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


class MapViewLike(ViewLike, Protocol):
    title: str
    center: MapPoint | None
    zoom: float | None
    points: list[MapPoint]
    height: int
    tiles: bool
    user_agent: str
    clicked: Signal[float, float]
    viewport_changed: SignalNoArgs


class WebMapRenderer(WebRenderer[MapViewLike]):
    _role = "map"
    is_labelable = False

    def __init__(self, view: MapViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("title", "center", "zoom", "points", "height", "tiles", "user_agent"),
                self._mark_dirty,
            )
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        view = self._view
        center, span_x, span_y = MapView.point_bounds(view.points, view.center)
        spec = json.dumps(
            {
                "latitude": center.latitude,
                "longitude": center.longitude,
                "zoom": view.zoom,
                "span": [span_x, span_y],
                "points": [[p.longitude, p.latitude] for p in view.points],
                "tiles": view.tiles,
                "enabled": self.is_enabled,
            },
            allow_nan=False,
            separators=(",", ":"),
        )
        attribution = (
            Markup(
                '<a href="https://www.openstreetmap.org/copyright" rel="noreferrer">'
                "© OpenStreetMap contributors</a>"
            )
            if view.tiles
            else Markup()
        )
        return Markup(
            '<figure {root} class="flex w-full flex-col gap-2">'
            "<figcaption>{title}</figcaption>"
            '<div data-map="{spec}" data-widget="{widget}" role="region"'
            ' aria-label="{title}" tabindex="0" style="height:{height}px;position:relative;'
            'width:100%;background:#e5e7eb"></div><small>{attribution}</small></figure>'
        ).format(
            root=self._root_attributes(oob=oob),
            title=view.title,
            spec=spec,
            widget=self.widget_id,
            height=view.height,
            attribution=attribution,
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if event not in ("click", "viewport") or not self.is_enabled:
            super().dispatch(event, form)
        try:
            point = MapPoint(
                latitude=float(form.get("latitude", "")),
                longitude=float(form.get("longitude", "")),
            )
            zoom = float(form.get("zoom", "")) if event == "viewport" else 0.0
        except ValueError:
            super().dispatch(event, form)
        if not 0 <= zoom <= MapView.MAX_ZOOM:
            super().dispatch(event, form)
        if event == "click":
            self._view.clicked.emit(point.latitude, point.longitude)
        else:
            with self.stop_refresh():
                self._view.center = point
                self._view.zoom = zoom
            self._view.viewport_changed.emit()


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
    `series` list swaps the figure, the page keeping the user's zoom (see `page.js`).

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
                    # its hovered values shown as integers, e.g. counts
                    "whole": ChartView.is_whole(series.y),
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
        # a click on the plot (see `page.js`), at a point in the axes' values
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
        assert isinstance(view, ChartView)  # the chart renderer's only view
        options = chartimage.ImageOptions(
            x_range=_query_range(query, "x"), y_range=_query_range(query, "y")
        )
        content = chartimage.chart_image_bytes(view, image_format, options)
        return chartimage.image_name(view.title, image_format.lower()), content

    def to_html(self, *, oob: bool = False) -> Markup:
        title = self._view.title
        # the corner's controls at the end of the row, the title in the middle of the rest
        caption = (
            Markup(
                '<figcaption class="min-w-0 flex-1 text-center font-semibold">{}</figcaption>'
            ).format(title)
            if title
            else Markup('<span class="flex-1"></span>')
        )
        return (
            # a column: a card's figures are rows of images otherwise (daisyUI's `card`)
            Markup(
                '<figure {root_attributes} class="flex w-full flex-col gap-2">'
                '<div class="flex w-full items-center gap-2">{caption}{save_image_html}</div>'
                '<div id="{widget_id}-plot" data-chart="{chart_json}"'
                ' role="img" aria-label="{description}"'
                "{height_attributes}></div></figure>"
            ).format(
                root_attributes=self._root_attributes(oob=oob),
                caption=caption,
                save_image_html=self._save_image_html(),
                widget_id=self.widget_id,
                chart_json=self.chart_json(),
                description=self._description(),
                height_attributes=self._height_attributes(),
            )
        )

    def _height_attributes(self) -> Markup:
        """Get the plot's height: the view's, or the page's own (the script fits it to it)."""
        height = self._view.height
        if height is None:
            return Markup(' class="h-72 w-full"')
        return Markup(' class="w-full" style="height: {}px"').format(int(height))

    def _save_image_html(self) -> Markup:
        """Get the figure's corner: its image's download, in a format picked beside it."""
        text = self._view.save_image_text
        if not chartimage.is_available():
            # no matplotlib: the page draws what it shows, as a PNG
            name = chartimage.image_name(self._view.title, "png")
            return Markup(
                '<button type="button" class="btn btn-ghost btn-xs" data-chart-png="{}">'
                "{} (PNG)</button>"
            ).format(name, text)
        options = Markup("").join(
            Markup('<option value="{}">{}</option>').format(image_format, image_format.upper())
            for image_format in ("pdf", "svg", "png")
        )
        # a plain link: htmx can't start a download. The page's script adds the zoom
        return Markup(
            '<div class="join">'
            '<select class="select select-xs join-item w-auto" aria-label="Image format"'
            " data-chart-format>{options}</select>"
            '<a class="btn btn-ghost btn-xs join-item" data-chart-image download'
            ' href="/widget/{widget_id}/image?format=pdf">{text}</a></div>'
        ).format(options=options, widget_id=self.widget_id, text=text)


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

    def to_html(self, *, oob: bool = False) -> Markup:
        delta = self._view.delta
        badge = ""
        if delta is not None:
            color = "badge-success" if delta > 0 else "badge-error" if delta < 0 else "badge-ghost"
            text = MetricView.badge(delta, self._view.delta_text)
            badge = Markup(
                '<div class="stat-desc"><span class="badge badge-soft {}">{}</span></div>'
            ).format(color, text)
        return Markup(
            '<div {root_attributes} class="stat px-0">'
            '<div class="stat-title">{label}</div>'
            '<div class="stat-value">{value}</div>{badge}</div>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            label=self._view.label,
            value=self._view.value,
            badge=badge,
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
    cell_widgets: dict[int, CellWidget]
    cell_clicked: Signal[int, int]
    cell_styles: dict[tuple[int, int], CellStyle]
    header_groups: list[HeaderGroup]
    row_headers: list[str]

    def emit_cell_edited(self, row: int, column: int, text: str) -> None: ...
    def mark_text(self, mark: NodeMark) -> str: ...
    def shown_cell_styles(self) -> dict[tuple[int, int], CellStyle]: ...
    def is_checked(self, row: int, column: int) -> bool: ...
    def cell_style(self, row: int, column: int) -> CellStyle: ...
    def header_group(self, column: int) -> HeaderGroup | None: ...
    def column_checked(self, column: int) -> bool | None: ...
    def check_all(self, column: int, *, is_checked: bool) -> None: ...
    def sort_by(self, column: int) -> None: ...
    def filter_error(self, column: int, text: str) -> str | None: ...
    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str: ...
    def filter_takes_pattern(self, column: int) -> bool: ...
    def filter_chip(self, column: int) -> str: ...


#: the order a sortable column's header shows, as `aria-sort` says it
_ARIA_SORT: Final[dict[bool | None, str]] = {None: "none", False: "ascending", True: "descending"}


class FilteredLike(Protocol):
    """What a table's filter bar reads and sets, its columns known by their positions."""

    search: str
    filters: dict[int, str]

    @property
    def headers(self) -> list[str]: ...
    @property
    def filter_texts(self) -> dict[str, str]: ...
    @property
    def filterable_columns(self) -> list[int]: ...
    def filter_error(self, column: int, text: str) -> str | None: ...
    def filter_takes_pattern(self, column: int) -> bool: ...
    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str: ...
    def filter_chip(self, column: int) -> str: ...


#: the parts of a filter bar each part holds: the count is in the bar
_BAR_PARTS_INSIDE: Mapping[str, tuple[str, ...]] = MappingProxyType({"bar": ("count",)})


class WebFilterBarRenderer(WebRenderer[TView]):
    """A table's renderer with a filter bar: a search, "+ Filter" and the filters' chips.

    The bar reads and sets `_filtered`, its columns known by their positions. The search
    posts as the user types; "+ Filter" opens an editor in the bar (a column, a value and
    Add), and the filters show as chips. A change swaps only the parts it changes
    (`_mark_parts`): "bar", "count" or "error", never the field the user types in; a
    value that can't filter swaps only its message in, the page marking the field invalid.

    A table adds its own parts (`_own_parts`), and what one holds (`_parts_inside`): a
    change marking the whole (`_mark_dirty`) swaps the table whole.
    """

    #: the parts each part holds, which swap with it rather than apart
    _parts_inside: ClassVar[Mapping[str, tuple[str, ...]]] = _BAR_PARTS_INSIDE

    def __init__(self, view: TView) -> None:
        super().__init__(view)
        #: the parts to swap, unless the whole table is (`_mark_dirty`)
        self._dirty_parts: set[str] = set()
        self._is_whole_dirty = False
        #: the filter editor, while open: its column (None for the first) and its text
        self._editor: tuple[int | None, str] | None = None
        #: why the editor's text can't filter, once the user added it
        self._editor_error: str | None = None
        #: whether "+ Filter" takes the focus back, the editor or a chip just gone
        self._focus_add_filter = False
        #: the column whose chip takes the focus, its filter just added: Enter reopens it
        self._focused_chip: int | None = None

    @staticmethod
    def _table_part(markup: Markup, *, oob: bool) -> Markup:
        """Wrap a part of the `<table>` swapped out of band in a `<template>` of its own.

        htmx parses an answer as a template's content: a `<tr>` or a `<tbody>` among the
        rest would switch the parser to a table's rules for what follows, mangling the
        next fragments, e.g. another table swapped whole.
        """
        return Markup("<template>{}</template>").format(markup) if oob else markup

    @property
    @abstractmethod
    def _filtered(self) -> FilteredLike:
        """Get what the bar reads and sets: the view, or what knows its columns by position."""

    @abstractmethod
    def _count_text(self) -> str:
        """Count the rows shown, while the search or the filters hide some: else ""."""

    @abstractmethod
    def _own_parts(self) -> dict[str, Callable[..., Markup]]:
        """Get how to render each of the table's own parts, in the order they're swapped."""

    @abstractmethod
    def _whole_html(self, *, oob: bool) -> Markup:
        """Render the whole table, its bar and its parts."""

    def to_html(self, *, oob: bool = False) -> Markup:
        parts, self._dirty_parts = self._dirty_parts, set()
        is_whole, self._is_whole_dirty = self._is_whole_dirty or not oob or not parts, False
        html_ = self._whole_html(oob=oob) if is_whole else self._parts_html(parts)
        self._focus_add_filter, self._focused_chip = False, None
        return html_

    def _parts_html(self, parts: set[str]) -> Markup:
        """Render the parts changed, out of band, each one only once."""
        for part, inside in self._parts_inside.items():
            if part in parts:
                parts.difference_update(inside)
        # the bar last: it may hold the element that sent the request, which htmx swaps
        # nothing more from once it's gone
        renders: dict[str, Callable[..., Markup]] = {
            **self._own_parts(),
            "count": self._count_html,
            "error": self._error_html,
            "bar": self._bar_html,
        }
        return Markup("").join(
            render(oob=True) for part, render in renders.items() if part in parts
        )

    def _mark_dirty(self, view: TView, rendered_object: str, value: Any) -> None:
        self._is_whole_dirty = True
        super()._mark_dirty(view, rendered_object, value)

    def _part_marker(self, *parts: str) -> Callable[[TView, str, Any], None]:
        """Get a refresh handler swapping these parts of the table."""

        def mark(_view: TView, _rendered_object: str, _value: Any) -> None:
            self._mark_parts(*parts)

        return mark

    def _mark_parts(self, *parts: str) -> None:
        """Swap these parts of the table: "bar", "count" or "error", or its own."""
        dirty = _DIRTY.get()
        if dirty is not None:
            self._dirty_parts.update(parts)
            dirty[self.widget_id] = self

    def _oob(self, *, oob: bool) -> Markup:
        return Markup(' hx-swap-oob="true"') if oob else Markup()

    def _post(self, values: Mapping[str, str | int]) -> Markup:
        """Get the attributes posting an event of the table, without swapping its element back."""
        return Markup(
            """ hx-post="/widget/{}" hx-vals='{}'"""
            ' hx-swap="none"'
        ).format(self.widget_id, json.dumps(values))

    def _count_html(self, *, oob: bool = False) -> Markup:
        text = self._count_text()
        return Markup(
            '<span id="{widget_id}-count" class="ms-auto text-sm opacity-70"'
            ' aria-live="polite"{oob}>{text}</span>'
        ).format(widget_id=self.widget_id, oob=self._oob(oob=oob), text=text)

    def _filterable_columns(self) -> list[int]:
        return [
            column
            for column in self._filtered.filterable_columns
            if column < len(self._filtered.headers)
        ]

    def _bar_html(self, *, oob: bool = False) -> Markup:
        bar_id = f"{self.widget_id}-bar"
        if len(self._filterable_columns()) == 0:
            return Markup('<div id="{}" hidden{}></div>').format(bar_id, self._oob(oob=oob))
        texts = self._filtered.filter_texts
        disabled = "" if self.is_enabled else " disabled"
        search_label = texts.get("search", "")
        search = Markup(
            '<label class="input input-sm w-56">'
            '{search_icon}<input id="{widget_id}-search" type="search"'
            ' name="search" value="{search}"'
            ' placeholder="{search_label}" aria-label="{search_label}"'
            ' hx-post="/widget/{widget_id}"'
            ' hx-trigger="input changed delay:{delay}ms, search"'
            ' hx-vals=\'{{"event": "search"}}\' hx-swap="none" hx-sync="this:queue last"'
            ' autocomplete="off"{disabled}></label>'
        ).format(
            search_icon=_icon("search"),
            widget_id=self.widget_id,
            delay=SEARCH_DELAY_MS,
            search=self._filtered.search,
            search_label=search_label,
            disabled=disabled,
        )
        if self._editor is None:
            focus = " autofocus" if self._focus_add_filter else ""
            editor = Markup(
                '<button id="{widget_id}-add-filter" type="button"'
                ' class="btn btn-sm btn-soft"{post}'
                "{focus}{disabled}>{get}</button>"
            ).format(
                widget_id=self.widget_id,
                post=self._post({"event": "open_editor"}),
                focus=focus,
                disabled=disabled,
                get=texts.get("add_filter", ""),
            )
        else:
            editor = self._editor_html()
        chips = Markup("").join(
            self._chip_html(column) for column in sorted(self._filtered.filters)
        )
        clear = ""
        if len(self._filtered.filters) >= 2:  # noqa: PLR2004
            clear = Markup(
                '<button type="button" class="btn btn-sm btn-ghost"{post}{disabled}>{get}</button>'
            ).format(
                post=self._post({"event": "clear_filters"}),
                disabled=disabled,
                get=texts.get("clear", ""),
            )
        return Markup(
            '<div id="{bar_id}" role="search" class="flex flex-wrap items-center gap-2"'
            "{oob}>{search}{editor}{chips}{clear}{count_html}</div>"
        ).format(
            bar_id=bar_id,
            oob=self._oob(oob=oob),
            search=search,
            editor=editor,
            chips=chips,
            clear=clear,
            count_html=self._count_html(),
        )

    def _editor_html(self) -> Markup:
        assert self._editor is not None
        texts = self._filtered.filter_texts
        columns = self._filterable_columns()
        column, typed = self._editor
        chosen = column if column in columns else columns[0]
        text, is_pattern = split_pattern(typed)
        takes_pattern = self._filtered.filter_takes_pattern(chosen)
        is_pattern = is_pattern and takes_pattern
        options = Markup("").join(
            Markup(
                '<option value="{option}"'
                ' data-placeholder="{filter_placeholder}"'
                ' data-pattern-placeholder="{pattern_placeholder}"'
                "{value}>"
                "{headers}</option>"
            ).format(
                option=option,
                filter_placeholder=self._filtered.filter_placeholder(option),
                pattern_placeholder=self._pattern_placeholder(option),
                value=" selected" if option == chosen else "",
                headers=self._filtered.headers[option],
            )
            for option in columns
        )
        value_id = f"{self.widget_id}-value"
        value_label = texts.get("value", "")
        pattern_label = texts.get("pattern", "")
        placeholder = self._filtered.filter_placeholder(chosen, is_pattern=is_pattern)
        # a checkbox drawn as a button: on, the value is a regular expression; the page
        # shows it only for a column a pattern filters, and hints at what to type
        pattern = Markup(
            '<label class="btn btn-sm btn-soft font-mono has-checked:btn-primary"'
            ' title="{pattern_label}" data-filter-pattern{value}>'
            '<input type="checkbox" name="pattern" value="1" class="sr-only"'
            ' aria-label="{pattern_label}"{value2}>.*</label>'
        ).format(
            pattern_label=pattern_label,
            value="" if takes_pattern else " hidden",
            value2=" checked" if is_pattern else "",
        )
        return Markup(
            '<form id="{widget_id}-editor" class="flex flex-wrap items-center gap-2"'
            "{post}>"
            '<select name="column" class="select select-sm w-auto" data-filter-column'
            ' aria-label="{get}">{options}</select>'
            "{pattern}"
            '<input id="{value_id}" name="value" class="input input-sm w-60" type="text"'
            ' value="{text}" aria-label="{value_label}"'
            ' placeholder="{placeholder}"'
            ' aria-describedby="{value_id}-error" autocomplete="off" autofocus'
            ' hx-post="/widget/{widget_id}" hx-trigger="escape-key"'
            """ hx-vals='{{"event": "close_editor"}}' hx-swap="none">"""
            "{error_html}"
            '<button type="submit" class="btn btn-sm btn-primary">'
            "{get2}</button></form>"
        ).format(
            widget_id=self.widget_id,
            post=self._post({"event": "add_filter"}),
            get=texts.get("column", ""),
            options=options,
            pattern=pattern,
            value_id=value_id,
            text=text,
            value_label=value_label,
            placeholder=placeholder,
            error_html=self._error_html(),
            get2=texts.get("add", ""),
        )

    def _pattern_placeholder(self, column: int) -> str:
        """Hint at a regular expression filtering `column`, or "" if none does."""
        if not self._filtered.filter_takes_pattern(column):
            return ""
        return self._filtered.filter_placeholder(column, is_pattern=True)

    def _error_html(self, *, oob: bool = False) -> Markup:
        """Render the editor's message, why its text can't filter; the page marks the field."""
        error = self._editor_error
        hidden = "" if error else " hidden"
        return Markup(
            '<span id="{widget_id}-value-error" class="text-sm text-error"'
            ' data-log="error"{hidden}{oob}>{value}</span>'
        ).format(widget_id=self.widget_id, hidden=hidden, oob=self._oob(oob=oob), value=error or "")

    def _chip_html(self, column: int) -> Markup:
        if column >= len(self._filtered.headers):
            return Markup()
        texts, header = self._filtered.filter_texts, self._filtered.headers[column]
        remove = texts.get("remove", "{header}").format(header=header)
        edit = texts.get("edit", "{header}").format(header=header)
        disabled = "" if self.is_enabled else " disabled"
        focus = " autofocus" if self._focused_chip == column else ""
        # named by its text, the filter; the pencil and the tooltip say it edits it
        return Markup(
            '<span class="badge badge-soft badge-primary gap-1 pe-0">'
            '<button id="{widget_id}-chip-{column}" type="button"'
            ' class="inline-flex cursor-pointer items-center gap-1 hover:underline"'
            ' title="{edit}"'
            "{post}{focus}{disabled}>"
            "{filter_chip}{pencil_icon}</button>"
            '<button type="button" class="btn btn-ghost btn-xs btn-circle"'
            ' aria-label="{remove}" title="{remove}"'
            "{post2}{disabled}>\u00d7</button>"
            "</span>"
        ).format(
            widget_id=self.widget_id,
            column=column,
            edit=edit,
            post=self._post({"event": "open_editor", "column": column}),
            focus=focus,
            disabled=disabled,
            filter_chip=self._filtered.filter_chip(column),
            pencil_icon=_icon("pencil", "size-3"),
            remove=remove,
            post2=self._post({"event": "remove_filter", "column": column}),
        )

    def _column(self, form: Mapping[str, str], columns: list[int]) -> int | None:
        """Get the column posted, if one of `columns`: a stale page may post another."""
        column = form.get("column", "")
        return int(column) if column.isdigit() and int(column) in columns else None

    def _search(self, form: Mapping[str, str]) -> None:
        # not swapped back: the user is typing in it
        with self.stop_refresh():
            self._filtered.search = form.get("search", "")

    def _open_editor(self, form: Mapping[str, str]) -> None:
        column = self._column(form, self._filterable_columns())
        text = self._filtered.filters.get(column, "") if column is not None else ""
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
        if form.get("pattern") == "1" and self._filtered.filter_takes_pattern(column):
            text = as_pattern(text)
        error = self._filtered.filter_error(column, text)
        if error is not None:
            # the field keeps the text typed: only its message is swapped in
            self._editor, self._editor_error = (column, text), error
            self._mark_parts("error")
            return
        self._close_editor(form)
        self._focus_add_filter, self._focused_chip = False, column
        self._filtered.filters = {**self._filtered.filters, column: text}

    def _remove_filter(self, form: Mapping[str, str]) -> None:
        column = self._column(form, list(self._filtered.filters))
        self._focus_add_filter = True
        self._mark_parts("bar")
        if column is not None:
            self._filtered.filters = {
                other: text for other, text in self._filtered.filters.items() if other != column
            }

    def _clear_filters(self, _form: Mapping[str, str]) -> None:
        self._focus_add_filter = True
        self._mark_parts("bar")
        self._filtered.filters = {}


class WebTableRenderer(WebFilterBarRenderer[TableViewLike]):
    """A table under its filter bar, scrolling sideways on its own when wider than the page.

    Clicking a row, or pressing Enter on it, selects it; the table is swapped back to
    show it selected, each row keeping its own id so htmx gives the focus back to the
    row that had it. Selecting one row, it is the current one (`aria-current`).
    Selecting several, the table is a grid whose rows are each selected or not
    (`aria-selected`), and a click adds or removes its row.

    Double clicking a cell of `editable_columns`, or pressing F2 on its row (see
    `page.js`), edits it: the table comes back with a field in the cell, named by its
    header, its text selected. Enter or leaving the field posts the text, Escape puts the
    old text back first; either way the cell is text again. The page keeps the text the
    user is typing through a swap of the table, e.g. answering the double click's clicks.

    A column of `cell_widgets` holds a widget in each cell: a check box or a select,
    posting its change and never swapped back for it (only a check-all box in the header
    follows); a button after the cell's text, or the text as a link-like button, posting
    a click. A check-all column's header starts with its box, partly checked (see
    `page.js`) while some rows are; its click swaps back the rows, not itself.

    A cell of `cell_styles` has its background color, its text black or white on it, and
    its mark before its text, named for screen readers; a disabled one is grayed, its
    widget disabled and its text never edited. A cell spanning rows covers those under
    it (`rowspan`). The rows' headers start each row (`<th scope="row">`), and
    `header_groups` add a row of headers above the columns', each over its columns.

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
                "cell_widgets": self._mark_dirty,
                "cell_styles": self._part_marker("body"),
                "header_groups": self._mark_dirty,
                "row_headers": self._mark_dirty,
                "done_text": self._part_marker("body"),
                "warning_text": self._part_marker("body"),
                "error_text": self._part_marker("body"),
            }
        )

    def _refresh_rows(self, view: TableViewLike, rendered_object: str, value: Any) -> None:
        self._editing = None  # its row may have moved, or be gone
        self._mark_dirty(view, rendered_object, value)

    @property
    def _filtered(self) -> FilteredLike:
        return self._view

    def _count_text(self) -> str:
        shown, total = len(self._view.shown_rows), len(self._view.rows)
        if shown == total:
            return ""
        return self._view.filter_texts.get("count", "").format(shown=shown, total=total)

    def _own_parts(self) -> dict[str, Callable[..., Markup]]:
        return {"head": self._head_html, "body": self._body_html}

    def _whole_html(self, *, oob: bool) -> Markup:
        grid = Markup(' role="grid" aria-multiselectable="true"') if self._is_multiple() else ""
        return Markup(
            '<div {root_attributes} class="flex flex-col gap-2">'
            "{bar_html}"
            '<div class="overflow-x-auto rounded-box border border-base-300">'
            '<table class="table table-zebra table-sm"{grid}>'
            "{head_html}{body_html}</table></div></div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            bar_html=self._bar_html(),
            grid=grid,
            head_html=self._head_html(),
            body_html=self._body_html(),
        )

    def _head_html(self, *, oob: bool = False) -> Markup:
        """Render the headers: a row of them, under a row of `header_groups` if any.

        A column without a group has its header across both rows.
        """
        headers = self._view.headers
        groups = [group for group in self._view.header_groups if group.column < len(headers)]
        span = Markup(' rowspan="2"') if len(groups) > 0 else ""
        # the corner over the rows' headers
        top = [Markup("<td{}></td>").format(span)] if len(self._view.row_headers) > 0 else []
        bottom = []
        for column in range(len(headers)):
            group = self._view.header_group(column)
            if group is None:
                top.append(self._header_html(column, span))
                continue
            if group.column == column:
                columns = min(group.column_count, len(headers) - column)
                top.append(
                    Markup('<th colspan="{}" scope="colgroup" class="text-center">{}</th>').format(
                        columns, group.text
                    )
                )
            bottom.append(self._header_html(column, ""))
        rows = Markup("<tr>{}</tr>").format(Markup("").join(top)) + (
            Markup("<tr>{}</tr>").format(Markup("").join(bottom)) if groups else ""
        )
        return self._table_part(
            Markup('<thead id="{widget_id}-head"{oob}>{rows}</thead>').format(
                widget_id=self.widget_id, oob=self._oob(oob=oob), rows=rows
            ),
            oob=oob,
        )

    def _header_html(self, column: int, span: str) -> Markup:
        """Render a column's header, with its check-all box, a button if sortable."""
        header = self._view.headers[column]
        box = self._check_all_html(column)
        if column not in self._view.sortable_columns:
            if box == "":
                return Markup("<th{}>{}</th>").format(span, header)
            return Markup(
                '<th{span}><span class="flex items-center gap-2">{box}{header}</span></th>'
            ).format(span=span, box=box, header=header)
        order = self._view.sort_descending if self._view.sort_column == column else None
        arrow = {None: "", False: " ▲", True: " ▼"}[order]
        disabled = "" if self.is_enabled else " disabled"
        return Markup(
            '<th{span} aria-sort="{ARIA_SORT}" class="p-0">'
            '<span class="flex items-center{value}">{box}'
            '<button type="button" class="btn btn-ghost btn-sm flex-1 justify-start'
            ' font-semibold"{post}{disabled}>'
            '{header}<span aria-hidden="true">{arrow}</span></button></span></th>'
        ).format(
            span=span,
            ARIA_SORT=_ARIA_SORT[order],
            value=" ps-3" if box else "",
            box=box,
            post=self._post({"event": "sort", "column": column}),
            disabled=disabled,
            header=header,
            arrow=arrow,
        )

    def _body_html(self, *, oob: bool = False) -> Markup:
        shown = self._view.shown_rows
        styles = self._view.shown_cell_styles()
        covered = {
            (position + offset, column)
            for (position, column), style in styles.items()
            for offset in range(1, style.row_span)
        }
        rows = Markup("").join(
            self._row_html(index, self._view.rows[index], position, styles, covered)
            for position, index in enumerate(shown)
        )
        if len(shown) == 0 and len(self._view.rows) > 0:
            no_match = self._view.filter_texts.get("no_match", "")
            columns = max(len(self._view.headers), 1) + (1 if self._view.row_headers else 0)
            rows = Markup(
                '<tr><td colspan="{}" class="text-center opacity-70">{}</td></tr>'
            ).format(columns, no_match)
        return self._table_part(
            Markup('<tbody id="{widget_id}-body"{oob}>{rows}</tbody>').format(
                widget_id=self.widget_id, oob=self._oob(oob=oob), rows=rows
            ),
            oob=oob,
        )

    def _check_all_html(self, column: int) -> Markup:
        """Render a check-all column's box, or "" for another column."""
        if column not in self._check_all_columns():
            return Markup()
        is_checked = self._view.column_checked(column)
        state = {True: " checked", False: "", None: " data-indeterminate"}[is_checked]
        disabled = "" if self.is_enabled and column in self._view.editable_columns else " disabled"
        # its own id, so htmx gives it the focus back when the head is swapped
        return Markup(
            '<input id="{widget_id}-check-all-{column}" type="checkbox"'
            ' class="checkbox checkbox-sm" aria-label="{headers}"'
            "{state}{post}"
            ' hx-trigger="change" autocomplete="off"{disabled}>'
        ).format(
            widget_id=self.widget_id,
            column=column,
            headers=self._view.headers[column],
            state=state,
            post=self._post({"event": "check_all", "column": column}),
            disabled=disabled,
        )

    def _check_all_columns(self) -> list[int]:
        return [
            column
            for column, widget in self._view.cell_widgets.items()
            if widget.kind is CellKind.CHECK_BOX
            and widget.check_all
            and column < len(self._view.headers)
        ]

    def _row_html(
        self,
        index: int,
        row: list[str],
        position: int,
        styles: dict[tuple[int, int], CellStyle],
        covered: set[tuple[int, int]],
    ) -> Markup:
        """Render a row, at `position` among those shown, as `styles` say its cells look.

        The cells `covered` by a cell spanning rows above aren't rendered.
        """
        # a row short of an editable cell, a widget's or a styled one's still gets the
        # cell, empty
        widths = [
            *self._editable_columns(),
            *self._view.cell_widgets,
            *(column for shown, column in styles if shown == position),
        ]
        width = max(len(row), *(column + 1 for column in widths), 0)
        cells = Markup("").join(
            self._cell_html(
                index,
                column,
                row[column] if column < len(row) else "",
                styles.get((position, column), PLAIN_CELL),
            )
            for column in range(width)
            if (position, column) not in covered
        )
        if len(self._view.row_headers) > 0:
            header = self._view.row_headers[index] if index < len(self._view.row_headers) else ""
            cells = Markup('<th scope="row">{}</th>{}').format(header, cells)

        is_selected = index in self._view.selected_rows
        if self._is_multiple():
            selected = Markup(' aria-selected="{}"').format("true" if is_selected else "false")
        else:
            selected = Markup(' aria-current="true"') if is_selected else Markup()
        if not self.is_enabled:
            return Markup("<tr{}>{}</tr>").format(selected, cells)
        return Markup(
            '<tr id="{widget_id}-row-{index}" class="cursor-pointer" tabindex="0"'
            '{selected} hx-post="/widget/{widget_id}"'
            # a click or Enter, not from a cell's field or widget, which takes its own
            ' hx-trigger="activate"'
            """ hx-vals='{{"event": "select", "row": "{index}"}}' hx-swap="none">"""
            "{cells}</tr>"
        ).format(widget_id=self.widget_id, index=index, selected=selected, cells=cells)

    def _cell_html(self, row: int, column: int, text: str, style: CellStyle) -> Markup:
        """Render a cell: its mark, then its text, widget or field, as `style` says."""
        widget = self._view.cell_widgets.get(column)
        if widget is not None and column < len(self._view.headers):
            content = self._widget_html(row, column, text, widget, is_disabled=not style.is_enabled)
            # a disabled widget is grayed already
            look = self._look(attrs.evolve(style, is_enabled=True))
            return Markup("<td{}>{}</td>").format(look, self._marked(style, content))
        if column not in self._editable_columns() or not self.is_enabled or not style.is_enabled:
            return Markup("<td{}>{}</td>").format(self._look(style), self._marked(style, text))

        def post(event: str) -> Markup:
            return Markup(
                ' hx-post="/widget/{widget_id}" hx-swap="none"'
                """ hx-vals='{{"event": "{event}", "row": "{row}", "column": "{column}"}}'"""
            ).format(widget_id=self.widget_id, event=event, row=row, column=column)

        if self._editing != (row, column):
            return Markup('<td{look} data-edit hx-trigger="dblclick"{post}>{marked}</td>').format(
                look=self._look(style), post=post("start_edit"), marked=self._marked(style, text)
            )
        header = self._view.headers[column]
        # its own id, so htmx gives it the focus back when the table is swapped
        return Markup(
            '<td{look}><input id="{widget_id}-cell-{row}-{column}"'
            ' type="text"'
            ' class="input input-ghost input-sm w-full min-w-0" name="text" data-cell'
            ' value="{text}" data-original="{text}"'
            ' aria-label="{header}" autocomplete="off" autofocus'
            ' hx-trigger="enter-key, blur"'
            "{post}></td>"
        ).format(
            look=self._look(style, "p-0"),
            widget_id=self.widget_id,
            row=row,
            column=column,
            text=text,
            header=header,
            post=post("edit"),
        )

    @staticmethod
    def _look(style: CellStyle, classes: str = "") -> Markup:
        """Get the attributes giving a cell its colors, grayed if disabled, and its rows' span."""
        if not style.is_enabled:
            classes = f"{classes} opacity-50".strip()
        attributes = Markup(' class="{}"').format(classes) if classes else Markup()
        if style.background is not None:
            attributes += Markup(' style="background-color: {}; color: {}"').format(
                style.background, style.text_color
            )
        if style.row_span > 1:
            attributes += Markup(' rowspan="{}"').format(style.row_span)
        return attributes

    def _marked(self, style: CellStyle, content: str) -> Markup:
        """Put the cell's mark, if any, before its content, named for screen readers."""
        if style.mark is None:
            return escape(content)
        icon, color = _MARK_ICONS[style.mark]
        text = self._view.mark_text(style.mark)
        return Markup(
            '<span class="flex items-center gap-1"><span class="shrink-0 {color}" role="img"'
            ' aria-label="{text}" title="{text}">{icon}</span>{content}</span>'
        ).format(color=color, text=text, icon=_icon(icon), content=content)

    def _widget_html(
        self, row: int, column: int, text: str, widget: CellWidget, *, is_disabled: bool
    ) -> Markup:
        """Render a cell's widget, named by its column's header; disabled with its cell."""
        header = self._view.headers[column]
        is_editable = self.is_enabled and column in self._view.editable_columns and not is_disabled
        values = {"row": row, "column": column}
        # its own id, so htmx gives it the focus back when the table is swapped
        widget_id = f"{self.widget_id}-cell-{row}-{column}"
        if widget.kind is CellKind.CHECK_BOX:
            checked = " checked" if self._view.is_checked(row, column) else ""
            return Markup(
                '<input id="{widget_id}" type="checkbox" class="checkbox checkbox-sm"'
                ' name="checked" value="on" aria-label="{header}"{checked}'
                '{post} hx-trigger="change"'
                ' autocomplete="off"{value}>'
            ).format(
                widget_id=widget_id,
                header=header,
                checked=checked,
                post=self._post({"event": "check", **values}),
                value="" if is_editable else " disabled",
            )
        if widget.kind is CellKind.COMBOBOX:
            options = [*widget.options, *([] if text in widget.options else [text])]
            choices = Markup("").join(
                Markup('<option value="{option}"{value}>{option}</option>').format(
                    option=option, value=" selected" if option == text else ""
                )
                for option in options
            )
            return Markup(
                '<select id="{widget_id}" class="select select-sm w-full min-w-24" name="text"'
                ' aria-label="{header}"{post}'
                ' hx-trigger="change" autocomplete="off"{value}>'
                "{choices}</select>"
            ).format(
                widget_id=widget_id,
                header=header,
                post=self._post({"event": "pick", **values}),
                value="" if is_editable else " disabled",
                choices=choices,
            )
        disabled = "" if self.is_enabled and not is_disabled else " disabled"
        click = self._post({"event": "click_cell", **values})
        if widget.kind is CellKind.LINK:
            return Markup(
                '<button id="{widget_id}" type="button" class="link'
                ' link-primary"{click}{disabled}>{text}</button>'
            ).format(widget_id=widget_id, click=click, disabled=disabled, text=text)
        label = f"{self._view.headers[column]}: {widget.text}"
        return Markup(
            '<span class="flex items-center gap-2"><span class="flex-1">{text}'
            '</span><button id="{widget_id}" type="button" class="btn btn-xs btn-soft"'
            ' aria-label="{label}" title="{label}"{click}{disabled}>'
            "{text2}</button></span>"
        ).format(
            text=text,
            widget_id=widget_id,
            label=label,
            click=click,
            disabled=disabled,
            text2=widget.text,
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a disabled table can't be clicked: a post saying otherwise is refused
        if not self.is_enabled:
            super().dispatch(event, form)
        if event in ("start_edit", "edit"):
            self._edit(event, form)
            return
        handlers = {
            "check": self._check,
            "pick": self._pick,
            "check_all": self._check_all,
            "click_cell": self._click_cell,
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

    def _sort(self, form: Mapping[str, str]) -> None:
        column = self._column(form, self._view.sortable_columns)
        if column is None:
            self._mark_parts("head", "body")  # as it now is
            return
        self._view.sort_by(column)

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
            or not self._view.cell_style(int(row), int(column)).is_enabled
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

    def _widget_cell(
        self, form: Mapping[str, str], kinds: tuple[CellKind, ...]
    ) -> tuple[int, int] | None:
        """Get the cell posted, if a shown one of a widget of `kinds` the user can use.

        A stale page may post another.
        """
        row, column = form.get("row", ""), form.get("column", "")
        if not row.isdigit() or int(row) not in self._view.shown_rows or not column.isdigit():
            return None
        widget = self._view.cell_widgets.get(int(column))
        if widget is None or widget.kind not in kinds or int(column) >= len(self._view.headers):
            return None
        is_edit = widget.kind in (CellKind.CHECK_BOX, CellKind.COMBOBOX)
        if is_edit and int(column) not in self._view.editable_columns:
            return None
        if not self._view.cell_style(int(row), int(column)).is_enabled:
            return None
        return int(row), int(column)

    def _check(self, form: Mapping[str, str]) -> None:
        self._set_widget_cell(
            self._widget_cell(form, (CellKind.CHECK_BOX,)), CHECKED_TEXTS["checked" in form]
        )

    def _pick(self, form: Mapping[str, str]) -> None:
        self._set_widget_cell(self._widget_cell(form, (CellKind.COMBOBOX,)), form.get("text", ""))

    def _set_widget_cell(self, cell: tuple[int, int] | None, text: str) -> None:
        """Apply a check box's or a select's change, which the widget already shows."""
        if cell is None:
            self._mark_dirty(self._view, self.widget_id, self._view.rows)  # as it now is
            return
        cells = self._view.rows[cell[0]]
        if text == (cells[cell[1]] if cell[1] < len(cells) else ""):
            return
        rows = self._view.rows
        self._view.emit_cell_edited(*cell, text)
        # unless the app answered with its own rows, which it has marked to show
        if self._view.rows is rows:
            with self.stop_refresh():
                self._view.rows = replace_cell(rows, *cell, text)
            if len(self._check_all_columns()) > 0:
                self._mark_parts("head")  # a check-all box follows its column's

    def _check_all(self, form: Mapping[str, str]) -> None:
        column = self._column(form, self._check_all_columns())
        if column is None or column not in self._view.editable_columns:
            self._mark_parts("head")  # a stale page: the head as it now is
            return
        # the rows swapped back, not the box, which sent the request and shows the click
        with self.stop_refresh():
            self._view.check_all(column, is_checked=self._view.column_checked(column) is not True)
        self._editing = None
        self._mark_parts("body", "count")

    def _click_cell(self, form: Mapping[str, str]) -> None:
        cell = self._widget_cell(form, (CellKind.BUTTON, CellKind.LINK))
        if cell is None:
            self._mark_dirty(self._view, self.widget_id, self._view.rows)  # as it now is
            return
        self._view.cell_clicked.emit(*cell)

    def _editable_columns(self) -> list[int]:
        """Get the `editable_columns` the table has a header for, and the user types in."""
        return [
            column
            for column in self._view.editable_columns
            if 0 <= column < len(self._view.headers) and column not in self._view.cell_widgets
        ]

    def _is_multiple(self) -> bool:
        return self._view.selection_mode is SelectionMode.MULTIPLE


TValue = TypeVar("TValue")


class SourceTableViewLike(ViewLike, Protocol):
    texts: dict[str, str]
    sort_column: str | None
    sort_descending: bool
    selection_mode: SelectionMode
    search: str
    filters: dict[str, str]
    filterable_columns: list[str]
    filter_texts: dict[str, str]

    @property
    def headers(self) -> list[str]: ...
    @property
    def column_names(self) -> list[str]: ...
    @property
    def row_count(self) -> int: ...
    @property
    def count_text(self) -> str: ...
    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]: ...
    def sort_by(self, column: str) -> None: ...
    def is_selected(self, row_id: Any) -> bool: ...
    def select_at(self, position: int) -> None: ...
    def extend_to(self, position: int) -> None: ...
    def header(self, column: str) -> str: ...
    def filter_error(self, column: str, text: str) -> str | None: ...
    def filter_takes_pattern(self, column: str) -> bool: ...
    def filter_placeholder(self, column: str, *, is_pattern: bool = False) -> str: ...
    def filter_chip(self, column: str) -> str: ...
    def selection_text(self) -> str: ...
    def csv_chunks(self) -> Iterator[str]: ...

    export_filename: str


class WebSourceTableRenderer(WebFilterBarRenderer[SourceTableViewLike]):
    """A large table, scrolled in a frame: the page draws only the rows around the view.

    The frame holds the headers, a window of `SOURCE_TABLE_WINDOW_ROWS` rows, and two filler
    rows that give the scroll bar the height of every row. When the user stops scrolling
    outside the window, `page.js` posts the first row shown (`scroll`), and only the
    `<tbody>` comes back, the scroll position kept, that row still under the headers.
    Past `SOURCE_TABLE_SCROLLED_ROWS` rows, the fillers stop growing: a filler's height
    stands for more rows than as many drawn ones (`_fillers`).
    Each row starts with its position, from 1, and tells screen readers where it is
    (`aria-rowindex` of `aria-rowcount`).

    A new order of the rows (a sort, a search, a filter, the source changed) swaps the
    whole frame, scrolled to the top. A header is a button sorting by its column
    (`SourceTableView.sort_by`), keeping the focus as it comes back (`autofocus`). A click
    on a row, or Enter on it, selects it (`select_at`): only the rows come back, the row
    keeping the focus. The web neither extends a selection nor activates a row. While a
    column of `filterable_columns` filters, the filter bar (`WebFilterBarRenderer`) is
    above the frame. Ctrl+C in the frame posts `copy` (see `page.js`): the selected rows'
    text (`SourceTableView.selection_text`) comes back in a hidden element, which the page
    writes to the clipboard. A link above the frame downloads the rows shown as CSV
    (`csv_chunks`, streamed by the `/widget/{id}/csv` route).
    """

    _role = "source_table"

    def __init__(self, view: SourceTableViewLike) -> None:
        super().__init__(view)
        self._by_position = SourceTableByPosition(view)
        #: the position of the window's first row
        self._start = 0
        #: the filler's height above the window, in rows' heights, where the page scrolled
        #: to; None: its rows scaled (`_scale`)
        self._before: float | None = None
        #: the column whose header takes the focus as it comes back: the user sorted by it
        self._focused_header: str | None = None
        #: the position of the row that takes the focus as it comes back: the user selected it
        self._focused_row: int | None = None
        #: the text the user copied, sent once in the "copied" part; None: nothing to send
        self._copied: str | None = None
        self._refresh_dispatcher.update(
            {
                **dict.fromkeys(
                    ("source", "texts", "filter_texts", "filterable_columns"), self._mark_dirty
                ),
                "row_count": self._reorder,
                **dict.fromkeys(
                    ("column_formats", "selected_ids", "selection_mode"),
                    self._part_marker("rows"),
                ),
                "search": self._part_marker("bar"),
                "filters": self._part_marker("bar"),
                # shown with the order they give, which the view sends as `row_count`
                "sort_column": lambda _view, _table, _value: None,
                "sort_descending": lambda _view, _table, _value: None,
                # read as the user downloads
                "export_filename": lambda _view, _table, _value: None,
                # never: the web orders in the request's thread (`draws_on_main_thread`)
                "is_ordering": lambda _view, _table, _value: None,
            }
        )

    @property
    def _filtered(self) -> FilteredLike:
        return self._by_position

    def _count_text(self) -> str:
        return self._view.count_text

    def _reorder(self, _view: SourceTableViewLike, _rendered_object: str, _value: Any) -> None:
        """Show a new order of the rows from its first: the frame comes back to the top."""
        self._start, self._before = 0, None
        self._mark_parts("frame", "count")

    _parts_inside = MappingProxyType({**_BAR_PARTS_INSIDE, "frame": ("rows",)})

    def _own_parts(self) -> dict[str, Callable[..., Markup]]:
        return {"frame": self._frame_html, "rows": self._rows_html, "copied": self._copied_html}

    def _whole_html(self, *, oob: bool) -> Markup:
        return Markup(
            '<div {root_attributes} class="flex flex-col gap-2">{bar_html}'
            # a plain link: htmx can't start a download
            '<a class="btn btn-ghost btn-xs self-end" href="/widget/{widget_id}/csv"'
            " download>{export}</a>{frame_html}{copied_html}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            bar_html=self._bar_html(),
            frame_html=self._frame_html(),
            copied_html=self._copied_html(),
            widget_id=self.widget_id,
            export=self._view.texts.get("export", ""),
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a scroll only reads: a disabled table still shows the rows scrolled to
        if not self.is_enabled and event != "scroll":
            super().dispatch(event, form)
        handlers: dict[str, Callable[[Mapping[str, str]], None]] = {
            "search": self._search,
            "open_editor": self._open_editor,
            "close_editor": self._close_editor,
            "add_filter": self._add_filter,
            "remove_filter": self._remove_filter,
            "clear_filters": self._clear_filters,
            "sort": self._sort,
            "select": self._select,
            "scroll": self._scroll,
            "copy": self._copy,
        }
        if event not in handlers:
            super().dispatch(event, form)
        handlers[event](form)

    def _sort(self, form: Mapping[str, str]) -> None:
        column = form.get("column", "")
        if column not in self._view.column_names:
            super().dispatch("sort", form)
        self._focused_header = column
        self._view.sort_by(column)

    def _select(self, form: Mapping[str, str]) -> None:
        position = form.get("position", "")
        if not position.isdigit() or int(position) >= self._view.row_count:
            # a row a stale page still shows: swap the rows back as they now are
            self._mark_parts("rows")
            return
        self._focused_row = int(position)
        self._view.select_at(int(position))

    def _scroll(self, form: Mapping[str, str]) -> None:
        """Draw the window around the first row shown, a fifth of it above.

        The page posts the row under the headers (`start`) and how far down the frame it
        is (`offset`, in rows' heights): the filler above the window gets the height that
        keeps that row there, the frame's scroll position kept.
        """
        shown = form.get("start", "")
        if not shown.isdigit():
            return
        last_start = max(self._view.row_count - SOURCE_TABLE_WINDOW_ROWS, 0)
        start = min(max(int(shown) - SOURCE_TABLE_WINDOW_ROWS // 5, 0), last_start)
        try:
            offset = float(form.get("offset", ""))
        except ValueError:
            offset = math.nan
        before = offset - (int(shown) - start) if math.isfinite(offset) else None
        if (start, before) != (self._start, self._before):
            self._start, self._before = start, before
            self._mark_parts("rows")

    def csv_file(self) -> tuple[str, Iterator[str]]:
        """Get the download's name, and the rows shown as CSV, in pieces."""
        return self._view.export_filename, self._view.csv_chunks()

    def _copy(self, _form: Mapping[str, str]) -> None:
        self._copied = self._view.selection_text()
        self._mark_parts("copied")

    def _copied_html(self, *, oob: bool = False) -> Markup:
        """Render the hidden element posting a copy, holding the text copied once answered.

        An answer (`data-copy-answer`, its text empty without a row selected) is sent
        once, out of band or in the whole table: the page waits for no other.
        """
        copied, self._copied = self._copied, None
        return Markup(
            '<pre id="{widget_id}-copied" hidden data-copied{answer}'
            ' hx-post="/widget/{widget_id}"'
            """ hx-trigger="copy-rows" hx-vals='{{"event": "copy"}}' hx-swap="none"{oob}>"""
            "{copied}</pre>"
        ).format(
            widget_id=self.widget_id,
            answer=Markup() if copied is None else Markup(" data-copy-answer"),
            oob=Markup(' hx-swap-oob="true"') if oob else Markup(),
            copied="" if copied is None else copied,
        )

    def _scale(self) -> float:
        """Get the rows each row's height of the scroll bar stands for: 1 up to the cap."""
        return max(self._view.row_count / SOURCE_TABLE_SCROLLED_ROWS, 1.0)

    def _header_html(self, name: str, header: str, *, is_focused: bool) -> Markup:
        """Render a column's header: a button sorting by the column, its order after it."""
        view = self._view
        order = view.sort_descending if view.sort_column == name else None
        arrow = {None: "", False: " ▲", True: " ▼"}[order]
        return Markup(
            '<th scope="col" aria-sort="{aria_sort}" class="p-0">'
            '<button type="button" class="btn btn-ghost btn-sm w-full justify-start'
            ' font-semibold"{post}{disabled}{autofocus}>'
            '{header}<span aria-hidden="true">{arrow}</span></button></th>'
        ).format(
            aria_sort=_ARIA_SORT[order],
            post=self._post({"event": "sort", "column": name}),
            disabled="" if self.is_enabled else " disabled",
            autofocus=" autofocus" if is_focused else "",
            header=header,
            arrow=arrow,
        )

    def _row_html(
        self, position: int, row_id: Any, cells: list[str], *, is_focused: bool
    ) -> Markup:
        """Render a row: its position, then its cells; a click or Enter selects it."""
        is_selected = self._view.is_selected(row_id)
        if self._view.selection_mode is SelectionMode.MULTIPLE:
            selected = Markup(' aria-selected="{}"').format("true" if is_selected else "false")
        else:
            selected = Markup(' aria-current="true"') if is_selected else Markup()
        content = Markup(
            '<th scope="row" class="tabular-nums whitespace-nowrap">{position}</th>{cells}'
        ).format(
            position=f"{position + 1:,}",
            cells=Markup("").join(
                Markup('<td class="whitespace-nowrap">{}</td>').format(cell) for cell in cells
            ),
        )
        if not self.is_enabled:
            return Markup('<tr class="h-9" aria-rowindex="{}"{} data-window-row>{}</tr>').format(
                position + 2, selected, content
            )
        return Markup(
            '<tr class="h-9 cursor-pointer" tabindex="0" aria-rowindex="{index}"'
            '{selected}{autofocus} data-window-row hx-post="/widget/{widget_id}"'
            """ hx-trigger="activate" hx-vals='{vals}' hx-swap="none">{content}</tr>"""
        ).format(
            index=position + 2,
            selected=selected,
            autofocus=" autofocus" if is_focused else "",
            widget_id=self.widget_id,
            vals=json.dumps({"event": "select", "position": str(position)}),
            content=content,
        )

    def _frame_html(self, *, oob: bool = False) -> Markup:
        """Render the scrolled frame: the headers, then the window of rows between fillers.

        Its hidden field takes the first row shown, which `page.js` posts on a scroll.
        """
        view = self._view
        focused, self._focused_header = self._focused_header, None
        head = Markup("").join(
            self._header_html(name, header, is_focused=name == focused)
            for name, header in zip(view.column_names, view.headers)
        )
        return Markup(
            '<div id="{widget_id}-frame" class="max-h-[36rem] overflow-y-auto rounded-box'
            ' border border-base-300" tabindex="0"'
            " data-virtual-scroll{oob}>"
            '<input type="hidden" name="offset" id="{widget_id}-offset" data-scroll-offset>'
            '<input type="hidden" name="start" data-scroll-start'
            ' hx-post="/widget/{widget_id}" hx-trigger="scroll-window"'
            ' hx-include="#{widget_id}-offset"'
            """ hx-vals='{{"event": "scroll"}}' hx-swap="none" hx-sync="this:replace">"""
            '<table class="table table-zebra table-sm" aria-rowcount="{row_count}">'
            '<thead class="sticky top-0 z-10 bg-base-100"><tr aria-rowindex="1"><td></td>'
            "{head}</tr></thead>{rows_html}</table></div>"
        ).format(
            widget_id=self.widget_id,
            oob=Markup(' hx-swap-oob="true"') if oob else Markup(),
            row_count=view.row_count + 1,
            head=head,
            rows_html=self._rows_html(),
        )

    def _rows_html(self, *, oob: bool = False) -> Markup:
        """Render the `<tbody>`: the window of rows, between the fillers standing for the rest.

        A filler is as tall as its rows, `_scale` of them to a row's height.
        """
        view = self._view
        start = min(self._start, max(view.row_count - 1, 0))
        rows = view.rows(start, start + SOURCE_TABLE_WINDOW_ROWS)
        width = len(view.headers) + 1
        if len(rows) == 0:
            empty = view.filter_texts.get("no_match", "") if view.count_text else ""
            body = Markup(
                '<tr><td colspan="{}" class="text-center opacity-70">{}</td></tr>'
            ).format(width, empty or view.texts.get("empty", ""))
        else:
            focused_row, self._focused_row = self._focused_row, None
            before, after = self._fillers(start, len(rows))
            body = Markup("{before}{rows}{after}").format(
                before=self._filler_html(before, width),
                rows=Markup("").join(
                    self._row_html(
                        start + offset, row_id, cells, is_focused=start + offset == focused_row
                    )
                    for offset, (row_id, cells) in enumerate(rows)
                ),
                after=self._filler_html(after, width),
            )
        return self._table_part(
            Markup('<tbody id="{}-rows"{}>{}</tbody>').format(
                self.widget_id, Markup(' hx-swap-oob="true"') if oob else Markup(), body
            ),
            oob=oob,
        )

    def _fillers(self, start: int, drawn: int) -> tuple[float, float]:
        """Get the heights, in rows' heights, of the fillers above and under the window.

        Together they stand for the rows not drawn, scaled: the frame keeps its height. The
        one above is where the page scrolled to (`_before`), else its rows scaled, and none
        from the first row.
        """
        hidden = (self._view.row_count - drawn) / self._scale()
        before = start / self._scale() if self._before is None else self._before
        before = 0.0 if start == 0 else min(max(before, 0.0), hidden)
        if start + drawn >= self._view.row_count:
            before = hidden  # down to the last row: no filler under it
        return before, hidden - before

    @staticmethod
    def _filler_html(height: float, width: int) -> Markup:
        """Render a row standing for rows not drawn, `height` rows' heights tall."""
        if height <= 0:
            return Markup()
        return Markup(
            '<tr aria-hidden="true" style="height: calc(2.25rem * {})"><td colspan="{}"></td></tr>'
        ).format(f"{height:.3f}", width)


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

    def _htmx_attributes(self) -> Markup:
        return Markup(
            ' name="{}" hx-post="/widget/{}" hx-trigger="change"'
            ' hx-vals=\'{{"event": "change"}}\' hx-swap="none"'
        ).format(self.widget_id, self.widget_id)


class WebRadioGroupRenderer(_WebValuesRenderer[TValue]):
    _role = "radio_group"
    is_labelable = False

    def to_html(self, *, oob: bool = False) -> Markup:
        selected = self._view.serialize_value()
        disabled = "" if self.is_enabled else " disabled"
        options = Markup("").join(
            Markup(
                '<label class="label cursor-pointer gap-2 text-base-content">'
                '<input type="radio" class="radio radio-sm radio-primary" value="{key}"'
                "{value}{htmx_attributes}"
                ' autocomplete="off"{disabled}>'
                "{label}</label>"
            ).format(
                key=key,
                value=" checked" if key == selected else "",
                htmx_attributes=self._htmx_attributes(),
                disabled=disabled,
                label=label,
            )
            for key, label in self._view.options
        )
        return Markup(
            '<div {root_attributes}{row_attributes} role="radiogroup" class="flex flex-wrap gap-x-6'
            ' gap-y-2">{options}</div>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            options=options,
        )


class WebComboBoxRenderer(_WebValuesRenderer[TValue]):
    _role = "combobox"

    def to_html(self, *, oob: bool = False) -> Markup:
        selected = self._view.serialize_value()
        disabled = "" if self.is_enabled else " disabled"
        # an empty choice only while nothing is selected, as Qt's combobox shows nothing
        empty = Markup('<option value="" selected></option>') if selected is None else ""
        options = Markup("").join(
            Markup('<option value="{key}"{value}>{label}</option>').format(
                key=key, value=" selected" if key == selected else "", label=label
            )
            for key, label in self._view.options
        )
        return Markup(
            '<select {root_attributes}{row_attributes} class="select w-full"{htmx_attributes}'
            ' autocomplete="off"{disabled}>{empty}{options}</select>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            htmx_attributes=self._htmx_attributes(),
            disabled=disabled,
            empty=empty,
            options=options,
        )


class LabelViewLike(ViewLike, Protocol):
    text: str


class WebLabelRenderer(WebRenderer[LabelViewLike]):
    _role = "label"

    def __init__(self, view: LabelViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> Markup:
        return Markup("<span {}>{}</span>").format(self._root_attributes(oob=oob), self._view.text)


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

    def to_html(self, *, oob: bool = False) -> Markup:
        parser = MarkdownIt("commonmark", {"html": False}).enable("table")
        # markup the parser escaped itself: the text's own HTML is off
        content = Markup(parser.render(self._view.text))  # noqa: S704
        return Markup('<div {} class="cui-markdown">{}</div>').format(
            self._root_attributes(oob=oob), content
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
        """The id of the ``<label>`` itself, which names a field ``<label for>`` can't."""
        return f"{self.widget_id}-text"

    @property
    def help_id(self) -> str:
        """The id of the row's help, which describes the field while there is help."""
        return f"{self.widget_id}-help"

    def has_help(self) -> bool:
        return self._view.help != ""

    def to_html(self, *, oob: bool = False) -> Markup:
        field = self._field_renderer()
        # a radio group or a checkbox is a `<div>`, which isn't labelable: its
        # `aria-labelledby` names it instead
        target = Markup(' for="{}"').format(field.widget_id) if field.is_labelable else ""
        return Markup(
            '<div {root_attributes} class="flex items-center gap-1">'
            '<label id="{text_id}"{target}'
            ' class="label text-sm font-medium text-base-content"'
            ">{label}</label>{help_html}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            text_id=self.text_id,
            target=target,
            label=self._view.label,
            help_html=self._help_html(),
        )

    def _help_html(self) -> Markup:
        """Render the "?" button and the help it opens, which also describes the field.

        Closed, the popover is hidden, which `aria-describedby` still reads. The page's
        script places it beside the button (see `page.js`).
        """
        if not self.has_help():
            return Markup()
        return Markup(
            '<button type="button" popovertarget="{help_id}"'
            ' class="inline-flex cursor-pointer rounded-full text-base-content/40'
            " transition-colors hover:text-primary focus-visible:text-primary"
            ' focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"'
            ' aria-label="{help_button_text}">{help_icon}</button>'
            # `cui-help`: the arrow pointing at the button, see `css/app.css`
            '<div id="{help_id}" popover data-help class="cui-help m-0 w-max max-w-80'
            " rounded-field border border-base-300 bg-base-100 px-3 py-2 text-xs"
            ' leading-relaxed text-base-content shadow-lg">'
            "{help}</div>"
        ).format(
            help_id=self.help_id,
            help_button_text=self._view.help_button_text,
            help_icon=_icon("help"),
            help=self._view.help,
        )

    def _refresh_help(self, view: FormLabelRowView, rendered_object: str, value: str) -> None:
        self._mark_dirty(view, rendered_object, value)
        dirty = _DIRTY.get()
        if dirty is not None and (view.help == "") != (value == ""):
            # its `aria-describedby` gains or loses the help
            field = self._field_renderer()
            dirty[field.widget_id] = field

    def _field_renderer(self) -> WebRenderer[Any]:
        assert isinstance(self._view.renderer, RendererContainer)  # a row's label's
        field_renderer = self._view.renderer.get_renderer("field")
        assert isinstance(field_renderer, WebRenderer)
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

    def to_html(self, *, oob: bool = False) -> Markup:
        attributes = self._root_attributes(oob=oob)
        if self._view.is_visible and self._view.log_message == "":
            attributes += " hidden"  # same as Qt/Textual: an empty log takes no room
        if isinstance(self._view, FormRowView) and self._view.has_form_error:
            attributes += " data-form-error"  # a check of the form failed on this row
        # `pre-line`: `FormView.validate` joins its messages with newlines.
        # `data-log`, `data-form-error`: the page's stylesheet and script mark the field
        # just before the log as invalid
        return Markup(
            '<p {attributes} aria-live="polite" data-log="{lower}" class="text-sm'
            ' whitespace-pre-line {LOG_CLASSES}">{log_message}</p>'
        ).format(
            attributes=attributes,
            lower=self._view.log_type.name.lower(),
            LOG_CLASSES=_LOG_CLASSES[self._view.log_type],
            log_message=self._view.log_message,
        )


def _is_shown(view: View) -> bool:
    """Tell whether this backend shows `view`: with a renderer of its own, or as a form row."""
    return isinstance(view.renderer, WebRenderer) or (
        isinstance(view, FormRowView) and isinstance(view.renderer, RendererContainer)
    )


def _view_html(view: View) -> Markup:
    """Get `view`'s HTML in a layout; a form row's anywhere, as a form shows it."""
    renderer = view.renderer
    if isinstance(view, FormRowView) and isinstance(renderer, RendererContainer):
        parts = (
            ["label", "field", "log"] if isinstance(view, FormLabelRowView) else ["field", "log"]
        )
        # field right before log: the page's stylesheet marks a field followed by an error
        return Markup('<div class="flex flex-col gap-1">{}</div>').format(
            Markup("").join(_fragment(renderer.get_renderer(part)) for part in parts)
        )
    return _fragment(renderer)


def _fragment(renderer: Any) -> Markup:
    return renderer.to_html() if isinstance(renderer, WebRenderer) else Markup()


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

    def to_html(self, *, oob: bool = False) -> Markup:
        return self._fieldset(oob=oob, classes="flex min-w-0 flex-col gap-5", legend="")

    def _fieldset(self, *, oob: bool, classes: str, legend: str) -> Markup:
        disabled = "" if self.is_enabled else " disabled"
        # a row whose field this backend doesn't support: empty
        rows = Markup("").join(_view_html(row) for row in self._view.field_rows)
        return Markup(
            "<fieldset {root_attributes}"
            ' class="{classes}"{disabled}>{legend}{rows}{fragment}</fieldset>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            classes=classes,
            disabled=disabled,
            legend=legend,
            rows=rows,
            fragment=_fragment(self._view.log_view.renderer),
        )


class WebGroupFormRenderer(WebFormRenderer):
    """A titled group of rows, e.g. `pipeform.py`'s "Main Pipe"."""

    _role = "group_form"

    def __init__(self, view: GroupFormView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"title": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> Markup:
        title = self._view.title if isinstance(self._view, GroupFormView) else ""
        return self._fieldset(
            oob=oob,
            classes="fieldset form-grid min-w-0 gap-4 rounded-box border border-base-300"
            " bg-base-200 p-4",
            legend=(
                Markup(
                    '<legend class="fieldset-legend px-1 text-sm font-semibold text-primary">'
                    "{}</legend>"
                ).format(title)
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

    def to_html(self, *, oob: bool = False) -> Markup:
        # docked like Qt/Textual's status bar; an empty message leaves a quiet empty line
        return Markup(
            "<footer {root_attributes}{auto_clear_attributes}"
            ' role="status" aria-live="polite"'
            ' class="status-bar fixed inset-x-0 bottom-0 z-20 flex min-h-9 items-center gap-2'
            ' border-t border-base-300 px-4 text-sm">'
            "{message}"
            "</footer>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            auto_clear_attributes=self._auto_clear_attributes(),
            message=self._view.message,
        )

    def _auto_clear_attributes(self) -> Markup:
        """Fetch the bar again once its message has timed out.

        `show_message`'s timer clears the message on the server outside any request,
        so no response ever tells the browser. Instead, a bar showing a message asks
        for its own current state once, just after `timeout`; by then the timer has
        cleared it. A message that was replaced or re-shown meanwhile comes back with
        its own fresh delay, so a stale fetch is harmless.
        """
        if self._view.message == "" or self._view.timeout <= 0:
            return Markup()
        # margin: the browser's delay starts after the server's timer did, but not by much
        delay_ms = round((self._view.timeout + _AUTO_CLEAR_MARGIN) * 1000)
        return Markup(
            ' hx-get="/widget/{}" hx-trigger="load delay:{}ms" hx-swap="outerHTML"'
        ).format(self.widget_id, delay_ms)


#: closes an open daisyUI dropdown (it stays open while something in it has focus)
_CLOSE_DROPDOWN = "data-close-dropdown"


def _web_shortcut(shortcut: str | None) -> tuple[str, str] | None:
    """Map a view's `Ctrl+<letter or digit>` shortcut to one the browser leaves free.

    Browsers keep most Ctrl shortcuts for themselves (Ctrl+N opens a window, Ctrl+O a
    file, Ctrl+S saves the page, Ctrl+Q quits Firefox on Linux), so `Ctrl+x` becomes
    `Alt+Shift+X`, the combination web apps use for their own shortcuts. Returns the
    label to show and the physical key (`KeyboardEvent.code`) the page's key handler
    matches (see `page.js`); None for any other shortcut, which has no free web
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
    "new": Markup('<path d="M12 5v14M5 12h14"/>'),
    "open": Markup(
        '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
    ),
    "save": Markup(
        '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
    ),
    "more": Markup(
        '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/>'
        '<circle cx="19" cy="12" r="1"/>'
    ),
    "chevron": Markup('<path d="m6 9 6 6 6-6"/>'),
    "search": Markup('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>'),
    "help": Markup(
        '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
        '<path d="M12 17h.01"/>'
    ),
    "pencil": Markup(
        '<path d="M21.17 6.81a1 1 0 0 0-3.98-3.98L3.84 16.17a2 2 0 0 0-.5.83l-1.32'
        ' 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z"/><path d="m15 5 4 4"/>'
    ),
    "sidebar": Markup('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>'),
    "calendar": (
        Markup(
            '<rect x="3" y="4" width="18" height="18" rx="2"/>'
            '<path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>'
        )
    ),
    "reload": Markup(
        '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>'
    ),
    "circle-check": Markup('<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>'),
    "circle-alert": Markup(
        '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>'
    ),
    "circle-x": Markup('<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>'),
}

#: a tree node's mark: its icon and its color, as a log's are colored
_MARK_ICONS: Final = {
    NodeMark.DONE: ("circle-check", "text-success"),
    NodeMark.WARNING: ("circle-alert", "text-warning"),
    NodeMark.ERROR: ("circle-x", "text-error"),
}


def _icon(name: str, size: str = "size-4") -> Markup:
    return Markup(
        '<svg class="{}" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        "{}</svg>"
    ).format(size, _ICONS[name])


def _file_icon(icon: str | None) -> Markup:
    """Show an action's icon file, or nothing without one (see `icons.py`).

    An SVG is drawn in the text's color, as the built-in icons are, so it follows the
    theme: only its shape counts. Any other image shows as it is.
    """
    url = None if icon is None else icon_url(icon)
    if url is None:
        return Markup()
    if url.endswith(".svg"):
        mask = f"url('{url}') center / contain no-repeat"
        return Markup(
            '<span aria-hidden="true" class="size-4 shrink-0 bg-current"'
            ' style="mask: {}; -webkit-mask: {}"></span>'
        ).format(mask, mask)
    return Markup(
        '<img src="{}" alt="" aria-hidden="true" class="size-4 shrink-0 object-contain">'
    ).format(url)


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

    def to_html(self, *, oob: bool = False) -> Markup:
        oob_attribute = Markup(' hx-swap-oob="true"') if oob else ""
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
        title = self._view.title
        if len(buttons) == 0:
            # a chevron: it opens a menu, unlike the header buttons next to it
            trigger = Markup(
                '<div tabindex="0" role="button" class="btn btn-ghost btn-sm gap-1 pr-2"'
                ' aria-haspopup="menu">'
                '{}<span class="opacity-60">{}</span></div>'
            ).format(title, _icon("chevron"))
        else:
            trigger = Markup(
                '<div tabindex="0" role="button" class="btn btn-ghost btn-sm btn-square"'
                ' aria-label="{title}" title="{title}">{more_icon}</div>'
            ).format(title=title, more_icon=_icon("more"))
        dropdown = (
            Markup(
                '<div class="dropdown dropdown-end">'
                "{}"
                # as wide as its longest item, its text and shortcut on one line
                '<ul tabindex="0" class="menu dropdown-content z-30 mt-2 w-max min-w-56'
                ' rounded-box border border-base-300 bg-base-100 p-2 shadow-lg">'
                "{}</ul></div>"
            ).format(trigger, Markup("").join(item for (_, item) in items))
            if len(items) > 0
            else ""
        )
        return Markup(
            '<div id="{widget_id}"{oob_attribute} class="flex items-center'
            ' gap-1">{join}{dropdown}</div>'
        ).format(
            widget_id=self.widget_id,
            oob_attribute=oob_attribute,
            join=Markup("").join(buttons),
            dropdown=dropdown,
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

    Those two can't go through the generic widget event: a download has to be a form's
    post (htmx can't start one), and a file has to be uploaded. Both name the action
    (`trigger`), so its `triggered` still fires first, for whatever user code is
    connected to it.
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

    def to_html(self, *, oob: bool = False) -> Markup:
        self._is_shown = True
        if self.placement is Placement.OMITTED:
            return Markup("<span {} hidden></span>").format(self._root_attributes(oob=oob))
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
            Markup('<kbd class="ml-6 font-sans text-xs text-base-content/50">{}</kbd>').format(
                shortcut[0]
            )
            if shortcut
            else ""
        )
        label = Markup(
            '<span class="flex items-center gap-2'
            ' whitespace-nowrap">{file_icon}{check}{text}</span>{kbd}'
        ).format(file_icon=_file_icon(view.icon), check=check, text=view.text, kbd=kbd)
        key = Markup(' data-shortcut="{}"').format(shortcut[1]) if shortcut else ""
        if not view.is_enabled:
            item = Markup(
                '<button type="button" class="justify-between" disabled>{}</button>'
            ).format(label)
        else:
            item = self._active_html(Markup('class="justify-between"'), label, key)
        menu_disabled = "" if view.is_enabled else Markup(' class="menu-disabled"')
        return Markup("<li {root_attributes}{menu_disabled}>{item}</li>").format(
            root_attributes=self._root_attributes(oob=oob), menu_disabled=menu_disabled, item=item
        )

    def _button_html(self, *, oob: bool) -> Markup:
        """Render a header button: Save the highlighted one, its shortcut in the tooltip."""
        view = self._view
        shortcut = _web_shortcut(view.shortcut)
        text = view.text
        tooltip = f"{text} ({shortcut[0]})" if shortcut else text
        style = "btn-primary" if isinstance(view, SaveAction) else "btn-ghost"
        icon = _file_icon(view.icon)
        if icon == "":
            if isinstance(view, NewAction):
                icon = _icon("new")
            else:
                icon = _icon("open" if isinstance(view, OpenFileAction) else "save")
        attributes = Markup(
            '{root_attributes} class="btn btn-sm {style}" title="{tooltip}"'
        ).format(root_attributes=self._root_attributes(oob=oob), style=style, tooltip=tooltip)
        label = Markup('{}<span class="toolbar-label">{}</span>').format(icon, text)
        if not view.is_enabled:
            return Markup('<button {} type="button" disabled>{}</button>').format(attributes, label)
        key = Markup(' data-shortcut="{}"').format(shortcut[1]) if shortcut else ""
        return self._active_html(attributes, label, key)

    def _tool_html(self, *, oob: bool) -> Markup:
        """Render a toolbar button, pressed while checked, its shortcut in the tooltip.

        With an icon, it keeps only the icon on a phone, as the header's buttons do: the
        tooltip then names it.
        """
        view = self._view
        shortcut = _web_shortcut(view.shortcut)
        text = view.text
        icon = _file_icon(view.icon)
        label = (
            Markup('{}<span class="toolbar-label">{}</span>').format(icon, text) if icon else text
        )
        if shortcut:
            tooltip = Markup(' title="{} ({})"').format(text, shortcut[0])
        else:
            tooltip = Markup(' title="{}"').format(text) if icon else Markup()
        is_checked = view.is_checkable and view.is_checked
        active = " btn-active" if is_checked else ""
        pressed = (
            Markup(' aria-pressed="{}"').format(str(is_checked).lower())
            if view.is_checkable
            else ""
        )
        attributes = Markup(
            '{root_attributes} class="btn btn-ghost btn-sm{active}"{tooltip}{pressed}'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            active=active,
            tooltip=tooltip,
            pressed=pressed,
        )
        if not self.is_enabled:
            return Markup('<button {} type="button" disabled>{}</button>').format(attributes, label)
        key = Markup(' data-shortcut="{}"').format(shortcut[1]) if shortcut else ""
        return self._active_html(attributes, label, key)

    def _page_link_html(self, *, oob: bool) -> Markup:
        """Render a toolbar link to a page: still a link to its address, for a new tab.

        A click posts `triggered` instead of following the link: the router navigates,
        and the response puts the page's address in the browser's history.
        """
        view = self._view
        is_current = view.is_checkable and view.is_checked
        shortcut = _web_shortcut(view.shortcut)
        text = view.text
        tooltip = Markup(' title="{} ({})"').format(text, shortcut[0]) if shortcut else ""
        icon = _file_icon(view.icon)
        label = Markup("{}{}").format(icon, text)
        gap = " gap-2" if icon else ""
        classes = f"tab tab-active{gap}" if is_current else f"tab{gap}"
        current = Markup(' aria-current="page"') if is_current else ""
        if not view.is_enabled:
            return Markup(
                '<a {root_attributes} class="tab tab-disabled{gap}"'
                ' aria-disabled="true"{tooltip}>{label}</a>'
            ).format(
                root_attributes=self._root_attributes(oob=oob),
                gap=gap,
                tooltip=tooltip,
                label=label,
            )
        key = Markup(' data-shortcut="{}"').format(shortcut[1]) if shortcut else ""
        href = self.href or ""
        return Markup(
            '<a {root_attributes} class="{classes}" href="{href}"{current}'
            '{tooltip} hx-post="/widget/{widget_id}"'
            """ hx-vals='{{"event": "triggered"}}' hx-swap="none"{key}>{label}</a>"""
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            classes=classes,
            href=href,
            current=current,
            tooltip=tooltip,
            widget_id=self.widget_id,
            key=key,
            label=label,
        )

    def _active_html(self, attributes: str, label: str, key: str) -> Markup:
        """Render the element a click (or the page's key handler, through `key`) activates."""
        view = self._view
        if isinstance(view, (SaveAction, SaveAsAction)):
            # it fires the action, so it posts the page's form, a download as answer
            return Markup(
                '<button {attributes} type="submit" form="{SAVE_FORM_ID}" name="trigger"'
                ' value="{widget_id}" {CLOSE_DROPDOWN}{key}>{label}</button>'
            ).format(
                attributes=attributes,
                SAVE_FORM_ID=SAVE_FORM_ID,
                widget_id=self.widget_id,
                CLOSE_DROPDOWN=_CLOSE_DROPDOWN,
                key=key,
                label=label,
            )
        if isinstance(view, OpenFileAction):
            accept = "" if self.accept is None else Markup(' accept="{}"').format(self.accept)
            return Markup(
                '<label {attributes}>{label}<input type="file" name="file"{accept}'
                ' class="hidden" hx-post="/state" hx-encoding="multipart/form-data"'
                """ hx-trigger="change" hx-vals='{{"trigger": "{widget_id}"}}'"""
                ' hx-swap="none" autocomplete="off" {CLOSE_DROPDOWN}{key}></label>'
            ).format(
                attributes=attributes,
                label=label,
                accept=accept,
                widget_id=self.widget_id,
                CLOSE_DROPDOWN=_CLOSE_DROPDOWN,
                key=key,
            )
        if isinstance(view, PickFileAction):
            types = ",".join(self.file_types)
            accept = Markup(' accept="{}"').format(types) if types else ""
            # emptied once sent: picking the same file again is a change too
            return Markup(
                '<label {attributes}>{label}<input type="file" name="file"{accept}'
                ' class="hidden" hx-post="/widget/{widget_id}/file"'
                ' hx-encoding="multipart/form-data" hx-trigger="change" hx-swap="none"'
                ' data-clear-after-post autocomplete="off"'
                " {CLOSE_DROPDOWN}{key}></label>"
            ).format(
                attributes=attributes,
                label=label,
                accept=accept,
                widget_id=self.widget_id,
                CLOSE_DROPDOWN=_CLOSE_DROPDOWN,
                key=key,
            )
        return Markup(
            '<button {attributes} type="button"'
            """ hx-post="/widget/{widget_id}" hx-vals='{{"event": "triggered"}}'"""
            ' hx-swap="none" {CLOSE_DROPDOWN}{key}>{label}</button>'
        ).format(
            attributes=attributes,
            widget_id=self.widget_id,
            CLOSE_DROPDOWN=_CLOSE_DROPDOWN,
            key=key,
            label=label,
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
        return _file_types(view.extensions)

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

    def to_html(self, *, oob: bool = False) -> Markup:
        if self.is_in_toolbar:
            return Markup(
                '<div {} role="separator"'
                ' aria-orientation="vertical" class="mx-1 h-5 w-px bg-base-300"></div>'
            ).format(self._root_attributes(oob=oob))
        return Markup('<li {} role="separator"><hr class="my-1 border-base-300 p-0"></li>').format(
            self._root_attributes(oob=oob)
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

    def to_html(self, *, oob: bool = False) -> Markup:
        items = _between_items(
            [
                (isinstance(child, SeparatorAction), child.renderer.to_html())
                for child in self._view.children_views
                if isinstance(child.renderer, WebRenderer)
            ]
        )
        title = self._view.title
        label = Markup(' aria-label="{}"').format(title) if title else ""
        return Markup(
            '<div {root_attributes} role="toolbar"{label} class="flex items-center'
            ' gap-1">{join}</div>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            label=label,
            join=Markup("").join(item for (_, item) in items),
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

    def to_html(self, *, oob: bool = False) -> Markup:
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
            Markup(
                ' hx-post="/widget/{}" hx-trigger="cancel"'
                """ hx-vals='{{"event": "dismiss"}}'"""
            ).format(self.widget_id)
            if self.is_enabled
            else " data-keep-open"
        )
        title = (
            Markup('<h2 id="{}" class="text-lg font-bold">{}</h2>').format(title_id, view.title)
            if view.title
            else ""
        )
        labelledby = Markup(' aria-labelledby="{}"').format(title_id) if view.title else ""
        return Markup(
            '<dialog {root_attributes} class="modal" data-dialog'
            '{labelledby} aria-describedby="{text_id}"{cancel} hx-swap="none">'
            '<div class="modal-box">{title}'
            '<p id="{text_id}" class="py-4 whitespace-pre-line">{text}</p>'
            '<div class="modal-action">{reject}{accept}</div></div></dialog>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            labelledby=labelledby,
            text_id=text_id,
            cancel=cancel,
            title=title,
            text=view.text,
            reject=reject,
            accept=accept,
        )

    def _button_html(self, event: str, text: str, classes: str, disabled: str) -> Markup:
        # the dialog's own `close`, not `cancel`: no dismissal posted on top of the answer
        autofocus = " autofocus" if event == "accept" else ""
        return Markup(
            '<button type="button" class="{classes}" hx-post="/widget/{widget_id}"'
            """ hx-vals='{{"event": "{event}"}}'"""
            " data-close-dialog{autofocus}{disabled}>"
            "{text}</button>"
        ).format(
            classes=classes,
            widget_id=self.widget_id,
            event=event,
            autofocus=autofocus,
            disabled=disabled,
            text=text,
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        answers = {
            "accept": self._view.accept,
            "reject": self._view.reject,
            "dismiss": self._view.dismiss,
        }
        answer = answers.get(event)
        if answer is None:
            super().dispatch(event, form)  # raises: no answer of a dialog's
        elif self.is_enabled:
            answer()


TForm = TypeVar("TForm", bound=FormView)


class WebFormDialogRenderer(WebDialogRenderer, Generic[TForm]):
    """A modal `<dialog>` holding its form, then Cancel and OK.

    OK is disabled while a check of the form fails, and only it swaps when that changes:
    the dialog itself, swapped while open, would take back what the user is typing.
    Unlike a message's, OK doesn't close the dialog in the browser: the form may refuse
    it, the dialog then staying open with its checks shown; the server swaps it closed
    once accepted. Cancel and Escape close it first, as for any dialog.
    """

    _role = "form_dialog"

    def __init__(self, view: TypedFormDialogView[TForm]) -> None:
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

    def to_html(self, *, oob: bool = False) -> Markup:
        is_whole, self._is_whole = self._is_whole, False
        if oob and not is_whole:
            return self._accept_html(oob=True)
        view = self._form_view
        title_id = f"{self.widget_id}-title"
        text_id = f"{self.widget_id}-text"
        disabled = "" if self.is_enabled else " disabled"
        reject = self._button_html("reject", view.reject_text, "btn", disabled)
        cancel = (
            Markup(
                ' hx-post="/widget/{}" hx-trigger="cancel"'
                """ hx-vals='{{"event": "dismiss"}}'"""
            ).format(self.widget_id)
            if self.is_enabled
            else " data-keep-open"
        )
        title = (
            Markup('<h2 id="{}" class="text-lg font-bold">{}</h2>').format(title_id, view.title)
            if view.title
            else ""
        )
        text = (
            Markup('<p id="{}" class="whitespace-pre-line">{}</p>').format(text_id, view.text)
            if view.text
            else ""
        )
        labelledby = Markup(' aria-labelledby="{}"').format(title_id) if view.title else ""
        describedby = Markup(' aria-describedby="{}"').format(text_id) if view.text else ""
        form = view.form.renderer
        form_html = form.to_html() if isinstance(form, WebRenderer) else ""
        return Markup(
            '<dialog {root_attributes} class="modal" data-dialog'
            '{labelledby}{describedby}{cancel} hx-swap="none">'
            '<div class="modal-box flex flex-col gap-4">{title}{text}{form_html}'
            '<div class="modal-action">{reject}{accept_html}</div>'
            "</div></dialog>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            labelledby=labelledby,
            describedby=describedby,
            cancel=cancel,
            title=title,
            text=text,
            form_html=form_html,
            reject=reject,
            accept_html=self._accept_html(oob=False),
        )

    def _accept_html(self, *, oob: bool) -> Markup:
        swap = Markup(' hx-swap-oob="true"') if oob else ""
        disabled = "" if self.is_enabled and self._form_view.is_accept_enabled else " disabled"
        return Markup(
            '<button id="{accept_id}" type="button" class="btn btn-primary"{swap}'
            ' hx-post="/widget/{widget_id}"'
            """ hx-vals='{{"event": "accept"}}'{disabled}>"""
            "{accept_text}</button>"
        ).format(
            accept_id=self.accept_id,
            swap=swap,
            widget_id=self.widget_id,
            disabled=disabled,
            accept_text=self._form_view.accept_text,
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

    def to_html(self, *, oob: bool = False) -> Markup:
        stretched_views = self._view.stretched_views
        if not any(stretch > 0 for _, stretch in stretched_views):
            # as wide as their content: a container query would measure them as 0 wide
            cells = Markup("").join(
                Markup(
                    '<div class="min-w-0 has-[>[hidden]]:hidden" style="flex: none">{}</div>'
                ).format(_view_html(view))
                for view, _ in stretched_views
                if _is_shown(view)
            )
            align = " justify-end" if self._view.align is Align.END else ""
            return Markup('<div {root_attributes} class="flex gap-6{align}">{cells}</div>').format(
                root_attributes=self._root_attributes(oob=oob), align=align, cells=cells
            )
        cells = Markup("").join(
            Markup(
                '<div class="min-w-0 has-[>[hidden]]:hidden @2xl:flex-(--share)"'
                # no share: as wide as its content
                ' style="--share: {}">'
                "{}</div>"
            ).format(f"{stretch} 1 0%" if stretch > 0 else "none", _view_html(view))
            for view, stretch in stretched_views
            if _is_shown(view)
        )
        # the row's own width is queried from its root, the views laid out inside it
        return Markup(
            '<div {} class="@container">'
            '<div class="flex flex-col gap-6 @2xl:flex-row">{}</div></div>'
        ).format(self._root_attributes(oob=oob), cells)


class WebVerticalRenderer(WebRenderer[VerticalView]):
    """Views one above the other, at the top of the column, like a page's."""

    _role = "vertical"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> Markup:
        content = Markup("").join(
            _view_html(view) for view in self._view.children_views if _is_shown(view)
        )
        return Markup('<div {} class="flex flex-col gap-6">{}</div>').format(
            self._root_attributes(oob=oob), content
        )


class WebSplitterRenderer(WebRenderer[SplitterView]):
    """Panes side by side, each in a cell as wide as its share, a border between two.

    A border is an ARIA window splitter (a focusable separator) the user drags, or moves
    with the arrow keys; the browser shares the width between the panes beside it at
    once (see `page.js`), then posts every pane's width (`resize`): like every control,
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

    def render(self) -> None:
        super().render()
        self._adopt(self._view.panes)

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
            ' hx-post="/widget/{widget_id}" hx-trigger="toggle"'
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

    def to_html(self, *, oob: bool = False) -> Markup:
        positions = {
            path: position for position, (path, _node) in enumerate(walk_tree(self._view.nodes))
        }
        # clipped to a pane too narrow for it, the focus rings at its edges left whole
        return Markup(
            '<ul {} class="flex flex-col gap-0.5 overflow-clip [overflow-clip-margin:4px]">{}</ul>'
        ).format(self._root_attributes(oob=oob), self._nodes_html(self._view.nodes, (), positions))

    def _nodes_html(
        self, nodes: Iterable[TreeNode], parent: TreePath, positions: Mapping[TreePath, int]
    ) -> Markup:
        disabled = "" if self.is_enabled else " disabled"
        items: list[str] = []
        for node in nodes:
            path = (*parent, node.key)
            position, label = positions[path], node.label
            children = ""
            if len(node.children) == 0:
                toggle = Markup('<span class="size-6 shrink-0" aria-hidden="true"></span>')
            else:
                is_expanded = path in self._view.expanded
                turn = "" if is_expanded else " -rotate-90"
                # named by its node, which `aria-expanded` says it expands or collapses
                toggle = Markup(
                    '<button id="{widget_id}-toggle-{position}" type="button"'
                    ' class="btn btn-ghost btn-xs btn-square"'
                    ' aria-expanded="{lower}" aria-label="{label}"'
                    "{post}{disabled}>"
                    "{chevron_icon}</button>"
                ).format(
                    widget_id=self.widget_id,
                    position=position,
                    lower=str(is_expanded).lower(),
                    label=label,
                    post=self._post("toggle", path, expanded=not is_expanded),
                    disabled=disabled,
                    chevron_icon=_icon("chevron", "size-3" + turn),
                )
                if is_expanded:
                    children = Markup(
                        '<ul class="ms-3 flex flex-col gap-0.5 border-s border-base-300 ps-1">'
                        "{}</ul>"
                    ).format(self._nodes_html(node.children, path, positions))
            is_selected = path == self._view.selected
            selected = Markup(' aria-current="true"') if is_selected else ""
            variant = "btn-soft btn-primary" if is_selected else "btn-ghost"
            mark_id = f"{self.widget_id}-mark-{position}"
            described = (
                "" if node.mark is None else Markup(' aria-describedby="{}"').format(mark_id)
            )
            items.append(
                Markup(
                    '<li><div class="flex items-center gap-1">{toggle}'
                    '<button id="{widget_id}-node-{position}" type="button"'
                    ' class="btn btn-sm {variant} min-w-0 shrink justify-start font-normal"'
                    "{selected}{described}"
                    "{post}{disabled}>{node_content}"
                    "</button></div>{children}</li>"
                ).format(
                    toggle=toggle,
                    widget_id=self.widget_id,
                    position=position,
                    variant=variant,
                    selected=selected,
                    described=described,
                    post=self._post("select", path),
                    disabled=disabled,
                    node_content=self._node_content(node, mark_id),
                    children=children,
                )
            )
        return Markup("").join(items)

    def _node_content(self, node: TreeNode, mark_id: str) -> Markup:
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
        label = Markup('<span class="{}">{}</span>').format(
            " ".join(["truncate", *styles]), node.label
        )
        mark = ""
        if node.mark is not None:
            icon, color = _MARK_ICONS[node.mark]
            text = self._view.mark_text(node.mark)
            mark = Markup(
                '<span class="shrink-0 {color}">{icon}</span><span id="{mark_id}"'
                " hidden>{text}</span>"
            ).format(color=color, icon=_icon(icon), mark_id=mark_id, text=text)
        return Markup("{file_icon}{label}{mark}").format(
            file_icon=_file_icon(node.icon), label=label, mark=mark
        )

    def _post(self, event: str, path: TreePath, *, expanded: bool = False) -> Markup:
        """Get the attributes posting an event of the node at `path`, without swapping it back."""
        values = {"event": event, "path": json.dumps(list(path))}
        if event == "toggle":
            values["expanded"] = str(expanded).lower()
        return Markup(
            """ hx-post="/widget/{}" hx-vals='{}'"""
            ' hx-swap="none"'
        ).format(self.widget_id, json.dumps(values))

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
    it. A button in the header (`toggle_html`; see `page.js`) retracts and expands the
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
        """The id of the drawer's checkbox, checked while the drawer shows on a phone."""
        return f"{self.widget_id}-drawer"

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

    def _item_html(self, view: View) -> Markup:
        content = _view_html(view)
        return Markup('<div id="{}">{}</div>').format(self._item_id(view), content)

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

    def to_html(self, *, oob: bool = False) -> Markup:
        content = Markup("").join(
            _view_html(view) for view in self._view.children_views if _is_shown(view)
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

    The browser shows the tab picked, by a click or the arrow keys (see `page.js`),
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
                    ' class="tab{active}" data-tab hx-post="/widget/{widget_id}"'
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
        # the grid's own width is queried from its root, the views laid out inside it
        return Markup(
            '<div {root_attributes} class="@container">'
            '<div class="grid grid-cols-1 items-start gap-6 @2xl:grid-cols-(--columns)"'
            ' style="--columns: {columns}">{cells}</div></div>'
        ).format(root_attributes=self._root_attributes(oob=oob), columns=columns, cells=cells)


#: the main column's width, following the shown page's `PageView.width`: switching pages
#: only swaps the router, so CSS picks the width from the page neither hidden nor in a
#: hidden slot
_MAIN_WIDTHS = (
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
            assert isinstance(page.action.renderer, WebActionRenderer)
            page.action.renderer.placement = Placement.PAGE
            page.action.renderer.href = page_path(page.route)

    def to_html(self, *, oob: bool = False) -> Markup:
        slots: list[str] = []
        for page in self._view.pages:
            assert isinstance(page.renderer, WebRenderer)  # a page's, which the web has
            hidden = "" if page.route == self._view.current_route else " hidden"
            slots.append(
                Markup('<div data-route="{route}"{hidden}>{to_html}</div>').format(
                    route=page.route, hidden=hidden, to_html=page.renderer.to_html()
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
            '<nav aria-label="Pages" class="tabs tabs-box tabs-sm order-last w-full'
            ' flex-nowrap overflow-x-auto sm:order-none sm:w-auto">{}</nav>'
        ).format(links)


#: first segments of the backend's own addresses, which no page's address can take
RESERVED_ROUTES: Final = frozenset({"icon", "jobs", "reload", "state", "static", "widget"})


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

    def page_html(self, reload_instance: str | None = None) -> str:
        """Get the whole page; with `reload_instance`, it reloads once its server restarts."""
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
        main = Markup(
            '<main class="mx-auto {} px-4 pt-8 pb-20">'
            '<div class="card border border-base-300 bg-base-100 shadow-md">'
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
            Markup("").join(content),
        )
        return get_page(
            self._view.title,
            # sticky: the menus stay at hand however long the form is
            Markup(
                '<header class="navbar sticky top-0 z-20 min-h-14{wrap} gap-3 border-b'
                " border-base-300"
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
            icon=self._app_icon_url(),
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
                '<div id="cui-brand"{swap} class="flex min-w-0 flex-1 basis-0 items-center gap-2'
                ' sm:flex-none sm:basis-auto">'
                "{badge}"
                '<h1 class="truncate text-lg font-semibold">{title}</h1></div>'
            ).format(swap=swap, badge=badge, title=title)
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


#: renderer keys of the web backend, looked up by `composeui.core.registry.create_renderer`
RENDERERS: Final[dict[str, Callable[[Any], Renderer[Any, Any]]]] = {
    "action": WebActionRenderer,
    "button": WebButtonRenderer,
    "chart": WebChartRenderer,
    "map": WebMapRenderer,
    "checkbox": WebCheckBoxRenderer,
    "combobox": WebComboBoxRenderer,
    "source_table": WebSourceTableRenderer,
    "date_input": WebDateInputRenderer,
    "file_path_input": WebFilePathInputRenderer,
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
