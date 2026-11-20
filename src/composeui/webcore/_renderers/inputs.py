"""The web renderers of fields: text, numbers, dates and date ranges."""

from __future__ import annotations

import contextlib
import datetime
import json
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar, cast

from markupsafe import Markup
from typing_extensions import Protocol

from composeui.core._views.controls import RANGE_DASH
from composeui.core._views.inputs import date_hint
from composeui.core.renderer import ViewLike
from composeui.core.view import DateRangeInputMixin, parse_date
from composeui.webcore.changes import _DIRTY
from composeui.webcore.webrenderer import WebRenderer, _icon

if TYPE_CHECKING:
    from collections.abc import Mapping

    from composeui.core.signal import Signal, SignalNoArgs


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


class WebTextAreaRenderer(WebInputRenderer):
    """A `<textarea>`, posting its edits as `WebInputRenderer` does.

    Its `change`, when it loses the focus after a change, emits `editing_finished`: Enter
    starts a new line, and posts nothing.
    """

    _role = "text_area"

    def to_html(self, *, oob: bool = False) -> Markup:
        disabled = "" if self.is_enabled else " disabled"
        return Markup(
            "<textarea {root_attributes}{row_attributes}"
            ' class="textarea w-full" rows="4"'
            ' name="value" placeholder="{placeholder}"'
            ' hx-post="/widget/{widget_id}"'
            ' hx-trigger="input changed delay:300ms, change"'
            ' data-post-event hx-swap="none" hx-sync="this:queue all"'
            ' autocomplete="off"'
            # the parser drops a new line just after the tag: this one, not the text's
            "{disabled}>\n{text}</textarea>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            placeholder=self._view.placeholder,
            widget_id=self.widget_id,
            disabled=disabled,
            text=self._text(),
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a form's encoding ends the lines with CRLF; the view's text with LF, as typed
        if "value" in form:
            form = {**form, "value": form["value"].replace("\r\n", "\n")}
        super().dispatch(event, form)


class _NumberFieldViewLike(TextFieldViewLike, Protocol):
    value: Any


TNumberField = TypeVar("TNumberField", bound=_NumberFieldViewLike)


class _WebNumberFieldRenderer(_WebTextFieldRenderer[TNumberField]):
    """A text field holding a number, parsed by `_parse`.

    Not `type="number"`: while typing e.g. "-5" its value reads "" for the transient
    "-", indistinguishable from a cleared field. A text field posts the raw text and
    unparsable text is ignored, the same as the Qt/Textual inputs. Like Textual,
    `minimum`/`maximum` (and `decimals`) are tracked on the view but not enforced on input.

    Leaving the field (`change`) with unparsable text puts the value back. Qt never
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


class _DateTextsLike(Protocol):
    minimum: datetime.date | None
    maximum: datetime.date | None
    date_format: str
    pick_text: str
    previous_month_text: str
    next_month_text: str

    def shown_text(self, value: datetime.date | None) -> str: ...


class _DateField(NamedTuple):
    """A date field of a renderer: its date and the text of its posts."""

    #: what its elements' ids start with
    field_id: str
    value: datetime.date | None
    placeholder: str
    #: added to its posts, e.g. which end of a range it is
    vals: Mapping[str, str]


def _date_field_html(
    view: _DateTextsLike,
    field: _DateField,
    owner: WebRenderer[Any],
    root_attributes: Markup,
    row_attributes: Markup,
) -> Markup:
    """Render a date field: its text, then its calendar button and popover.

    It posts to `owner`, the renderer holding it (see `WebDateInputRenderer`).
    """
    field_id, value, placeholder, vals = field
    widget_id = owner.widget_id
    disabled = "" if owner.is_enabled else " disabled"
    pick = view.pick_text
    limits = Markup("").join(
        Markup(' {}="{}"').format(name, limit.isoformat())
        for name, limit in (("min", view.minimum), ("max", view.maximum))
        if limit is not None
    )
    picked = "" if value is None else value.isoformat()
    calendar_id = f"{field_id}-calendar"
    field_vals = Markup(" hx-vals='{}'").format(json.dumps(dict(vals))) if vals else Markup()
    return (
        # daisyUI's field around both, its colors, focus ring and invalid border theirs
        Markup(
            '<div {root_attributes} class="input relative w-full pe-1">'
            '<input id="{field_id}-field"{row_attributes}'
            ' class="min-w-0 grow" type="text" name="value"'
            ' value="{shown_text}"'
            ' placeholder="{date_hint}"'
            ' hx-post="/widget/{widget_id}" hx-trigger="input changed delay:300ms, change"'
            '{field_vals} data-post-event hx-swap="none" hx-sync="this:queue all"'
            ' autocomplete="off"{disabled}>'
            '<button id="{field_id}-pick" type="button"'
            ' class="btn btn-ghost btn-sm btn-square"'
            ' aria-label="{pick}" title="{pick}" popovertarget="{calendar_id}"'
            ' style="anchor-name: --{field_id}"{disabled}>'
            "{calendar_icon}</button>"
            # in the top layer, under the button: Escape or a click beside it closes it
            '<div id="{calendar_id}" popover data-date-button="{field_id}-pick"'
            ' class="dropdown dropdown-end rounded-box bg-base-100 shadow-lg"'
            ' style="position-anchor: --{field_id}">'
            '<calendar-date class="cally" value="{picked}"{limits} data-date-calendar'
            ' hx-post="/widget/{widget_id}" hx-trigger="change"'
            " hx-vals='{pick_vals}' data-post-picked hx-swap=\"none\">"
            '<span slot="previous" aria-label="{previous_month_text}">'
            "{chevron_icon}</span>"
            '<span slot="next" aria-label="{next_month_text}">'
            "{chevron_icon2}</span>"
            "<calendar-month></calendar-month></calendar-date></div></div>"
        ).format(
            root_attributes=root_attributes,
            field_id=field_id,
            widget_id=widget_id,
            row_attributes=row_attributes,
            shown_text=view.shown_text(value),
            date_hint=date_hint(placeholder, view.date_format),
            field_vals=field_vals,
            disabled=disabled,
            pick=pick,
            calendar_id=calendar_id,
            calendar_icon=_icon("calendar"),
            picked=picked,
            limits=limits,
            pick_vals=json.dumps({"event": "pick", **vals}),
            previous_month_text=view.previous_month_text,
            chevron_icon=_icon("chevron", "size-4 rotate-90"),
            next_month_text=view.next_month_text,
            chevron_icon2=_icon("chevron", "size-4 -rotate-90"),
        )
    )


class WebDateInputRenderer(WebRenderer[DateInputViewLike]):
    """A text field typing the date as the view's `date_format` says, then a calendar button.

    The root is daisyUI's field holding both. So the button takes the field's colors in
    every theme, and the field's border marks the row invalid (see `css/app.css`). A row's
    label names the text field with `aria-labelledby`, as a `<div>` can't be labelled. The
    text posts like a number's (see `_WebNumberFieldRenderer`): never swapped back while
    typed in, text that isn't a date ignored. Left (`change`), it is swapped back showing
    the date as the format writes it, or the date back for text that isn't one.

    The button opens a popover holding Cally's calendar (`<calendar-date>`, which daisyUI
    styles in the theme's colors), its months and days in the page's language (see
    `page.js`). The date picked posts as its change (`pick`), in ISO 8601. Like the number
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
        return _date_field_html(
            view,
            _DateField(self.widget_id, view.value, view.placeholder, {}),
            self,
            self._root_attributes(oob=oob),
            self._row_attributes(),
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        if not self.is_enabled or event not in ("input", "change", "pick"):
            super().dispatch(event, form)
        if event == "pick":
            try:
                picked = datetime.date.fromisoformat(form.get("picked", ""))
            except ValueError:  # a date input posts a date, or nothing
                picked = None
            if picked is not None and self._edit(picked):
                # a picked date changes the text, but the user didn't type it
                self._view.text_changed.emit(self._view.shown_text(picked))
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

    def _edit(self, value: datetime.date | None) -> bool:
        """Give the view the user's date; get whether it changed."""
        if value == self._view.value:
            return False
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)
        return True

    def _posted_text(self) -> str:
        if self._last_posted_text is not None:
            return self._last_posted_text
        return self._view.shown_text(self._view.value)

    def _refresh_value(self, view: DateInputViewLike, rendered_object: str, value: Any) -> None:
        self._last_posted_text = None  # the server's date wins over what was typed
        self._mark_dirty(view, rendered_object, value)


class DateRangeInputViewLike(ViewLike, Protocol):
    value: tuple[datetime.date | None, datetime.date | None]
    minimum: datetime.date | None
    maximum: datetime.date | None
    date_format: str
    start_text: str
    end_text: str
    pick_text: str
    previous_month_text: str
    next_month_text: str
    value_changed: Signal[tuple[datetime.date | None, datetime.date | None]]

    def shown_text(self, value: datetime.date | None) -> str: ...


#: the parts of a date range, by the index of their end
_DATE_RANGE_PARTS = ("start", "end")
#: the attributes of a date range that swap it whole
_DATE_RANGE_ATTRIBUTES = (
    "value",
    "minimum",
    "maximum",
    "date_format",
    "start_text",
    "end_text",
    "pick_text",
    "previous_month_text",
    "next_month_text",
)


class WebDateRangeInputRenderer(WebRenderer[DateRangeInputViewLike]):
    """Two date fields, the start and the end, each as `WebDateInputRenderer`'s, in a group.

    Each posts with its end (``"end"``: 0 or 1). The date typed or picked for an end that
    passes the other moves the other to it (`DateRangeInputMixin.with_end`), which then
    swaps alone: never the field typed in, unless left or picked in. A change of the app's
    swaps the whole. The row's label names the group; each field, its end's text.
    """

    _role = "date_range_input"
    is_labelable = False

    def __init__(self, view: DateRangeInputViewLike) -> None:
        super().__init__(view)
        #: the text each end last posted, while it stays what its field shows
        self._last_posted_texts: list[str | None] = [None, None]
        #: the ends to swap, unless the whole is
        self._dirty_parts: set[int] = set()
        self._is_whole_dirty = False
        self._refresh_dispatcher.update(dict.fromkeys(_DATE_RANGE_ATTRIBUTES, self._mark_dirty))
        # the calendar names them, in the page's language (`Intl`'s names)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("month_names", "day_names"), lambda _view, _rendered_object, _value: None
            )
        )

    def _mark_dirty(self, view: DateRangeInputViewLike, rendered_object: str, value: Any) -> None:
        self._is_whole_dirty = True
        self._last_posted_texts = [None, None]  # the server's dates win over what was typed
        super()._mark_dirty(view, rendered_object, value)

    def _mark_end(self, index: int) -> None:
        """Swap the field of the end `index`, as the view's date: only an event marks one."""
        self._last_posted_texts[index] = None
        self._dirty_parts.add(index)
        cast("dict[str, WebRenderer[Any]]", _DIRTY.get())[self.widget_id] = self

    def to_html(self, *, oob: bool = False) -> Markup:
        parts, self._dirty_parts = self._dirty_parts, set()
        is_whole, self._is_whole_dirty = self._is_whole_dirty or not oob or not parts, False
        if not is_whole:
            return Markup("").join(self._end_html(index, oob=True) for index in sorted(parts))
        return Markup(
            '<div {root_attributes}{row_attributes} role="group"'
            ' class="flex items-center gap-2">{start}<span aria-hidden="true">{dash}</span>'
            "{end}</div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            row_attributes=self._row_attributes(),
            start=self._end_html(0, oob=False),
            dash=RANGE_DASH.strip(),
            end=self._end_html(1, oob=False),
        )

    def _end_html(self, index: int, *, oob: bool) -> Markup:
        view = self._view
        field_id = f"{self.widget_id}-{_DATE_RANGE_PARTS[index]}"
        text = (view.start_text, view.end_text)[index]
        return _date_field_html(
            view,
            _DateField(field_id, view.value[index], text, {"end": str(index)}),
            self,
            Markup('id="{}"{}').format(
                field_id, Markup(' hx-swap-oob="true"') if oob else Markup()
            ),
            Markup(' aria-label="{}"').format(text),
        )

    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        posted_end = form.get("end", "")
        if event not in ("input", "change", "pick") or posted_end not in ("0", "1"):
            super().dispatch(event, form)
        index = int(posted_end)
        if event == "pick":
            with contextlib.suppress(ValueError):  # a date input posts a date, or nothing
                self._edit(index, datetime.date.fromisoformat(form.get("picked", "")))
            # the field shows it: swapped back, as the button had the focus, not the field
            self._mark_end(index)
            return
        # `change` carries the text too: it can overtake a still-debounced `input`
        text = form.get("value", "")
        if text != self._posted_text(index):
            self._last_posted_texts[index] = text
            if text.strip() == "":
                self._edit(index, None)
            else:
                with contextlib.suppress(ValueError):  # not a date yet, e.g. halfway
                    self._edit(index, parse_date(text, self._view.date_format))
        if event == "change":
            # left: the date as the format writes it, or back for text that isn't one
            self._mark_end(index)

    def _edit(self, index: int, date: datetime.date | None) -> None:
        view = self._view
        value = DateRangeInputMixin.with_end(view.value, index, date)
        if value == view.value:
            return
        other = 1 - index
        followed = value[other] != view.value[other]
        with self.stop_refresh():
            view.value = value
        if followed:
            self._mark_end(other)
        view.value_changed.emit(value)

    def _posted_text(self, index: int) -> str:
        posted = self._last_posted_texts[index]
        return self._view.shown_text(self._view.value[index]) if posted is None else posted
