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
import enum
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
    Align,
    ButtonVariant,
    DialogKind,
    DialogView,
    ExitAppAction,
    FormLabelRowView,
    FormRowView,
    FormView,
    GroupFormView,
    HorizontalView,
    LogType,
    MainView,
    Menu,
    NewAction,
    OpenFileAction,
    PageView,
    ProgressBarView,
    Router,
    SaveAction,
    SaveAsAction,
    SelectionMode,
    SeparatorAction,
    StatusBar,
    ToolBar,
    VerticalView,
    View,
    replace_cell,
)
from composeui.webcore.icons import icon_url
from composeui.webcore.page import get_page

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Mapping
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

        The field is described by the log, read out with the field, and is
        `aria-invalid` while the log shows an error (the page script keeps that in step
        when only the log is swapped, see `page.py`). A field a `<label for>` can't name,
        a radio group or a checkbox, is labelled by the row's label instead. Nothing
        outside a row.
        """
        attributes: list[str] = []
        log_id = self._row_part_id("log")
        if log_id is not None:
            attributes.append(f'aria-describedby="{log_id}"')
            if isinstance(self._view, FormRowView) and self._view.is_invalid:
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


class TableViewLike(ViewLike, Protocol):
    headers: list[str]
    selection_mode: SelectionMode
    rows: list[list[str]]
    selected_rows: list[int]
    selection_changed: Signal[list[int]]
    editable_columns: list[int]
    cell_edited: Signal[int, int, str]

    def emit_cell_edited(self, row: int, column: int, text: str) -> None: ...


class WebTableRenderer(WebRenderer[TableViewLike]):
    """A table, scrolling sideways on its own when wider than the page.

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
    """

    _role = "table"

    def __init__(self, view: TableViewLike) -> None:
        super().__init__(view)
        #: the cell the user is editing, by row and column
        self._editing: tuple[int, int] | None = None
        self._refresh_dispatcher.update(
            {
                "headers": self._mark_dirty,
                "selection_mode": self._mark_dirty,
                "rows": self._refresh_rows,
                "selected_rows": self._mark_dirty,
                "editable_columns": self._mark_dirty,
            }
        )

    def _refresh_rows(self, view: TableViewLike, rendered_object: str, value: Any) -> None:
        self._editing = None  # its row may have moved, or be gone
        self._mark_dirty(view, rendered_object, value)

    def to_html(self, *, oob: bool = False) -> str:
        headers = "".join(f"<th>{html.escape(header)}</th>" for header in self._view.headers)
        rows = "".join(self._row_html(index, row) for index, row in enumerate(self._view.rows))
        grid = ' role="grid" aria-multiselectable="true"' if self._is_multiple() else ""
        return (
            f"<div {self._root_attributes(oob=oob)}"
            ' class="overflow-x-auto rounded-box border border-base-300">'
            f'<table class="table table-zebra table-sm"{grid}>'
            f"<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div>"
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
        if event in ("start_edit", "edit") and self.is_enabled:
            self._edit(event, form)
            return
        # a disabled table can't be clicked: a post saying otherwise is refused
        if event != "select" or not self.is_enabled:
            super().dispatch(event, form)
        row = form.get("row", "")
        if not row.isdigit() or int(row) >= len(self._view.rows):
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

    def _edit(self, event: str, form: Mapping[str, str]) -> None:
        """Start editing a cell, or end it with the text posted."""
        # either way the table comes back: with the field, or with the cell's text
        self._mark_dirty(self._view, self.widget_id, self._view.rows)
        row, column = form.get("row", ""), form.get("column", "")
        if (
            not row.isdigit()
            or int(row) >= len(self._view.rows)
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


class WebFormLabelRenderer(WebRenderer[FormLabelRowView]):
    """The label of a form row, pointing at the row's field for clicks/screen readers."""

    _role = "form_label"

    def __init__(self, view: FormLabelRowView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"label": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> str:
        field = self._field_renderer()
        # a radio group or a checkbox is a `<div>`, which isn't labelable: its
        # `aria-labelledby` names it instead
        target = f' for="{field.widget_id}"' if field.is_labelable else ""
        return (
            f"<label {self._root_attributes(oob=oob)}{target}"
            ' class="label text-sm font-medium text-base-content"'
            f">{html.escape(self._view.label)}</label>"
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
}


def _icon(name: str) -> str:
    return (
        '<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
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
    per share; the cell hides with its view, which swaps on its own.
    """

    _role = "horizontal"

    def render(self) -> None:
        super().render()
        self._adopt(self._view.children_views)

    def to_html(self, *, oob: bool = False) -> str:
        cells = "".join(
            '<div class="min-w-0 has-[>[hidden]]:hidden"'
            # no share: as wide as its content
            f' style="flex: {f"{stretch} 1 0%" if stretch > 0 else "none"}">'
            f"{view.renderer.to_html()}</div>"
            for view, stretch in self._view.stretched_views
            if isinstance(view.renderer, WebRenderer)
        )
        align = " justify-end" if self._view.align is Align.END else ""
        return f'<div {self._root_attributes(oob=oob)} class="flex gap-6{align}">{cells}</div>'


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
            else:
                if child_view is self.router and isinstance(child_view.renderer, WebRouterRenderer):
                    toolbar = child_view.renderer.toolbar_html()
                content.append(child_view.renderer.to_html())
        # the pages' toolbar wraps to a row of its own on a narrow screen
        wrap = " flex-wrap" if toolbar else ""
        # bottom padding keeps the last row clear of the fixed status bar
        return get_page(
            self._view.title,
            # sticky: the menus stay at hand however long the form is
            f'<header class="navbar sticky top-0 z-20 min-h-14{wrap} gap-3 border-b'
            " border-base-300"
            ' bg-base-100 px-4">'
            f"{self.brand_html()}{toolbar}"
            '<nav class="ml-auto flex items-center gap-1">'
            f"{''.join(toolbars)}{''.join(menus)}</nav>"
            f"{_THEME_MENU}"
            "</header>"
            f'<main class="mx-auto {_MAIN_WIDTHS} px-4 pt-8 pb-20">'
            '<div class="card border border-base-300 bg-base-100 shadow-md">'
            '<div class="card-body gap-6 p-6">'
            f"{''.join(content)}"
            "</div></div></main>"
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
    "checkbox": WebCheckBoxRenderer,
    "combobox": WebComboboxRenderer,
    "dialog": WebDialogRenderer,
    "float_input": WebFloatInputRenderer,
    "form": WebFormRenderer,
    "form_label": WebFormLabelRenderer,
    "group_form": WebGroupFormRenderer,
    "horizontal": WebHorizontalRenderer,
    "input": WebInputRenderer,
    "label": WebLabelRenderer,
    "log": WebLogRenderer,
    "main": WebMainRenderer,
    "menu": WebMenuRenderer,
    "page": WebPageRenderer,
    "progress_bar": WebProgressBarRenderer,
    "radio_group": WebRadioGroupRenderer,
    "router": WebRouterRenderer,
    "separator": WebSeparatorRenderer,
    "status_bar": WebStatusBarRenderer,
    "table": WebTableRenderer,
    "toolbar": WebToolBarRenderer,
    "vertical": WebVerticalRenderer,
}
