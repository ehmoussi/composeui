"""The views that take text, numbers and dates."""

from __future__ import annotations

import bisect
import contextlib
import datetime
import functools
import itertools
import math
import re
from collections.abc import Callable, Iterable
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Optional,
    Protocol,
    TypeVar,
    Union,
    cast,
)

import attrs
from typing_extensions import override

from composeui.core._views.base import (
    OMIT,
    UI_TEXT,
    View,
    define_view,
    notify_renderer,
    write_view_text,
)
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.translation import (
    T,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


@define_view
class _InputView:
    # properties
    placeholder: str = attrs.field(default="", metadata={UI_TEXT: True})
    # signals
    editing_finished: SignalNoArgs = attrs.field(factory=SignalNoArgs)
    #: the user changed the text: typed it, or picked a path or a date that the field shows.
    #: Text or a value set by code emits no signal.
    text_changed: Signal[str] = attrs.field(factory=Signal[str])
    #: the user typed in the field. Text or a value set by code emits no signal.
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


#: a text editor's texts, by what they're for: its controls saving the text to a file,
#: copying it to the clipboard, and searching it, with the count of the matches, then where
#: the caret is
EDITOR_TEXTS: Mapping[str, str] = {
    "save": T("Save as"),
    "copy": T("Copy all"),
    "copied": T("Copied"),
    "search": T("Search"),
    "matches": T("{current} of {count}"),
    "no_match": T("No match"),
    "position": T("Line {line}, column {column}"),
}


class Lexer(Protocol):
    """A Pygments lexer, or any object that splits a text into tokens as one does."""

    def get_tokens_unprocessed(self, text: str) -> Iterable[tuple[int, Any, str]]:
        """Get each token of `text`: where it starts, its Pygments token type, and its text."""
        ...


#: the kinds of token that a text editor colors, by the Pygments token types they hold, the
#: most precise first: a token of none shows in the text's own color
_TOKEN_KINDS = (
    ("Comment", "comment"),
    ("Literal.String", "string"),
    ("Literal.Number", "number"),
    ("Keyword", "keyword"),
    ("Name.Builtin", "builtin"),
    ("Name.Function", "function"),
    ("Name.Class", "function"),
    ("Name.Decorator", "function"),
    ("Operator", "operator"),
)
#: the color of each kind of token on Qt and Textual, on a light background then a dark one
HIGHLIGHT_COLORS: Mapping[str, tuple[str, str]] = {
    "comment": ("#6b7280", "#9ca3af"),
    "string": ("#15803d", "#86efac"),
    "number": ("#b45309", "#fcd34d"),
    "keyword": ("#4338ca", "#a5b4fc"),
    "builtin": ("#9333ea", "#d8b4fe"),
    "function": ("#0369a1", "#7dd3fc"),
    "operator": ("#475569", "#cbd5e1"),
}
#: the longest text, in characters, whose syntax a text editor colors: each edit colors the
#: whole text again, on the web under the session's lock, and Pygments takes about 70 ms for
#: 50 000 characters of Python; a longer text shows plain
MAX_HIGHLIGHT_SIZE = 50_000


@functools.cache
def _named_lexer(name: str) -> Lexer:
    """Get Pygments' lexer of the language `name`, e.g. "python"; raise if it has none."""
    from pygments.lexers import get_lexer_by_name  # noqa: PLC0415 (Pygments only to color)

    return cast("Lexer", get_lexer_by_name(name))


@functools.lru_cache(maxsize=1)
def _token_kinds() -> tuple[tuple[Any, str], ...]:
    from pygments.token import Token  # noqa: PLC0415 (Pygments only to color)

    # e.g. "Literal.String" is Token.Literal.String
    return tuple(
        (functools.reduce(getattr, name.split("."), Token), kind) for name, kind in _TOKEN_KINDS
    )


def highlight_lines(
    text: str, language: Union[str, Lexer, None]
) -> list[list[tuple[int, int, str]]]:
    """Get the colored parts of each line of `text` in `language`: start, end and kind.

    A kind is one of `HIGHLIGHT_COLORS`. Without a language, or past `MAX_HIGHLIGHT_SIZE`, no
    line has any.
    """
    lines = text.split("\n")
    parts: list[list[tuple[int, int, str]]] = [[] for _ in lines]
    if language is None or len(text) > MAX_HIGHLIGHT_SIZE:
        return parts
    lexer = _named_lexer(language) if isinstance(language, str) else language
    starts = list(itertools.accumulate((len(line) + 1 for line in lines[:-1]), initial=0))
    kinds = _token_kinds()
    for start, token, value in lexer.get_tokens_unprocessed(text):
        kind = next((kind for token_type, kind in kinds if token in token_type), None)
        if kind is None:
            continue
        position, end = start, start + len(value)
        while position < end:  # a token over several lines, as a docstring, colors each
            line = bisect.bisect_right(starts, position) - 1
            line_end = starts[line] + len(lines[line])
            part = (position - starts[line], min(end, line_end) - starts[line], kind)
            line_parts = parts[line]
            if line_parts and line_parts[-1][1:] == (part[0], kind):  # the same kind goes on
                line_parts[-1] = (line_parts[-1][0], part[1], kind)
            elif part[0] < part[1]:
                line_parts.append(part)
            position = line_end + 1
    return parts


def _check_language(
    _view: TextEditorView, _attribute: attrs.Attribute[Any], value: Union[str, Lexer, None]
) -> None:
    if isinstance(value, str):
        _named_lexer(value)  # an unknown name, or no Pygments, fails now, not as it shows


@define_view
class TextEditorView(TextAreaMixin, View):
    """A box where the user edits a file's text, for example a solver's input file.

    The text shows in a fixed-width font, its lines never wrapped and numbered down the
    left, under a bar with `export_filename` and the caret's line and column. Tab indents
    by four spaces. On Qt and Textual, Escape moves the focus out; on the web, Escape then
    Tab does. The user saves the text to a file, named `export_filename` at first, or
    copies it all, and searches it, as `find_in_lines` finds it. On Qt and Textual, "Save as"
    calls `export_text`. On the web, the browser downloads the text that the field shows, and
    the app isn't told. With a `language`, Pygments colors the text's syntax, up to
    50 000 characters.

    Its text is study data, as a `TextAreaView`'s: saved, loaded and reset with the study.
    To edit a file that the user uploads, read it into `text`. To give the file to a
    program, write `text` to it.
    """

    _renderer_key = "text_editor"

    #: the texts of its controls, by what they're for (see `EDITOR_TEXTS`)
    texts: dict[str, str] = attrs.field(
        factory=lambda: dict(EDITOR_TEXTS), metadata={UI_TEXT: True}
    )
    #: the name offered for the file the text is saved to
    export_filename: str = attrs.field(default="text.txt", metadata={OMIT: True})
    #: the language whose syntax colors the text: a Pygments lexer's name, such as "python",
    #: or a lexer, such as the app's own; None for plain text
    language: Union[str, Lexer, None] = attrs.field(
        default=None, validator=_check_language, metadata={OMIT: True}
    )

    def export_text(self, path: Path) -> None:
        """Write the text to the file `path`, in UTF-8, and say how it went.

        Outside a main view, a failure raises `OSError` instead.
        """
        write_view_text(self, path, self.text, self.tr("Saved {name}."))


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


TParsed = TypeVar("TParsed")


@define_view
class ParsedInputMixin(InputMixin, Generic[TParsed]):
    """The fields of a field whose text the app reads, e.g. "4 GB": `parse` and `format`.

    The view holds the `text` as typed, and `value` reads it with `parse` at each read: None
    while the field is empty, or while `parse` raises `ValueError`. The text that `format`
    writes must be one that `parse` reads back.
    """

    #: reads a non-empty text into a value, raising `ValueError` for text it can't read
    parse: Callable[[str], TParsed] = attrs.field(
        on_setattr=attrs.setters.frozen, repr=False, metadata={OMIT: True}
    )
    #: writes a value as the field shows it once editing ends, and when the app sets it
    format: Callable[[TParsed], str] = attrs.field(
        on_setattr=attrs.setters.frozen, repr=False, metadata={OMIT: True}
    )
    #: the value the field starts with, the same as setting `value` once it is built
    _initial_value: Optional[TParsed] = attrs.field(
        default=None, alias="value", repr=False, metadata={OMIT: True}
    )

    def _set_up_parsed_input(self) -> None:
        """Show the initial value, and write the text again once editing ends.

        Called by the views' `__attrs_post_init__`: a form row has `View`'s before the mixin.
        """
        if self._initial_value is not None:
            self.value = self._initial_value
        # first, so the callbacks connected after it read the text shown
        self.editing_finished.connect(self._show_value)

    @property
    def value(self) -> Optional[TParsed]:
        """Get the value of `text`: None while it is empty, or while `parse` can't read it."""
        if self.text.strip() == "":
            return None
        try:
            return self.parse(self.text)
        except ValueError:
            return None

    @value.setter
    def value(self, value: Optional[TParsed]) -> None:
        self.text = "" if value is None else self.format(value)

    def _show_value(self) -> None:
        """Write the text again as `format` does, unless `parse` can't read it."""
        value = self.value
        if value is not None:
            self.text = self.format(value)


@define_view
class ParsedInputView(ParsedInputMixin[TParsed], View):
    """A field whose text the app reads, e.g. a memory typed as "4 GB" or "4096 MB".

    `value` is what `parse` reads from the text, and `format` writes it back once editing
    ends. Text that `parse` can't read stays, so the user sees what to fix: its `value` is
    None, as for an empty field, and `text` tells them apart.
    """

    _renderer_key = "input"

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._set_up_parsed_input()


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
