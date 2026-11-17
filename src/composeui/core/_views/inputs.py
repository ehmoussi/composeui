"""The views that take text, numbers and dates."""

from __future__ import annotations

import contextlib
import datetime
import math
import re
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    cast,
)

import attrs

from composeui.core._views.base import UI_TEXT, View, define_view, notify_renderer
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.translation import (
    T,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@define_view
class _InputView:
    # properties
    placeholder: str = attrs.field(default="", metadata={UI_TEXT: True})
    # signals
    editing_finished: SignalNoArgs = attrs.field(factory=SignalNoArgs)
    text_changed: Signal[str] = attrs.field(factory=Signal[str])
    text_edited: Signal[str] = attrs.field(factory=Signal[str])


@define_view
class InputMixin(_InputView):
    """The fields of a field for one line of text: its `text` and its signals."""

    # properties
    text: str = attrs.field(default="")


@define_view
class InputView(InputMixin, View):
    """A field where the user types one line of text, for example a name."""

    _renderer_key = "input"


@define_view
class TextAreaMixin(_InputView):
    """The fields of a field for several lines of text: its `text` and its signals."""

    # properties
    text: str = attrs.field(default="")


@define_view
class TextAreaView(TextAreaMixin, View):
    """A field where the user types several lines of text, for example a comment.

    `editing_finished` is emitted when the field loses the focus after a change: Enter
    starts a new line.
    """

    _renderer_key = "text_area"


@define_view
class FloatInputMixin(_InputView):
    """The fields of a field for a decimal number: its `value`, range and decimals."""

    # properties
    value: Optional[float] = attrs.field(default=None)
    minimum: Optional[float] = attrs.field(default=None)
    maximum: Optional[float] = attrs.field(default=None)
    #: the most decimals the field shows (and, on Qt, takes); None: as many as `str` writes
    decimals: Optional[int] = attrs.field(default=None)

    @staticmethod
    def shown_text(value: Optional[float], decimals: Optional[int]) -> str:
        """Show `value` with at most `decimals` decimals, "" for no value.

        The value is rounded, and trailing zeros are left out: with 0 decimals, 36.0 is
        "36", and with 2, 3.14159 is "3.14" and 2.5 is "2.5". Without `decimals`, the
        value shows as `str` writes it, e.g. "36.0". Takes `decimals`, as a renderer
        refreshes it before the view holds it.
        """
        if value is None:
            return ""
        if decimals is None or not math.isfinite(value):
            return str(value)
        text = f"{value:.{decimals}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        # a negative value rounded to 0 isn't "-0"
        return "0" if text == "-0" else text


@define_view
class FloatInputView(FloatInputMixin, View):
    """A field where the user types a decimal number, for example a length.

    `value` is None while the field is empty.
    """

    _renderer_key = "float_input"


@define_view
class IntInputMixin(_InputView):
    """The fields of a field for a whole number: its `value` and its range."""

    # properties
    value: Optional[int] = attrs.field(default=None)
    minimum: Optional[int] = attrs.field(default=None)
    maximum: Optional[int] = attrs.field(default=None)


@define_view
class IntInputView(IntInputMixin, View):
    """A whole number, e.g. an hour of the day; a spin box where the toolkit has one."""

    _renderer_key = "int_input"


#: how a date is typed and shown when nothing gives it a format: ISO 8601's
ISO_DATE_FORMAT = "yyyy-MM-dd"
#: a date format's parts: its day, month and year (see `DateInputMixin.date_format`)
_DATE_PARTS = {"dd": "day", "MM": "month", "yyyy": "year"}
_DATE_PART_PATTERN = re.compile("|".join(_DATE_PARTS))
#: splits a date format into its parts and the separators between them
_DATE_PART_SPLIT = re.compile(f"({_DATE_PART_PATTERN.pattern})")


def is_date_format(date_format: str) -> bool:
    """Tell whether `date_format` has a day, a month and a year, each once."""
    parts = _DATE_PART_PATTERN.findall(date_format)
    return sorted(parts) == sorted(_DATE_PARTS)


def format_date(value: datetime.date, date_format: str) -> str:
    """Show `value` as `date_format` says, e.g. "18/10/2026" for "dd/MM/yyyy".

    A format lacking a part, e.g. a catalog's mistake, shows the date as ISO 8601 does.
    """
    if not is_date_format(date_format):
        date_format = ISO_DATE_FORMAT
    texts = {"dd": f"{value.day:02d}", "MM": f"{value.month:02d}", "yyyy": f"{value.year:04d}"}
    return _DATE_PART_PATTERN.sub(lambda part: texts[part.group()], date_format)


def date_hint(placeholder: str, date_format: str) -> str:
    """Get what an empty date field shows: `placeholder`, else the format, as "mm/dd/yyyy"."""
    return placeholder or date_format.lower()


def parse_date(text: str, date_format: str) -> datetime.date:
    """Read a date typed as `date_format` says, or as ISO 8601 (2026-10-18) whatever it is.

    The day and the month may have a single digit ("1/2/2026"), and a separator ending
    the format may be left out ("18.10.2026" for "dd.MM.yyyy."). Raises `ValueError`
    for anything else, or a day the month doesn't have.
    """
    text = text.strip()
    for candidate in dict.fromkeys([date_format, ISO_DATE_FORMAT]):
        if not is_date_format(candidate):
            continue
        pieces = [piece for piece in _DATE_PART_SPLIT.split(candidate) if piece != ""]
        pattern = ""
        for index, piece in enumerate(pieces):
            if piece in _DATE_PARTS:
                digits = r"\d{4}" if piece == "yyyy" else r"\d{1,2}"
                pattern += f"(?P<{_DATE_PARTS[piece]}>{digits})"
            elif index == len(pieces) - 1:
                # a separator ending the format, e.g. Hungarian's dot, may be left out
                pattern += rf"(?:\s*{re.escape(piece.strip())})?"
            else:
                pattern += rf"\s*{re.escape(piece.strip())}\s*"
        matched = re.fullmatch(pattern, text)
        if matched is None:
            continue
        with contextlib.suppress(ValueError):  # a day the month doesn't have
            return datetime.date(*(int(matched[part]) for part in ("year", "month", "day")))
    # the same message for a day the month doesn't have, whatever Python's own says
    msg = f"{text!r} isn't a date as {date_format}"
    raise ValueError(msg)


@define_view
class _DateTextsMixin:
    """The text of a date field: its format, and the names its calendar shows."""

    #: how the date is typed and shown: its day ``dd``, month ``MM`` and year ``yyyy`` between
    #: separators; a text the catalogs translate, so the main view's language's
    date_format: str = attrs.field(default=T("MM/dd/yyyy"), metadata={UI_TEXT: True})
    #: the calendar's month names, January first, and its days' short names, Monday first
    month_names: list[str] = attrs.field(
        factory=lambda: [
            T("January"),
            T("February"),
            T("March"),
            T("April"),
            T("May"),
            T("June"),
            T("July"),
            T("August"),
            T("September"),
            T("October"),
            T("November"),
            T("December"),
        ],
        metadata={UI_TEXT: True},
    )
    day_names: list[str] = attrs.field(
        factory=lambda: [T("Mo"), T("Tu"), T("We"), T("Th"), T("Fr"), T("Sa"), T("Su")],
        metadata={UI_TEXT: True},
    )
    #: the names of the button opening the calendar, and of its month buttons, as a
    #: screen reader reads them out
    pick_text: str = attrs.field(default=T("Pick a date"), metadata={UI_TEXT: True})
    previous_month_text: str = attrs.field(default=T("Previous month"), metadata={UI_TEXT: True})
    next_month_text: str = attrs.field(default=T("Next month"), metadata={UI_TEXT: True})

    def shown_text(self, value: Optional[datetime.date]) -> str:
        """Show `value` as `date_format` says, "" for no date."""
        return "" if value is None else format_date(value, self.date_format)


@define_view
class DateInputMixin(_InputView, _DateTextsMixin):
    """A date, typed as `date_format` says or picked from a calendar.

    Not every backend refuses a date typed out of `minimum`/`maximum`: Textual and the web
    mark it or keep it. So validate the date. The calendar offers only the dates in range.
    """

    value: Optional[datetime.date] = attrs.field(default=None)
    minimum: Optional[datetime.date] = attrs.field(default=None)
    maximum: Optional[datetime.date] = attrs.field(default=None)
    #: the user typed or picked a new date (None once the field is emptied); not
    #: emitted when `value` is set in code
    value_changed: Signal[Optional[datetime.date]] = attrs.Factory(Signal[Optional[datetime.date]])


@define_view
class DateInputView(DateInputMixin, View):
    """A date, e.g. a booking's first day: typed in the main view's language's format."""

    _renderer_key = "date_input"


#: a range's ends: its low and its high one, or its first and its last day
_RANGE_ENDS = 2


#: a range of dates: its first and its last day, each None for no limit on that side
DateRange = tuple[Optional[datetime.date], Optional[datetime.date]]


def _date_pair(pair: Iterable[Optional[datetime.date]]) -> DateRange:
    """Get a date range's ends as a tuple, e.g. from a list; its validator checks them."""
    return cast("DateRange", tuple(pair))


def _check_date_range(instance: Any, attribute: attrs.Attribute[Any], pair: DateRange) -> None:
    """Reject a date range that isn't two ends, or that starts after it ends."""
    if len(pair) != _RANGE_ENDS:
        msg = f"Cannot set {type(instance).__name__}.{attribute.name} to {pair}: not two ends."
        raise ValueError(msg)
    start, end = pair
    if start is not None and end is not None and start > end:
        msg = (
            f"Cannot set {type(instance).__name__}.{attribute.name} to {pair}: it starts after "
            "it ends."
        )
        raise ValueError(msg)


@define_view
class DateRangeInputMixin(_DateTextsMixin):
    """A range of dates, each end typed as `date_format` says or picked from a calendar.

    Either end can be empty (None), for a range open on that side. An end that the user
    sets past the other moves the other to it. As for a date field, not every backend
    refuses a date out of `minimum`/`maximum`: validate the range.
    """

    #: the first and the last day, each None for no limit; the first not after the last
    value: DateRange = attrs.field(
        default=(None, None),
        converter=_date_pair,
        validator=[_check_date_range],
        on_setattr=[attrs.setters.convert, attrs.setters.validate, notify_renderer],
    )
    minimum: Optional[datetime.date] = attrs.field(default=None)
    maximum: Optional[datetime.date] = attrs.field(default=None)
    #: the names of the two fields, shown in them while empty
    start_text: str = attrs.field(default=T("Start"), metadata={UI_TEXT: True})
    end_text: str = attrs.field(default=T("End"), metadata={UI_TEXT: True})
    #: the user typed or picked a new date for an end; not emitted when `value` is set in code
    value_changed: Signal[DateRange] = attrs.Factory(Signal[DateRange])

    @staticmethod
    def with_end(value: DateRange, index: int, date: Optional[datetime.date]) -> DateRange:
        """Get `value` with its end `index` (0 the start, 1 the end) set to `date`.

        Set past the other end, the other moves to it, as the user means the date set.
        """
        ends = [*value]
        ends[index] = date
        start, end = ends
        if start is not None and end is not None and start > end:
            ends[1 - index] = date
        return ends[0], ends[1]


@define_view
class DateRangeInputView(DateRangeInputMixin, View):
    """A range of dates, e.g. the days of the trips to show, typed or picked in a calendar."""

    _renderer_key = "date_range_input"
