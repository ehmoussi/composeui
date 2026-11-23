"""The table views, their filters and cells, and the sources of a source table."""

from __future__ import annotations

import array
import contextlib
import csv
import datetime
import decimal
import enum
import io
import operator
import os
import re
import weakref
from collections import Counter, OrderedDict
from collections.abc import Callable, Hashable, Mapping, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    NamedTuple,
    Optional,
    Protocol,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
)

import attrs
from typing_extensions import override

from composeui.core._views.base import (
    _BAD_STATE_ERRORS,
    _COLOR_PATTERN,
    CONVERTER,
    OMIT,
    UI_TEXT,
    EditRefusedError,
    LogType,
    View,
    _editing_cell,
    define_view,
    emit_if_made,
    notify_renderer,
)
from composeui.core._views.choices import NodeMark
from composeui.core._views.files import _write_csv, path_of_text, text_of_path
from composeui.core.reactivity import (
    set_value,
)
from composeui.core.renderer import MainRenderer, Renderer, RendererContainer
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.translation import (
    T,
    Translate,
    translate_again,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from attrs import AttrsInstance

    from composeui.core.jobs import Job, Jobs


class SelectionMode(enum.Enum):
    """How many of a table's rows the user can select."""

    #: one row at most: selecting another row replaces it
    SINGLE = enum.auto()
    #: any number of rows: selecting a row adds it, and selecting it again removes it
    MULTIPLE = enum.auto()


def replace_cell(rows: list[list[str]], row: int, column: int, text: str) -> list[list[str]]:
    """Return `rows` with `text` in a cell, as new lists: a row short of it is filled with ""."""
    cells = [*rows[row], *[""] * (column + 1 - len(rows[row]))]
    cells[column] = text
    return [*rows[:row], cells, *rows[row + 1 :]]


def _parse_bool(text: Any, _type: type) -> bool:
    if isinstance(text, str) and text.lower() in ("true", "false"):
        return text.lower() == "true"
    msg = f"{text!r} isn't a boolean"
    raise ValueError(msg)


#: parses a cell's text into a record's field; strict about booleans, which
#: ``bool("False")`` would make true
#: the longest duration read: the frames' libraries refuse a longer one in a filter
_MAX_DURATION = datetime.timedelta(microseconds=2**63 - 1)
_DURATION_TEXT = re.compile(
    r"(-?)(?:([0-9]+)d)?\s*(?:([0-9]+)h)?\s*(?:([0-9]+)m)?\s*(?:([0-9]+(?:\.[0-9]*)?)s)?"
)


def _duration_text(duration: datetime.timedelta) -> str:
    """Write a duration in full with its units, such as ``1d 2h 30m`` or ``-1.5s``."""
    magnitude = abs(duration)
    hours, rest = divmod(magnitude.seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    fraction = f"{magnitude.microseconds:06d}".rstrip("0")
    second_text = f"{seconds}.{fraction}" if fraction != "" else str(seconds)
    parts = [
        f"{value}{unit}"
        for value, unit in ((magnitude.days, "d"), (hours, "h"), (minutes, "m"))
        if value != 0
    ]
    if second_text != "0" or len(parts) == 0:
        parts.append(f"{second_text}s")
    return f"{'-' if duration < datetime.timedelta(0) else ''}{' '.join(parts)}"


def _parse_duration(value: Any, _type: Any = None) -> datetime.timedelta:
    """Read a duration as a cell shows it (``1d 2h 30m``), or a number of seconds."""
    text = str(value).strip()
    match = _DURATION_TEXT.fullmatch(text)
    try:
        if match is None or text in ("", "-"):
            duration = datetime.timedelta(seconds=float(text))
        else:
            sign, days, hours, minutes, seconds = match.groups()
            duration = datetime.timedelta(
                days=int(days or 0),
                hours=int(hours or 0),
                minutes=int(minutes or 0),
                seconds=float(seconds or 0),
            )
            duration = -duration if sign == "-" else duration
    except OverflowError as error:
        raise ValueError(text) from error
    if abs(duration) > _MAX_DURATION:
        raise ValueError(text)
    return duration


CONVERTER.register_unstructure_hook(datetime.timedelta, _duration_text)
CONVERTER.register_structure_hook(datetime.timedelta, _parse_duration)
_CELL_CONVERTER = CONVERTER.copy()
_CELL_CONVERTER.register_structure_hook(bool, _parse_bool)


class FilterProblem(enum.Enum):
    """Why a filter's text doesn't parse (see `parse_filter`)."""

    #: nothing typed
    EMPTY = enum.auto()
    #: not a number, for a number column
    NOT_A_NUMBER = enum.auto()
    #: not a date, for a date column
    NOT_A_DATE = enum.auto()
    #: neither true nor false, for a boolean column
    NOT_A_BOOLEAN = enum.auto()
    #: a range whose start is after its end
    REVERSED_RANGE = enum.auto()
    #: not a valid regular expression, for a text column's ``/pattern/``
    NOT_A_PATTERN = enum.auto()
    #: a ``/pattern/`` while ``COMPOSEUI_FILTER_PATTERNS`` turns regular expressions off
    PATTERNS_OFF = enum.auto()


class FilterError(ValueError):
    """A filter's text that doesn't parse: `problem` says why (see `TableMixin.filter_error`)."""

    def __init__(self, problem: FilterProblem, text: str) -> None:
        super().__init__(f"{text!r}: {problem.name.lower().replace('_', ' ')}")
        self.problem = problem
        self.text = text


class FilterOperator(enum.Enum):
    """How a filter compares a cell with its value."""

    CONTAINS = "contains"
    NOT_CONTAINS = "!"
    TEXT_EQUAL = "=text"
    TEXT_NOT_EQUAL = "!=text"
    STARTS_WITH = "start*"
    ENDS_WITH = "*end"
    MATCHES = "/regex/"
    EMPTY = "empty"
    EQUAL = "="
    NOT_EQUAL = "!="
    LESS = "<"
    LESS_OR_EQUAL = "<="
    GREATER = ">"
    GREATER_OR_EQUAL = ">="
    RANGE = ".."


#: the comparisons a filter's text starts with, the longer before their prefixes
_COMPARISONS = (
    FilterOperator.GREATER_OR_EQUAL,
    FilterOperator.LESS_OR_EQUAL,
    FilterOperator.NOT_EQUAL,
    FilterOperator.GREATER,
    FilterOperator.LESS,
    FilterOperator.EQUAL,
)


#: each comparison, as a function of a cell's value and the filter's
_COMPARE: Mapping[FilterOperator, Callable[[Any, Any], Any]] = {
    FilterOperator.EQUAL: operator.eq,
    FilterOperator.NOT_EQUAL: operator.ne,
    FilterOperator.LESS: operator.lt,
    FilterOperator.LESS_OR_EQUAL: operator.le,
    FilterOperator.GREATER: operator.gt,
    FilterOperator.GREATER_OR_EQUAL: operator.ge,
}


#: each text comparison, as a function of the filter's value and a cell's text
_TEXT_MATCHES: Mapping[FilterOperator, Callable[[Any, str], Any]] = {
    FilterOperator.CONTAINS: lambda value, text: value in text.casefold(),
    FilterOperator.NOT_CONTAINS: lambda value, text: value not in text.casefold(),
    FilterOperator.TEXT_EQUAL: lambda value, text: text.casefold() == value,
    FilterOperator.TEXT_NOT_EQUAL: lambda value, text: text.casefold() != value,
    FilterOperator.STARTS_WITH: lambda value, text: text.casefold().startswith(value),
    FilterOperator.ENDS_WITH: lambda value, text: text.casefold().endswith(value),
    FilterOperator.MATCHES: lambda value, text: value.search(text) is not None,
}


@attrs.frozen
class Filter:
    """A column's filter, parsed from the text the user typed (see `parse_filter`)."""

    operator: FilterOperator
    #: the text a cell is compared with (casefolded), a compiled regular expression, or
    #: the value a cell's is compared with
    value: Any = None
    #: a range's end
    upper: Any = None
    #: a text's filter typed in ASCII characters alone, which SQLite folds as Python does
    #: (see `SqliteSource`)
    typed_ascii: bool = True

    def matches(self, value: Any, text: str) -> bool:
        """Tell whether a cell passes: its value (its text in a text column) and its text."""
        if self.operator is FilterOperator.EMPTY:
            return value is None or text == ""
        if self.operator in _TEXT_MATCHES:
            return bool(_TEXT_MATCHES[self.operator](self.value, text))
        if value is None:
            return False
        try:
            return self._compares(value)
        except TypeError:  # a value of another type, e.g. the column's since changed
            return False

    def _compares(self, value: Any) -> bool:
        if self.operator is FilterOperator.RANGE:
            return bool(self.value <= value <= self.upper)
        return bool(_COMPARE[self.operator](value, self.value))


class ColumnKind(enum.Enum):
    """What a column's cells hold, which sets how they sort and filter."""

    TEXT = enum.auto()
    NUMBER = enum.auto()
    DATE = enum.auto()
    BOOLEAN = enum.auto()


def column_kind(field_type: Any) -> ColumnKind:
    """Get the kind of a column showing a field of `field_type` (`Optional` or not)."""
    types = [arg for arg in get_args(field_type) if arg is not type(None)]
    if get_origin(field_type) is Union and len(types) == 1:
        field_type = types[0]
    if field_type is bool:
        return ColumnKind.BOOLEAN
    if field_type in (int, float, decimal.Decimal, datetime.timedelta):
        return ColumnKind.NUMBER
    if field_type in (datetime.date, datetime.datetime):
        return ColumnKind.DATE
    return ColumnKind.TEXT


def _parse_value(text: str, field_type: Any, kind: ColumnKind) -> Any:
    """Parse a filter's value as the column's field, the way an edit is parsed."""
    types = [arg for arg in get_args(field_type) if arg is not type(None)]
    base = types[0] if get_origin(field_type) is Union and len(types) == 1 else field_type
    problems = {
        ColumnKind.NUMBER: FilterProblem.NOT_A_NUMBER,
        ColumnKind.DATE: FilterProblem.NOT_A_DATE,
        ColumnKind.BOOLEAN: FilterProblem.NOT_A_BOOLEAN,
    }
    try:
        # as `_cell_text` writes a date: ISO, which the converter doesn't read
        if base is datetime.datetime:
            parsed = datetime.datetime.fromisoformat(text)
            if parsed.tzinfo is not None:  # raises at the ends of the calendar, without UTC
                parsed.astimezone(datetime.timezone.utc)
            return parsed
        if base is datetime.date:
            return datetime.date.fromisoformat(text)
        if base is decimal.Decimal:
            return decimal.Decimal(text)
        return _CELL_CONVERTER.structure(text, base)
    except (*_BAD_STATE_ERRORS, decimal.InvalidOperation, OverflowError) as error:
        raise FilterError(problems[kind], text) from error


#: environment variable that a deployed app sets to ``off`` to refuse the regular expressions
#: of filters: a crafted one can run for a long time in Python's ``re``, which no timeout
#: stops and which holds the GIL, so that every session of the process waits
FILTER_PATTERNS_VARIABLE = "COMPOSEUI_FILTER_PATTERNS"


def take_filter_patterns() -> bool:
    """Tell whether filters take regular expressions; a value nobody can read is an error."""
    setting = os.environ.get(FILTER_PATTERNS_VARIABLE, "").strip().lower()
    if setting in ("", "on", "true", "1", "yes"):
        return True
    if setting in ("off", "false", "0", "no"):
        return False
    # a security setting: a typo mustn't leave the regular expressions on, unnoticed
    msg = f"{FILTER_PATTERNS_VARIABLE} must be off or on, not {setting!r}"
    raise ValueError(msg)


def as_pattern(text: str) -> str:
    """Write a regular expression as a text column's filter: between slashes."""
    return f"/{text}/"


def split_pattern(text: str) -> tuple[str, bool]:
    """Get a filter's text without its slashes, and whether it's a regular expression.

    The user writes a pattern without them, a toggle saying it is one (see `as_pattern`).
    """
    is_pattern = len(text) >= 2 and text.startswith("/") and text.endswith("/")  # noqa: PLR2004
    return (text[1:-1], True) if is_pattern else (text, False)


def _parse_text(text: str) -> Filter:
    """Parse a text column's filter, its text stripped and neither empty nor ``=``.

    A regular expression (`as_pattern`) searches the cells (ignoring case), ``=kitchen``
    keeps the cells equal to the text and ``!=kitchen`` the others, ``!kit`` the cells not
    containing it, ``kit*`` those starting with it and ``*en`` those ending with it. Else
    the cells containing it.
    """
    pattern, is_pattern = split_pattern(text)
    if is_pattern:
        if not take_filter_patterns():
            raise FilterError(FilterProblem.PATTERNS_OFF, pattern)
        try:
            return Filter(FilterOperator.MATCHES, re.compile(pattern, re.IGNORECASE))
        except re.error as error:
            raise FilterError(FilterProblem.NOT_A_PATTERN, pattern) from error
    for prefix, comparison in (
        ("!=", FilterOperator.TEXT_NOT_EQUAL),
        ("=", FilterOperator.TEXT_EQUAL),
        ("!", FilterOperator.NOT_CONTAINS),
    ):
        if text.startswith(prefix) and len(text) > len(prefix):
            return _text_filter(comparison, text[len(prefix) :].strip())
    if len(text) > 1 and text.endswith("*") and not text.startswith("*"):
        return _text_filter(FilterOperator.STARTS_WITH, text[:-1])
    if len(text) > 1 and text.startswith("*") and not text.endswith("*"):
        return _text_filter(FilterOperator.ENDS_WITH, text[1:])
    return _text_filter(FilterOperator.CONTAINS, text.strip("*"))


def _text_filter(operator: FilterOperator, text: str) -> Filter:
    """Get the filter comparing the cells with `text`, ignoring any case (casefolded)."""
    return Filter(operator, text.casefold(), typed_ascii=text.isascii())


def parse_filter(text: str, field_type: Any = str) -> Filter:
    """Parse a filter's text for a column showing a field of `field_type`.

    In a text column, ignoring case: the cells that contain the text, or as `_parse_text`
    says (``=exact``, ``!=exact``, ``!not``, ``start*``, ``*end``, ``/regex/``). In a
    number, a date or a duration column (``1d 2h`` or seconds): a comparison (``>20``, ``>=20``,
    ``<20``, ``<=20``, ``!=20``). Or a range (``18..24``, both ends included), or a bare
    value, which means ``=``. In a boolean column: ``true`` or ``false``. In any column:
    ``=`` alone, for the empty cells. Raise `FilterError` when the text doesn't parse, or for
    a ``/regex/`` when the ``COMPOSEUI_FILTER_PATTERNS`` environment variable is ``off``.
    """
    text = text.strip()
    if text == "":
        raise FilterError(FilterProblem.EMPTY, text)
    if text == "=":
        return Filter(FilterOperator.EMPTY)
    kind = column_kind(field_type)
    if kind is ColumnKind.TEXT:
        return _parse_text(text)
    if kind is ColumnKind.BOOLEAN:
        return Filter(FilterOperator.EQUAL, _parse_value(text, field_type, kind))
    for comparison in _COMPARISONS:
        if text.startswith(comparison.value):
            value = text[len(comparison.value) :].strip()
            return Filter(comparison, _parse_value(value, field_type, kind))
    if ".." in text:
        lower, _, upper = (part.strip() for part in text.partition(".."))
        range_filter = Filter(
            FilterOperator.RANGE,
            _parse_value(lower, field_type, kind),
            _parse_value(upper, field_type, kind),
        )
        try:
            is_reversed = range_filter.value > range_filter.upper
        except TypeError as error:  # a time zone at one end only
            raise FilterError(FilterProblem.NOT_A_DATE, text) from error
        if is_reversed:
            raise FilterError(FilterProblem.REVERSED_RANGE, text)
        return range_filter
    return Filter(FilterOperator.EQUAL, _parse_value(text, field_type, kind))


class CellKind(enum.Enum):
    """What the cells of a column show (see `CellWidget`)."""

    #: a check box, checked when the cell's text is "true", ignoring case
    CHECK_BOX = enum.auto()
    #: a combobox of `CellWidget.options`, showing the cell's text
    COMBOBOX = enum.auto()
    #: the cell's text, then a button
    BUTTON = enum.auto()
    #: the cell's text as a link
    LINK = enum.auto()
    #: a file's path, then a "…" button picking one (see `CellWidget.file_path`)
    FILE_PATH = enum.auto()
    #: a folder's path, then a "…" button picking one (see `CellWidget.folder_path`)
    FOLDER_PATH = enum.auto()
    #: a path to save a file to, then a "…" button picking one (see `CellWidget.save_path`)
    SAVE_PATH = enum.auto()
    #: a path picked as the row's kind says, by another cell (see `CellWidget.path_by`)
    PATH_BY_KIND = enum.auto()

    @property
    def is_path(self) -> bool:
        """Tell whether its "…" button picks a path: a file's, a folder's, or one to save to."""
        return self in (CellKind.FILE_PATH, CellKind.FOLDER_PATH, CellKind.SAVE_PATH)


#: a check box cell's text, by whether it's checked, as `str` writes a boolean
CHECKED_TEXTS: Mapping[bool, str] = {True: "True", False: "False"}


def _to_texts(texts: Iterable[str]) -> tuple[str, ...]:
    return tuple(texts)


def _to_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    return tuple(paths)


@attrs.frozen
class CellWidget:
    """A widget in each cell of a table's column, by `TableMixin.cell_widgets`.

    A check box and a combobox edit their cell when the column is in `editable_columns`.
    Then `cell_edited` emits the new text, as for a typed edit; a check box's text comes
    from `CHECKED_TEXTS`. Else they only show the cell's text. A button and a link emit
    `cell_clicked`, and the user never types in their cells.

    A file path cell is typed in, and its "…" button picks a file, as `FilePathInputView`'s
    does: the toolkit's file dialog on Qt and Textual, an upload on the web, whose copy the
    session keeps while a cell holds its path. `cell_edited` then emits the file's path.
    With `upload_folder`, the web keeps the upload in that folder instead, as the app's
    own file, unless no cell holds its path once the edit is over, e.g. refused.
    Its button is enabled only in an editable column. With `server_roots`, the web lists
    the server's files in them instead, and refuses a path typed outside them: the cell
    keeps its text, and a notification says why. A folder path cell and a save path cell
    pick as `FolderPathInputView` and `SavePathInputView` do: on the web, without
    `server_roots`, their path is typed, and they have no button. With `base_folder`, a
    relative path names a path in that folder, and a path picked in it shows relative to
    it, as in a path field.

    `path_by` picks the widget of each cell by the row's kind: the text of another cell of
    the row. When the user changes that cell, the path cell's widget follows.
    """

    kind: CellKind
    #: a combobox's choices, the texts its cells take
    options: tuple[str, ...] = attrs.field(default=(), converter=_to_texts)
    #: a button's text; a file path button's name, as a tooltip and a screen reader show it
    text: str = "\u2026"
    #: whether a check box column's header has a box checking or unchecking every shown row
    check_all: bool = False
    #: the file types a file path's dialog offers, by name: ``{"CSV": (".csv",)}``; on the
    #: web, a file of another type is refused
    extensions: dict[str, tuple[str, ...]] = attrs.field(
        factory=dict[str, tuple[str, ...]], hash=False
    )
    #: the folders of the server whose files a file path's "…" lists on the web, rather
    #: than uploading a copy; on Qt and Textual, the dialog opens in the first one while
    #: the cell is empty, and the user can leave it (see `FilePathInputMixin.server_roots`)
    server_roots: tuple[Path, ...] = attrs.field(default=(), converter=_to_paths)
    #: the folder of a path cell's relative path (see `PathInputMixin.base_folder`)
    base_folder: Optional[Path] = None
    #: the folder that keeps a file path's upload on the web (see
    #: `FilePathInputMixin.upload_folder`)
    upload_folder: Optional[Path] = None
    #: whether a save path's user agrees to replace a file that exists, before it's picked
    confirms_overwrite: bool = True
    #: for `path_by`: the column of the row's kind, and the path widget of each kind
    kind_column: int = 0
    editors: dict[str, CellWidget] = attrs.field(factory=dict[str, "CellWidget"], hash=False)

    def translated(self, translate: Translate) -> CellWidget:
        """Get it with a button's text translated again, if it's `TranslatedText`."""
        text = translate_again(self.text, translate)
        editors = {kind: editor.translated(translate) for kind, editor in self.editors.items()}
        if text is self.text and all(editors[kind] is self.editors[kind] for kind in editors):
            return self
        return attrs.evolve(self, text=text, editors=editors)

    def for_row(self, cells: Sequence[str]) -> Optional[CellWidget]:
        """Get the widget of a cell of the row `cells`: for `path_by`, its kind's, if any.

        A kind's widget without a `base_folder` or an `upload_folder` takes this one's.
        """
        if self.kind is not CellKind.PATH_BY_KIND:
            return self
        kind = cells[self.kind_column] if self.kind_column < len(cells) else ""
        editor = self.editors.get(kind)
        if editor is None:
            return None
        inherited = {
            name: getattr(self, name)
            for name in ("base_folder", "upload_folder")
            if getattr(editor, name) is None and getattr(self, name) is not None
        }
        # most rows: the editor itself, not a copy made for each cell drawn
        return attrs.evolve(editor, **inherited) if inherited else editor

    def path(self, text: str) -> Path:
        """Get the path a path cell's `text` names: from `base_folder` if relative."""
        return path_of_text(text.strip(), self.base_folder)

    def path_text(self, path: Path) -> str:
        """Get the text a path cell shows for `path`: relative to `base_folder` when inside it."""
        return text_of_path(path, self.base_folder)

    def start_folder(self) -> Optional[Path]:
        """Get the folder a path cell's dialog opens in while it's empty, if any.

        `base_folder`, else the first of `server_roots`.
        """
        if self.base_folder is not None:
            return self.base_folder.expanduser()
        return self.server_roots[0] if self.server_roots else None

    @classmethod
    def check_box(cls, *, check_all: bool = False) -> CellWidget:
        return cls(CellKind.CHECK_BOX, check_all=check_all)

    @classmethod
    def combobox(cls, options: Iterable[str] = ()) -> CellWidget:
        return cls(CellKind.COMBOBOX, _to_texts(options))

    @classmethod
    def button(cls, text: str = "\u2026") -> CellWidget:
        return cls(CellKind.BUTTON, text=text)

    @classmethod
    def link(cls) -> CellWidget:
        return cls(CellKind.LINK)

    @classmethod
    def file_path(
        cls,
        extensions: Optional[dict[str, tuple[str, ...]]] = None,
        text: str = T("Choose a file"),
        server_roots: Iterable[Path] = (),
        base_folder: Optional[Path] = None,
        upload_folder: Optional[Path] = None,
    ) -> CellWidget:
        return cls(
            CellKind.FILE_PATH,
            text=text,
            extensions=dict(extensions or {}),
            server_roots=_to_paths(server_roots),
            base_folder=base_folder,
            upload_folder=upload_folder,
        )

    @classmethod
    def folder_path(
        cls,
        text: str = T("Choose a folder"),
        server_roots: Iterable[Path] = (),
        base_folder: Optional[Path] = None,
    ) -> CellWidget:
        return cls(
            CellKind.FOLDER_PATH,
            text=text,
            server_roots=_to_paths(server_roots),
            base_folder=base_folder,
        )

    @classmethod
    def save_path(
        cls,
        extensions: Optional[dict[str, tuple[str, ...]]] = None,
        text: str = T("Save as"),
        server_roots: Iterable[Path] = (),
        base_folder: Optional[Path] = None,
        *,
        confirms_overwrite: bool = True,
    ) -> CellWidget:
        """Get a save path cell: picking a file that exists asks first, nothing is written."""
        return cls(
            CellKind.SAVE_PATH,
            text=text,
            extensions=dict(extensions or {}),
            server_roots=_to_paths(server_roots),
            base_folder=base_folder,
            confirms_overwrite=confirms_overwrite,
        )

    @classmethod
    def path_by(
        cls,
        kind_column: int,
        editors: Mapping[str, CellWidget],
        base_folder: Optional[Path] = None,
        upload_folder: Optional[Path] = None,
    ) -> CellWidget:
        """Get a path cell whose widget is that of the row's kind, the text of `kind_column`.

        `editors` are file, folder or save path widgets, by kind. A row whose kind has none
        shows a plain cell. `base_folder` and `upload_folder` are those of the widgets that
        have none.
        """
        for kind, editor in editors.items():
            if not editor.kind.is_path:
                msg = f"Cannot pick a path for the kind {kind!r} with a {editor.kind.name} cell."
                raise ValueError(msg)
        return cls(
            CellKind.PATH_BY_KIND,
            text="",
            kind_column=kind_column,
            editors=dict(editors),
            base_folder=base_folder,
            upload_folder=upload_folder,
        )


#: the brightness above which a background takes black text, else white
_LIGHT_BACKGROUND = 0.5


@attrs.frozen
class CellStyle:
    """How a table's cell looks, by `TableMixin.cell_styles`: plain by default."""

    def _check_background(self, _attribute: attrs.Attribute[Any], color: Optional[str]) -> None:
        if color is not None and _COLOR_PATTERN.fullmatch(color) is None:
            msg = f"Cannot color a cell's background {color!r}: give it as #rrggbb."
            raise ValueError(msg)

    def _check_row_span(self, _attribute: attrs.Attribute[Any], row_span: int) -> None:
        if row_span < 1:
            msg = f"Cannot make a cell span {row_span} rows: it spans 1 at least."
            raise ValueError(msg)

    #: its color, as #rrggbb, the same in every theme, e.g. red for NaN; its text is
    #: black or white, whichever reads on it (`text_color`)
    background: Optional[str] = attrs.field(default=None, validator=[_check_background])
    #: False: grayed, and never edited, even in an editable column: its widget is disabled
    is_enabled: bool = True
    #: a mark before its text, e.g. a warning, named by the table's `mark_text`
    mark: Optional[NodeMark] = None
    #: how many rows it covers, its own and those under it, which show nothing in its
    #: column; only while the table shows them right under it, unsorted and unfiltered
    row_span: int = attrs.field(default=1, validator=[_check_row_span])

    @property
    def text_color(self) -> Optional[str]:
        """Get the color of the text on `background`, black or white; None without one."""
        if self.background is None:
            return None
        red, green, blue = (int(self.background[i : i + 2], 16) / 255 for i in (1, 3, 5))
        brightness = 0.299 * red + 0.587 * green + 0.114 * blue
        return "#000000" if brightness > _LIGHT_BACKGROUND else "#ffffff"


#: a cell without a style of its own
PLAIN_CELL = CellStyle()


@attrs.frozen
class HeaderGroup:
    """A header over several columns, on a row above theirs, by `TableMixin.header_groups`.

    E.g. "Coordinates" over "Standard space" and "Physical space".
    """

    text: str
    #: its first column
    column: int
    #: how many columns it covers, from `column` on
    column_count: int

    def translated(self, translate: Translate) -> HeaderGroup:
        """Get it with its text translated again, if it's `TranslatedText`."""
        text = translate_again(self.text, translate)
        return self if text is self.text else attrs.evolve(self, text=text)

    def covers(self, column: int) -> bool:
        return self.column <= column < self.column + self.column_count


#: the milliseconds a table's filter bar waits after the last key typed in its search
#: before it searches: one search for a word, not one per letter (Enter searches at once)
SEARCH_DELAY_MS = 300

#: the text of a table's filter bar, which the renderers show
FILTER_TEXTS: Mapping[str, str] = {
    "search": T("Search"),
    "clear_search": T("Clear the search"),
    "add_filter": T("+ Filter"),
    "column": T("Column"),
    "value": T("Value"),
    "add": T("Add"),
    "clear": T("Clear"),
    "count": T("{shown} of {total}"),
    "no_match": T("No rows match the filters"),
    "remove": T("Remove the filter on {header}"),
    "edit": T("Edit the filter on {header}"),
    "chip": T("{header}: {filter}"),
    "chip_pattern": T("{header} matches {filter}"),
    "pattern": T("Regular expression"),
}

#: the texts of the web's list of the server's files, for a table's file path cells
FILE_TEXTS: Mapping[str, str] = {
    "parent_folder": T("Parent folder"),
    "cancel": T("Cancel"),
    "unreadable_folder": T("This folder can't be read."),
    "partial_folder": T("This folder holds too many items to list them all: type the file's path."),
    "outside_roots": T("Can't take {path}: it isn't in the folders this column lists."),
    "choose_folder": T("Choose this folder"),
    "file_name": T("File name"),
    "save": T("Save"),
    "replace_question": T("{name} already exists. Replace it?"),
    "replace": T("Replace"),
}

_ItemT = TypeVar("_ItemT")


def _sorted_by(
    items: Sequence[_ItemT],
    value: Callable[[_ItemT], Any],
    text: Callable[[_ItemT], str],
    *,
    is_text: bool,
    descending: bool,
) -> list[_ItemT]:
    """Sort `items` stably by `value`: text by `str.casefold`, empty cells last.

    Values that don't compare (e.g. a column's type since changed) sort by their `text`.
    """

    def key(item: _ItemT) -> Any:
        cell = value(item)
        if cell is None or cell == "":
            return None
        return cell.casefold() if is_text else cell

    keyed = [(item, key(item)) for item in items]
    present = [(item, cell) for item, cell in keyed if cell is not None]
    try:
        ordered = sorted(present, key=operator.itemgetter(1), reverse=descending)
    except TypeError:
        ordered = sorted(present, key=lambda pair: text(pair[0]).casefold(), reverse=descending)
    return [item for item, _ in ordered] + [item for item, cell in keyed if cell is None]


def _filter_error(tr: Callable[[str], str], text: str, field_type: Any) -> Optional[str]:
    """Say why `text` can't filter a column of `field_type`, translated by `tr`; None if it can."""
    try:
        parse_filter(text, field_type)
    except FilterError as error:
        messages = {
            FilterProblem.EMPTY: tr("Type a value to filter by"),
            FilterProblem.NOT_A_NUMBER: tr('"{text}" isn\'t a number'),
            FilterProblem.NOT_A_DATE: tr('"{text}" isn\'t a date, as 2024-01-31'),
            FilterProblem.NOT_A_BOOLEAN: tr('"{text}" isn\'t true or false'),
            FilterProblem.REVERSED_RANGE: tr("The range's start is after its end"),
            FilterProblem.NOT_A_PATTERN: tr('"{text}" isn\'t a valid regular expression'),
            FilterProblem.PATTERNS_OFF: tr("This app doesn't accept regular expressions"),
        }
        return messages[error.problem].format(text=error.text)
    return None


def _filter_placeholder(tr: Callable[[str], str], field_type: Any, *, is_pattern: bool) -> str:
    """Hint at what filters a column of `field_type`: a regular expression, or else text."""
    kind = column_kind(field_type)
    if is_pattern and kind is ColumnKind.TEXT:
        return tr("a regular expression, as Room [1-3]")
    if datetime.timedelta in (field_type, *get_args(field_type)):
        return tr(">=1d 2h, 1m..90m")
    if kind is ColumnKind.NUMBER:
        return tr(">=20, 18..24")
    if kind is ColumnKind.DATE:
        return tr(">=2024-01-31")
    if kind is ColumnKind.BOOLEAN:
        return tr("true or false")
    return tr("contains, =exact, start*, !not")


def _filter_chip(texts: Mapping[str, str], header: str, typed: str, *, takes_pattern: bool) -> str:
    """Show a filter as its chip does: its column's header, then the text typed.

    Apart, as a label and its value: the header isn't part of what's typed. A regular
    expression without its slashes: "Room matches Room [1-3]".
    """
    text, is_pattern = split_pattern(typed)
    if is_pattern and takes_pattern:
        chip = texts.get("chip_pattern", "{header} {filter}")
    else:
        chip, text = texts.get("chip", "{header}: {filter}"), typed
    return chip.format(header=header, filter=text)


def _store(view: View, attribute: attrs.Attribute[Any], value: Any) -> None:
    """Set `view`'s attribute, then notify its renderer: it shows the view as it now is."""
    old = getattr(view, attribute.name)
    set_value(view, attribute.name, value)
    renderer = view.renderer
    if (
        old != value
        and isinstance(renderer, (Renderer, RendererContainer))
        and not renderer.is_updating_state()
    ):
        renderer.refresh_attribute(attribute.name, value)


def _sort_value(value: Any) -> Any:
    """Get the value a field's cell sorts and filters by: an enum by its text, as shown."""
    return _cell_text(value) if isinstance(value, enum.Enum) else value


@define_view
class TableMixin:
    """A table of text: the app formats each cell itself.

    Each row has one cell per header. Assign new lists to update the table: changing a
    list in place doesn't reach the renderer. The user selects rows as `selection_mode`
    allows. `selected_rows` holds their indexes, and `selection_changed` emits them when
    the user changes them. New `rows` keep each selected row selected when they hold it
    exactly once, wherever it moved, and drop it otherwise. `row_activated` emits a row's
    index when the user opens it: a double click on a cell that doesn't edit or click, or
    Enter, which also selects it on Textual and the web.

    The user edits the cells of the columns in `editable_columns` (none by default).
    `cell_edited` emits the row, the column and the new text while `rows` still holds the
    old text. Then the edit replaces its row in `rows`, and keeps the selection. To refuse
    or reformat the edit, or to show what it changed elsewhere, assign `rows` from the
    callback instead. The table shows these rows, and doesn't apply the edit on top. The
    edited row stays selected when they hold it as edited (e.g. renamed, then sorted), or
    else as it was (the edit refused). Raising `EditRefusedError` refuses the edit too,
    and the rows stay as they are, e.g. when the model refused the new text and changed
    nothing. A `RefusedError` caught by `View.refusing` in the callback does the same.
    To read the edited rows instead, connect `cell_edit_applied`: it emits the row, the
    column and the cell's text once `rows` holds the edit, and not for an edit refused or
    answered with other rows.

    A column of `cell_widgets` shows a widget in each cell (see `CellWidget`). A check box,
    a combobox or a file path edits the cell. A button or a link emits `cell_clicked` with
    its row and column. A check box column's header can check or uncheck every shown row
    (`check_all`), and each change is emitted as the user's edit. To give a cell a widget
    that its row decides, override `cell_widget`.

    The user sorts the rows by a column of `sortable_columns` (`sort_column`, ascending
    unless `sort_descending`). The user also searches the text of `filterable_columns`
    (`search`), and filters each of them (`filters`, the text typed, see `parse_filter`).
    The table shows `shown_rows`, which these compute. The indexes that the table emits or
    takes stay those of `rows`, whatever the order. A search or a filter that hides a
    selected row deselects it, and `selection_changed` emits. New `rows` keep the order,
    the search and the filters.

    Each cell of `cell_styles` looks as its `CellStyle` says: a background color, grayed
    and never edited, a mark, spanning the rows under it. Assign the styles with the rows
    they describe. They are by index in `rows`, so new rows keep the styles of the rows
    that were at their indexes. `header_groups` put a header over several columns, on a
    row above theirs. `row_headers` put a header before each row, e.g. the keys of a small
    key/value table of results.
    """

    def _check_selected_rows(self, _attribute: attrs.Attribute[Any], rows: list[int]) -> None:
        name = type(self).__name__
        if any(not 0 <= row < len(self.rows) for row in rows):
            msg = f"Cannot set {name}.selected_rows to {rows}: the table has {len(self.rows)} rows."
            raise ValueError(msg)
        if len(set(rows)) != len(rows):
            msg = f"Cannot set {name}.selected_rows to {rows}: a row is selected twice."
            raise ValueError(msg)
        if self.selection_mode is SelectionMode.SINGLE and len(rows) > 1:
            msg = f"Cannot set {name}.selected_rows to {rows}: the table selects a single row."
            raise ValueError(msg)

    def _check_header_groups(
        self, _attribute: attrs.Attribute[Any], groups: list[HeaderGroup]
    ) -> None:
        name = type(self).__name__
        covered: set[int] = set()
        for group in groups:
            columns = set(range(group.column, group.column + group.column_count))
            if group.column < 0 or group.column_count < 1:
                msg = f"Cannot group {name}'s headers under {group.text!r}: it covers no column."
                raise ValueError(msg)
            if len(columns & covered) > 0:
                msg = (
                    f"Cannot group {name}'s headers under {group.text!r}: a column is in two"
                    " groups."
                )
                raise ValueError(msg)
            covered |= columns

    def _check_sort_column(self, _attribute: attrs.Attribute[Any], column: Optional[int]) -> None:
        if column is not None and not self._is_column(column, self.sortable_columns):
            name = type(self).__name__
            msg = f"Cannot sort {name} by column {column}: it isn't one of its sortable columns."
            raise ValueError(msg)

    def _check_filters(self, _attribute: attrs.Attribute[Any], filters: dict[int, str]) -> None:
        name = type(self).__name__
        for column, text in filters.items():
            if not self._is_column(column, self.filterable_columns):
                msg = (
                    f"Cannot filter {name} by column {column}: it isn't one of its filterable"
                    " columns."
                )
                raise ValueError(msg)
            parse_filter(text, self._column_type(column))

    def _reconcile_mode(
        self, attribute: attrs.Attribute[Any], mode: SelectionMode
    ) -> SelectionMode:
        """Keep only the first selected row when the table comes to select a single one."""
        if mode is SelectionMode.SINGLE and len(self.selected_rows) > 1:
            self.selected_rows = self.selected_rows[:1]
        return cast("SelectionMode", notify_renderer(cast("View", self), attribute, mode))

    def _reconcile_rows(
        self, attribute: attrs.Attribute[Any], rows: list[list[str]]
    ) -> list[list[str]]:
        """Move `selected_rows` to their rows in `rows` (or drop them), and notify the renderer."""
        renderer = cast("View", self).renderer
        if isinstance(renderer, (Renderer, RendererContainer)) and renderer.is_updating_state():
            # the user edited a cell: the selection stays on its rows, which may still move
            # or hide, as their cells sort or filter
            set_value(self, "rows", rows)
            self._show_rows(self.selected_rows, force=False)
            return rows
        edited = self._edited_rows if self._edited_rows is not None else self.rows
        # each selected row as edited, then as it was
        selected = [(edited[row], self.rows[row]) for row in self.selected_rows]
        # unshown until the rows are: the renderer shows the selection with them
        set_value(self, "selected_rows", [])
        rows = notify_renderer(cast("View", self), attribute, rows)
        set_value(self, "rows", rows)
        found: set[int] = set()
        for candidates in selected:
            held = [rows.index(cells) for cells in candidates if rows.count(cells) == 1]
            found.update(held[:1])
        self._show_rows(sorted(found), force=True)
        return rows

    def _reconcile_sortable(self, attribute: attrs.Attribute[Any], columns: list[int]) -> list[int]:
        """Stop sorting by a column no longer sortable, and notify the renderer."""
        self._store(attribute, columns)
        if self.sort_column is not None and self.sort_column not in columns:
            self.sort_column = None
        return columns

    def _reconcile_filterable(
        self, attribute: attrs.Attribute[Any], columns: list[int]
    ) -> list[int]:
        """Drop the filters of columns no longer filterable, and notify the renderer."""
        self._store(attribute, columns)
        if any(column not in columns for column in self.filters):
            self.filters = {
                column: text for column, text in self.filters.items() if column in columns
            }
        if len(columns) == 0 and self.search != "":
            self.search = ""  # nothing left to search
        return columns

    def _store(self, attribute: attrs.Attribute[Any], value: Any) -> None:
        """Set an attribute, then notify the renderer: it shows the view as it now is."""
        _store(cast("View", self), attribute, value)

    def _restyle(self, attribute: attrs.Attribute[Any], value: Any) -> Any:
        """Set how the table looks, and notify the renderer, which shows it with the rows."""
        self._store(attribute, value)
        return value

    def _reshow(self, attribute: attrs.Attribute[Any], value: Any) -> Any:
        """Show the rows as `value` sorts or filters them, and notify the renderer."""
        if getattr(self, attribute.name) == value:
            return value
        self._store(attribute, value)
        selected = self.selected_rows
        shown = self._show_rows(selected, force=True)
        if shown != selected:
            self.selection_changed.emit(shown)
        return value

    headers: list[str] = attrs.field(factory=list[str], metadata={UI_TEXT: True})
    #: the filter bar's text, by what it's for (see `FILTER_TEXTS`)
    filter_texts: dict[str, str] = attrs.field(
        factory=lambda: dict(FILTER_TEXTS), metadata={UI_TEXT: True}
    )
    # before `selected_rows`, which it limits
    selection_mode: SelectionMode = attrs.field(
        default=SelectionMode.SINGLE, on_setattr=_reconcile_mode
    )
    rows: list[list[str]] = attrs.field(factory=list[list[str]], on_setattr=_reconcile_rows)
    # the sort and the filters, after `rows` and before `selected_rows`: loading saved state
    # shows the rows as they were before selecting them again
    sortable_columns: list[int] = attrs.field(factory=list[int], on_setattr=_reconcile_sortable)
    filterable_columns: list[int] = attrs.field(factory=list[int], on_setattr=_reconcile_filterable)
    sort_column: Optional[int] = attrs.field(
        default=None,
        validator=[_check_sort_column],
        on_setattr=[attrs.setters.validate, _reshow],
    )
    sort_descending: bool = attrs.field(default=False, on_setattr=_reshow)
    #: text the shown rows contain in a filterable column, ignoring case
    search: str = attrs.field(default="", on_setattr=_reshow)
    #: the filters by column, as typed (see `parse_filter`)
    filters: dict[int, str] = attrs.field(
        factory=dict[int, str],
        validator=[_check_filters],
        on_setattr=[attrs.setters.validate, _reshow],
    )
    # after `rows`: loading saved state checks it against the rows already loaded
    selected_rows: list[int] = attrs.field(factory=list[int], validator=[_check_selected_rows])
    #: the indexes in `rows` of the rows shown, in their order: computed, never set
    shown_rows: list[int] = attrs.field(
        factory=list[int], init=False, on_setattr=attrs.setters.frozen, metadata={OMIT: True}
    )
    selection_changed: Signal[list[int]] = attrs.Factory(Signal[list[int]])
    #: the user opened a row (a double click, Enter): its index in `rows`
    row_activated: Signal[int] = attrs.Factory(Signal[int])
    editable_columns: list[int] = attrs.Factory(list[int])
    cell_edited: Signal[int, int, str] = attrs.Factory(Signal[int, int, str])
    #: `rows` holds the user's edit: its row, its column and the cell's text
    cell_edit_applied: Signal[int, int, str] = attrs.Factory(Signal[int, int, str])
    #: the widget in each cell of a column, by column: the app's setup, not study data
    cell_widgets: dict[int, CellWidget] = attrs.field(
        factory=dict[int, CellWidget], on_setattr=_restyle, metadata={OMIT: True}
    )
    #: the texts of the web's list of the server's files, for a file path cell with
    #: `server_roots`, by what they're for (see `FILE_TEXTS`)
    file_texts: dict[str, str] = attrs.field(
        factory=lambda: dict(FILE_TEXTS), metadata={UI_TEXT: True}
    )
    #: the user clicked a button or a link cell: its row and its column
    cell_clicked: Signal[int, int] = attrs.Factory(Signal[int, int])
    #: how each cell looks, by its index in `rows` and its column (see `CellStyle`): the
    #: app's to set with the rows, not study data
    cell_styles: dict[tuple[int, int], CellStyle] = attrs.field(
        factory=dict[tuple[int, int], CellStyle], on_setattr=_restyle, metadata={OMIT: True}
    )
    #: headers over several columns, on a row above `headers`
    header_groups: list[HeaderGroup] = attrs.field(
        factory=list[HeaderGroup],
        validator=[_check_header_groups],
        on_setattr=[attrs.setters.validate, _restyle],
        metadata={UI_TEXT: True},
    )
    #: a header before each row, by its index in `rows`; none shown while empty
    row_headers: list[str] = attrs.field(
        factory=list[str], on_setattr=_restyle, metadata={UI_TEXT: True}
    )
    #: each `NodeMark`'s name, for screen readers (web) and as a tooltip (Qt)
    done_text: str = attrs.field(default=T("Done"), metadata={UI_TEXT: True})
    warning_text: str = attrs.field(default=T("Warning"), metadata={UI_TEXT: True})
    error_text: str = attrs.field(default=T("Error"), metadata={UI_TEXT: True})
    #: `rows` as the edit being emitted leaves them, while its callbacks run
    _edited_rows: Optional[list[list[str]]] = attrs.field(
        default=None, init=False, repr=False, metadata={OMIT: True}
    )

    def sort_by(self, column: int) -> None:
        """Sort as a click on the column's header does: ascending, descending, then not."""
        if self.sort_column != column:
            self.sort_descending = False
            self.sort_column = column
        elif not self.sort_descending:
            self.sort_descending = True
        else:
            self.sort_column = None
            self.sort_descending = False

    def filter_error(self, column: int, text: str) -> Optional[str]:
        """Say why `text` can't filter `column`, translated; None if it can."""
        return _filter_error(cast("View", self).tr, text, self._column_type(column))

    def filter_takes_pattern(self, column: int) -> bool:
        """Tell whether a regular expression filters `column`: a text column."""
        return take_filter_patterns() and column_kind(self._column_type(column)) is ColumnKind.TEXT

    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str:
        """Hint at what filters `column`, translated: a regular expression, or else text."""
        tr = cast("View", self).tr
        return _filter_placeholder(tr, self._column_type(column), is_pattern=is_pattern)

    def filter_chip(self, column: int) -> str:
        """Show a filter as its chip does: its column's header, then the text typed.

        Apart, as a label and its value: the header isn't part of what's typed. A regular
        expression without its slashes: "Room matches Room [1-3]".
        """
        header = self.headers[column] if column < len(self.headers) else ""
        return _filter_chip(
            self.filter_texts,
            header,
            self.filters[column],
            takes_pattern=self.filter_takes_pattern(column),
        )

    def mark_text(self, mark: NodeMark) -> str:
        """Get the name of `mark` in the main view's language."""
        if mark is NodeMark.DONE:
            return self.done_text
        return self.warning_text if mark is NodeMark.WARNING else self.error_text

    def cell_style(self, row: int, column: int) -> CellStyle:
        """Get how a cell looks, by its index in `rows`: plain unless `cell_styles` say."""
        return self.cell_styles.get((row, column), PLAIN_CELL)

    def cell_widget(self, row: int, column: int) -> Optional[CellWidget]:
        """Get the widget of a cell, by its index in `rows`: its row's kind's for `path_by`.

        Every backend draws and edits a cell with the widget this gives. Override it to give
        each row its own widget, e.g. a file or a folder by what the row holds. The tables
        ask again when `rows` or `cell_widgets` change: set what it reads before them.
        """
        widget = self.cell_widgets.get(column)
        if widget is None:
            return None
        return widget.for_row(self.rows[row] if row < len(self.rows) else [])

    def is_cell_editable(self, row: int, column: int) -> bool:
        """Tell whether the user edits a cell: in `editable_columns`, and not disabled."""
        return column in self.editable_columns and self.cell_style(row, column).is_enabled

    def header_group(self, column: int) -> Optional[HeaderGroup]:
        """Get the group of `header_groups` over `column`, if any."""
        return next((group for group in self.header_groups if group.covers(column)), None)

    def shown_cell_styles(self) -> dict[tuple[int, int], CellStyle]:
        """Get how the shown cells look, by position in `shown_rows` and column.

        A cell spans the shown rows right under it that follow it in `rows`, up to its
        `row_span`. Its style here says how many rows it spans as shown.
        """
        positions = {row: position for position, row in enumerate(self.shown_rows)}
        styles: dict[tuple[int, int], CellStyle] = {}
        for (row, column), style in self.cell_styles.items():
            position = positions.get(row)
            if position is None or column >= len(self.headers):
                continue
            span = 1
            while (
                span < style.row_span
                and position + span < len(self.shown_rows)
                and self.shown_rows[position + span] == row + span
            ):
                span += 1
            styles[position, column] = attrs.evolve(style, row_span=span)
        return styles

    def is_checked(self, row: int, column: int) -> bool:
        """Tell whether a check box cell is checked: its text is "true", ignoring case."""
        return self._cell_text(row, column).casefold() == "true"

    def column_checked(self, column: int) -> Optional[bool]:
        """Tell whether a check box column's shown cells are all checked, none, or some (None).

        Its disabled cells don't count: the check-all box doesn't change them.
        """
        checked = {
            self.is_checked(row, column)
            for row in self.shown_rows
            if self.cell_style(row, column).is_enabled
        }
        return None if len(checked) > 1 else checked == {True}

    def check_all(self, column: int, *, is_checked: bool) -> None:
        """Check or uncheck a check box column's shown cells, as its header's box does.

        Each cell changing is the user's edit: `cell_edited` emits it, and the edit applies
        unless its callbacks assigned `rows` or refused it. A disabled cell stays as it is.
        """
        text = CHECKED_TEXTS[is_checked]
        positions, position = list(self.shown_rows), 0
        # rows have no identity but their cells: those already tried, by their cells, are
        # left alone when a callback's new rows are read from the start
        tried: Counter[tuple[str, ...]] = Counter()
        seen: Counter[tuple[str, ...]] = Counter()
        edits_left = len(positions)  # a callback that keeps answering can't make it endless
        while position < len(positions) and edits_left > 0:
            row = positions[position]
            position += 1
            if (
                row >= len(self.rows)
                or self.is_checked(row, column) == is_checked
                or not self.cell_style(row, column).is_enabled
            ):
                continue
            cells = tuple(self.rows[row])
            seen[cells] += 1
            if seen[cells] <= tried[cells]:
                continue
            tried[cells] += 1
            edits_left -= 1
            edited = self._edit_cell(row, column, text, self._assign_edited)
            # unless the rows are the edit's, another row may now be anywhere: the
            # callbacks of `cell_edited` or `cell_edit_applied` answered with their own
            if edited is None or self.rows is not edited:
                positions, position, seen = list(self.shown_rows), 0, Counter()

    def edit_cell(
        self,
        row: int,
        column: int,
        text: str,
        assign: Optional[Callable[[list[list[str]]], None]] = None,
    ) -> bool:
        """Emit the user's edit, apply it unless its callbacks answered, and say if it applied.

        `assign` sets `rows` to the edited rows: a renderer's, which its widget already
        shows. Once `rows` holds the edit, `cell_edit_applied` emits it.
        """
        return self._edit_cell(row, column, text, assign or self._assign_edited) is not None

    def _edit_cell(
        self, row: int, column: int, text: str, assign: Callable[[list[list[str]]], None]
    ) -> Optional[list[list[str]]]:
        """Edit the cell as `edit_cell` does, and get the rows holding the edit, if applied."""
        rows = self.rows
        if not self.emit_cell_edited(row, column, text):
            if self.rows is not rows:  # refused, or answered with the callbacks' rows
                return None
            assign(replace_cell(rows, row, column, text))
        edited = self.rows
        # most tables' isn't connected: don't make it
        emit_if_made(cast("View", self), "cell_edit_applied", row, column, edited[row][column])
        return edited

    def _assign_edited(self, rows: list[list[str]]) -> None:
        # as edited, for the selection to stay on its row
        self._edited_rows = rows
        try:
            self.rows = rows
        finally:
            self._edited_rows = None

    def emit_cell_edited(self, row: int, column: int, text: str) -> bool:
        """Emit `cell_edited` for the user's edit, `rows` still holding the old text.

        Rows its callbacks assign keep the edited row selected as `TableMixin` says.
        Return whether the view applied the edit itself, as a `RecordTableView` does:
        else `edit_cell` applies it.
        """
        self._edited_rows = replace_cell(self.rows, row, column, text)
        token = _editing_cell.set(True)
        try:
            return self._emit_edit(row, column, text)
        except EditRefusedError:
            # the rows answering the edit, as when a callback puts them back itself
            self.rows = [list(cells) for cells in self.rows]
            return False
        finally:
            _editing_cell.reset(token)
            self._edited_rows = None

    def _emit_edit(self, row: int, column: int, text: str) -> bool:
        """Emit the edit's signals, `_edited_rows` holding the rows as it leaves them.

        Return whether the view applied the edit itself.
        """
        self.cell_edited.emit(row, column, text)
        return False

    def loadable(self, name: str, value: Any) -> Any:
        """Get the part of a saved sort or filters (`name`) the table's columns still take."""
        if name == "sort_column":
            return value if value is None or self._is_column(value, self.sortable_columns) else None
        if name == "filters":
            return {
                column: text
                for column, text in value.items()
                if self._is_column(column, self.filterable_columns)
                and self.filter_error(column, text) is None
            }
        return value

    def _is_column(self, column: int, columns: list[int]) -> bool:
        return column in columns and 0 <= column < len(self.headers)

    def _column_type(self, _column: int) -> Any:
        """Get the type of the field a column shows: text, in a table of text."""
        return str

    def _cell_value(self, row: int, column: int) -> Any:
        """Get the value a cell sorts and filters by: its text, in a table of text."""
        return self._cell_text(row, column)

    def _cell_text(self, row: int, column: int) -> str:
        cells = self.rows[row]
        return cells[column] if column < len(cells) else ""

    def _shown(self) -> list[int]:
        """Get the indexes in `rows` of the rows the search and the filters pass, sorted."""
        filters: dict[int, Filter] = {}
        for column, text in self.filters.items():
            # a filter the columns no longer take, e.g. changed since, filters nothing
            with contextlib.suppress(FilterError):
                filters[column] = parse_filter(text, self._column_type(column))
        needle = self.search.strip().casefold()
        searched = [column for column in self.filterable_columns if column < len(self.headers)]
        shown = [
            row
            for row in range(len(self.rows))
            if (
                needle == ""
                or any(needle in self._cell_text(row, column).casefold() for column in searched)
            )
            and all(
                row_filter.matches(self._cell_value(row, column), self._cell_text(row, column))
                for column, row_filter in filters.items()
            )
        ]
        if self.sort_column is None or self.sort_column >= len(self.headers):
            return shown
        return self._sorted(shown, self.sort_column)

    def _sorted(self, rows: list[int], column: int) -> list[int]:
        """Sort `rows` by `column`, stably: by value, text by `str.casefold`, empty cells last."""
        return _sorted_by(
            rows,
            lambda row: self._cell_value(row, column),
            lambda row: self._cell_text(row, column),
            is_text=column_kind(self._column_type(column)) is ColumnKind.TEXT,
            descending=self.sort_descending,
        )

    def _show_rows(self, selected: list[int], *, force: bool) -> list[int]:
        """Compute `shown_rows`, keep the shown rows of `selected` selected, and show both.

        The renderer gets `shown_rows` when they changed, or always with `force` (it shows
        the rows with them); once the view holds them both, so it can show them together.
        Return the rows still selected.
        """
        shown = self._shown()
        is_shown = set(shown)
        kept = [row for row in selected if row in is_shown]
        changed = shown != self.shown_rows
        set_value(self, "shown_rows", shown)
        set_value(self, "selected_rows", kept)
        renderer = cast("View", self).renderer
        if isinstance(renderer, (Renderer, RendererContainer)) and (force or changed):
            # even while the renderer updates the view: its widget doesn't order the rows
            renderer.refresh_attribute("shown_rows", shown)
        return kept


@define_view
class TableView(TableMixin, View):
    """A table of text that the app formats cell by cell (see `TableMixin`)."""

    _renderer_key = "table"

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        set_value(self, "shown_rows", self._shown())


RecordT = TypeVar("RecordT", bound="AttrsInstance")


@attrs.frozen
class Column:
    """A column of a `RecordTableView`: a field of its records, under `header`."""

    #: the name of the records' field the column shows
    field: str
    header: str
    #: whether the user edits the column's cells
    editable: bool = False
    #: whether the user sorts the rows by the column
    sortable: bool = False
    #: whether the user searches and filters the column
    filterable: bool = False
    #: the widget in each of its cells (see `CellWidget`); a combobox without options, on
    #: an enum field, offers the enum's members
    widget: Optional[CellWidget] = None


def _cell_text(value: Any) -> str:
    """Show a record's field in its cell: as saved, None as an empty cell."""
    return "" if value is None else str(CONVERTER.unstructure(value))


def _parse_cell(text: str, field_type: Any) -> Any:
    """Parse a cell's text into a record's field of `field_type`, as its cell shows it.

    An enum's member by the text of its value: cattrs would read "1" as text, or an
    `IntEnum`'s as an `int`. Raises a `ValueError` for text no cell shows.
    """
    types = [arg for arg in get_args(field_type) if arg is not type(None)]
    if text == "" and len(types) < len(get_args(field_type)):
        return None  # an empty cell: an `Optional` field's None
    base = types[0] if get_origin(field_type) is Union and len(types) == 1 else field_type
    if isinstance(base, type) and issubclass(base, enum.Enum):
        for member in base:
            if _cell_text(member) == text:
                return member
        msg = f"{text!r} isn't a value of {base.__name__}"
        raise ValueError(msg)
    return _CELL_CONVERTER.structure(text, field_type)


@define_view
class RecordTableView(TableView, Generic[RecordT]):
    """A table of records, `attrs` instances, each a row with a cell per column.

    Build it with its records' type, so a study can save and load them:
    ``child(RecordTableView[Room], columns=[Column("name", T("Room"), editable=True)])``.
    `columns` set the headers and the editable columns. The table formats each field in
    its cell (`str`, None as an empty cell): assign new `records`, not `rows`.

    The user's edit is parsed into the field's type with `CONVERTER`. A cell that doesn't
    parse refuses the edit, and a notification says why. Else `record_edited` emits the
    old and the new record while `records` still holds the old one. Then the new record
    replaces the old one, unless the callbacks assigned `records` themselves. Refusing the
    edit works as with `cell_edited` (`View.refusing`).
    """

    def _reconcile_columns(
        self, _attribute: attrs.Attribute[Any], columns: list[Column]
    ) -> list[Column]:
        # first: the rows sort and filter by the columns' fields
        set_value(self, "columns", columns)
        self.headers = [translate_again(column.header, self._tr) for column in columns]
        self.editable_columns = [index for index, column in enumerate(columns) if column.editable]
        self.sortable_columns = [index for index, column in enumerate(columns) if column.sortable]
        self.filterable_columns = [
            index for index, column in enumerate(columns) if column.filterable
        ]
        self.cell_widgets = self._cell_widgets()
        self.rows = [self._cells(record, columns) for record in self.records]
        return columns

    def _cell_widgets(self) -> dict[int, CellWidget]:
        return {
            index: self._cell_widget(index, column.widget)
            for index, column in enumerate(self.columns)
            if column.widget is not None
        }

    def _cell_widget(self, column: int, widget: CellWidget) -> CellWidget:
        """Get a column's widget, translated.

        A combobox without options, on an enum field, offers the enum's members.
        """
        widget = widget.translated(self._tr)
        field_type = self._column_type(column)
        if (
            widget.kind is not CellKind.COMBOBOX
            or len(widget.options) > 0
            or not isinstance(field_type, type)
            or not issubclass(field_type, enum.Enum)
        ):
            return widget
        return attrs.evolve(widget, options=_to_texts(_cell_text(member) for member in field_type))

    def _reconcile_records(
        self, _attribute: attrs.Attribute[Any], records: list[RecordT]
    ) -> list[RecordT]:
        # first: the rows sort and filter by the records' values
        set_value(self, "records", records)
        # the records' type may be known only since: ``RecordTableView[Room](...)`` sets it
        # once built
        self.cell_widgets = self._cell_widgets()
        self.rows = [self._cells(record, self.columns) for record in records]
        return records

    # the table's setup, by the app: not study data
    columns: list[Column] = attrs.field(
        factory=list[Column], on_setattr=_reconcile_columns, metadata={OMIT: True}
    )
    records: list[RecordT] = attrs.field(factory=list, on_setattr=_reconcile_records)
    #: the user edited a record: the old one, then the new one
    record_edited: Signal[RecordT, RecordT] = attrs.Factory(Signal[RecordT, RecordT])

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.columns = self.columns
        self.records = self.records

    @property
    def record_type(self) -> type:
        """Get the records' type, from ``RecordTableView[Room]`` or a subclass's base."""
        bases = [getattr(self, "__orig_class__", None)]
        bases += [base for cls in type(self).__mro__ for base in getattr(cls, "__orig_bases__", ())]
        for base in bases:
            origin = get_origin(base)
            if isinstance(origin, type) and issubclass(origin, RecordTableView):
                (record_type,) = get_args(base)
                if isinstance(record_type, type):
                    return record_type
        msg = (
            f"{type(self).__name__} doesn't know its records' type: build it as "
            "RecordTableView[Room](...)."
        )
        raise TypeError(msg)

    def column_index(self, field: str) -> int:
        """Get the index of the column showing `field`, e.g. to style its cells.

        Raise `ValueError` when no column shows it.
        """
        for index, column in enumerate(self.columns):
            if column.field == field:
                return index
        msg = f"{type(self).__name__} has no column showing {field!r}."
        raise ValueError(msg)

    @property
    def selected_record(self) -> Optional[RecordT]:
        """Get the first selected record, or None if no row is selected."""
        return self.records[self.selected_rows[0]] if len(self.selected_rows) > 0 else None

    @property
    def selected_records(self) -> list[RecordT]:
        """Get the selected records, as `selected_rows` lists them."""
        return [self.records[row] for row in self.selected_rows]

    def structure_records(self, data: Any) -> list[RecordT]:
        """Build records of `record_type` from their saved data."""
        return cast("list[RecordT]", CONVERTER.structure(data, cast("Any", list)[self.record_type]))

    @staticmethod
    def _cells(record: Any, columns: Sequence[Column]) -> list[str]:
        return [_cell_text(getattr(record, column.field)) for column in columns]

    @override
    def _column_type(self, column: int) -> Any:
        """Get the type of the column's field, by which its cells sort and filter."""
        assert column < len(self.columns)  # a sort's, a filter's or a header's: one of them
        try:
            fields = attrs.fields_dict(attrs.resolve_types(self.record_type))
        except TypeError:  # a table not knowing its records' type: its cells are text
            return str
        field = fields.get(self.columns[column].field)
        return str if field is None else field.type

    @override
    def _cell_value(self, row: int, column: int) -> Any:
        # the rows are the records' cells, under their columns
        assert row < len(self.records)
        assert column < len(self.columns)
        return _sort_value(getattr(self.records[row], self.columns[column].field))

    @override
    def _emit_edit(self, row: int, column: int, text: str) -> bool:
        old = self.records[row]
        name = self.columns[column].field
        field_type: Any = attrs.fields_dict(attrs.resolve_types(type(old)))[name].type
        try:
            value = _parse_cell(text, field_type)
        except _BAD_STATE_ERRORS as error:
            main_view = None if self._main_view is None else self._main_view()
            if main_view is not None:
                message = self.tr('{header}: "{text}" isn\'t a valid value')
                main_view.notify(
                    message.format(header=self.headers[column], text=text), LogType.ERROR
                )
            raise EditRefusedError from error
        # `old` as `Any`: mypy's attrs plugin doesn't take a bound type variable
        new: RecordT = attrs.evolve(cast("Any", old), **{name: value})
        assert self._edited_rows is not None  # set by `emit_cell_edited`, its only caller
        # as the table will show it, to keep it selected once the records come back
        self._edited_rows[row] = self._cells(new, self.columns)
        records, rows = self.records, self.rows
        super()._emit_edit(row, column, text)
        self.record_edited.emit(old, new)
        if self.records is not records or self.rows is not rows:
            return False
        self.records = [*records[:row], new, *records[row + 1 :]]
        return True


@attrs.frozen
class SourceColumn:
    """A column of a `TableSource`: the values it holds, under `header`."""

    #: the name the source knows the column by, e.g. a record's field or a query's column
    name: str
    header: str
    #: the type of its values, which sets how they sort and filter (see `column_kind`)
    type: Any = str


@attrs.frozen
class Sort:
    """The order of a table's rows: by the values of the column named `column`."""

    column: str
    descending: bool = False


IdT = TypeVar("IdT")


class TableSource(Protocol[IdT]):
    """The rows of a large table, each known by its id, which the table reads in windows.

    The source sorts, searches and filters its rows itself (e.g. in SQL), so that a table
    never reads them all: it asks once for the ids of the rows it shows, in order, then
    for the cells of the rows on screen. `changed` says the rows changed, so the table
    reads them again. An id is a hashable value that stays its row's own while the rows
    change (e.g. a primary key), so that a table's selection stays on its rows.
    `ListSource` is a source of records in memory.

    A source whose ids are only positions also has a ``row_ids_scope`` attribute: a new
    object each time that new rows replace the others, which clears a table's selection,
    unless the source had no rows before.
    """

    @property
    def columns(self) -> Sequence[SourceColumn]:
        """Get the columns, in the order a table shows them."""
        ...

    @property
    def changed(self) -> SignalNoArgs:
        """Get the signal emitted once the rows changed."""
        ...

    def count(self) -> int:
        """Get the number of rows, before any search or filter."""
        ...

    def ordered_ids(
        self, sort: Optional[Sort], search: str, filters: Mapping[str, Filter]
    ) -> Sequence[IdT]:
        """Get the ids of the rows that `search` and `filters` pass, in the order of `sort`.

        `search` keeps the rows where the cell of a text column contains it, ignoring case;
        a blank one keeps every row. `filters` holds a `Filter` by column name (see
        `parse_filter`), which a cell passes as `Filter.matches` says. `sort` orders the
        rows by a column's values, text ignoring case, the empty cells last in both orders
        and equal cells in the source's order. Without it, the rows keep the source's
        order. Raise `ValueError` for a column the source doesn't have.
        """
        ...

    def cells(self, ids: Sequence[IdT], columns: Sequence[str]) -> Mapping[IdT, Sequence[Any]]:
        """Get the values of the rows `ids` in `columns`, by id; an id now gone is left out.

        Raise `ValueError` for a column the source doesn't have.
        """
        ...


class ListSource(Generic[RecordT]):
    """A `TableSource` of `attrs` records in memory: a row per record, a column per header.

    Build it with the records' type and the headers by field:
    ``ListSource(Room, {"name": T("Room"), "temperature": T("Temperature")})``. A row's id
    is its index in `records`, or its `id_field` when it has one: then new records keep a
    table's selection on the same records. Assign new `records` to change the rows, which
    emits `changed`. It sorts, searches and filters as a `RecordTableView` does: an enum
    by its text, as shown.
    """

    def __init__(
        self,
        record_type: type[RecordT],
        headers: Mapping[str, str],
        records: Sequence[RecordT] = (),
        *,
        id_field: Optional[str] = None,
    ) -> None:
        fields = attrs.fields_dict(attrs.resolve_types(record_type))
        for name in [*headers, *([] if id_field is None else [id_field])]:
            if name not in fields:
                msg = f"Cannot build a ListSource of {record_type.__name__}: no field {name!r}."
                raise ValueError(msg)
        self._columns = {
            name: SourceColumn(name, header, fields[name].type) for name, header in headers.items()
        }
        self._id_field = id_field
        self._changed = SignalNoArgs()
        self._records: tuple[RecordT, ...] = ()
        #: the records by id, in their order
        self._rows: dict[Hashable, RecordT] = {}
        self._set_records(records)

    @property
    def columns(self) -> Sequence[SourceColumn]:
        return tuple(self._columns.values())

    @property
    def changed(self) -> SignalNoArgs:
        return self._changed

    @property
    def records(self) -> Sequence[RecordT]:
        return self._records

    @records.setter
    def records(self, records: Sequence[RecordT]) -> None:
        self._set_records(records)
        self._changed.emit()

    def count(self) -> int:
        return len(self._records)

    def _set_records(self, records: Sequence[RecordT]) -> None:
        rows = {
            index if self._id_field is None else getattr(record, self._id_field): record
            for index, record in enumerate(records)
        }
        if len(rows) != len(records):
            msg = f"Cannot set the records of a ListSource: two have the same {self._id_field}."
            raise ValueError(msg)
        self._records = tuple(records)
        self._rows = rows
        #: a new object for new rows: an index names another record in them (see `TableSource`)
        self.row_ids_scope = None if self._id_field is not None else object()

    def ordered_ids(
        self, sort: Optional[Sort], search: str, filters: Mapping[str, Filter]
    ) -> list[Hashable]:
        for name in [*filters, *([] if sort is None else [sort.column])]:
            self._column(name)
        needle = search.strip().casefold()
        searched = [
            column.name
            for column in self._columns.values()
            if column_kind(column.type) is ColumnKind.TEXT
        ]
        # the records once: in a job, the main thread may assign new ones meanwhile
        rows = self._rows
        ids = [
            row_id
            for row_id, record in rows.items()
            if (
                needle == ""
                or any(needle in self._text(record, name).casefold() for name in searched)
            )
            and all(
                row_filter.matches(self._value(record, name), self._text(record, name))
                for name, row_filter in filters.items()
            )
        ]
        if sort is None:
            return ids
        return _sorted_by(
            ids,
            lambda row_id: self._value(rows[row_id], sort.column),
            lambda row_id: self._text(rows[row_id], sort.column),
            is_text=column_kind(self._column(sort.column).type) is ColumnKind.TEXT,
            descending=sort.descending,
        )

    def cells(self, ids: Sequence[Hashable], columns: Sequence[str]) -> dict[Hashable, list[Any]]:
        names = [self._column(name).name for name in columns]
        rows = self._rows  # once, as `ordered_ids` does
        return {
            row_id: [getattr(rows[row_id], name) for name in names]
            for row_id in ids
            if row_id in rows
        }

    def _column(self, name: str) -> SourceColumn:
        column = self._columns.get(name)
        if column is None:
            msg = f"Cannot read the column {name!r} of a ListSource: it has none of this name."
            raise ValueError(msg)
        return column

    @staticmethod
    def _value(record: Any, name: str) -> Any:
        return _sort_value(getattr(record, name))

    @staticmethod
    def _text(record: Any, name: str) -> str:
        return _cell_text(getattr(record, name))


#: the text of a large table: what the web says without rows, and its export's action
SOURCE_TABLE_TEXTS: Mapping[str, str] = {"empty": T("No rows"), "export": T("Export CSV")}

#: the rows a `SourceTableView` reads from its source at once, from a multiple of it on
SOURCE_TABLE_WINDOW = 200
#: the rows whose values a `SourceTableView` keeps, the ones read last
SOURCE_TABLE_CACHE = 1_000
#: the rows from which a `SourceTableView` orders its source's in a job, on Qt and Textual
SOURCE_TABLE_JOB_ROWS = 100_000
#: a table's row ids before its first source
_NO_ROW_IDS = object()


class _WeakCallback:
    """A view's method connected to a signal, held weakly, and called no more once dropped.

    So a source outliving its table (e.g. the model's) keeps no table alive, and calls
    none that replaced it.
    """

    def __init__(self, method: Callable[[], None]) -> None:
        self._method: Optional[weakref.WeakMethod[Callable[[], None]]] = weakref.WeakMethod(method)

    def drop(self) -> None:
        self._method = None

    def __call__(self) -> None:
        method = None if self._method is None else self._method()
        if method is not None:
            method()


class _Order(NamedTuple):
    """The rows a `SourceTableView` shows, as its source ordered them."""

    #: the source's rows' count, if counted with the order
    total: Optional[int]
    ids: Sequence[Any]
    #: the ids selected when the order was asked that it shows
    shown_selected: frozenset[Any]


def _ordered_ids(
    _job: Optional[Job[_Order]],
    source: TableSource[Any],
    settings: tuple[Optional[Sort], str, Mapping[str, Filter]],
    *,
    is_counting: bool,
    selected: frozenset[Any],
) -> _Order:
    """Ask `source` for its rows' count, if `is_counting`, then the ids of those shown.

    `settings` are the sort, the search and the filters the source orders them by. Then
    find which ids of `selected` the order shows: in a job, this pass over every id runs
    on the job's thread too.
    """
    total = source.count() if is_counting else None
    ids = _compact_ids(source.ordered_ids(*settings))
    shown = frozenset(row_id for row_id in ids if row_id in selected) if selected else frozenset()
    return _Order(total, ids, shown)


def _compact_ids(ids: Sequence[Any]) -> Sequence[Any]:
    """Keep integer ids in an `array` (8 bytes each), any other ids in a list."""
    if isinstance(ids, array.array) and ids.typecode == "q":
        return ids  # e.g. `SqliteSource`'s, read into one: no copy
    if all(isinstance(row_id, int) and not isinstance(row_id, bool) for row_id in ids):
        with contextlib.suppress(OverflowError):
            return array.array("q", ids)
    return list(ids)


@define_view
class SourceTableView(View):
    """A large table, whose rows a source keeps and the table reads a window at a time.

    `source` (a `TableSource`) sorts, searches and filters the rows. For each
    `sort_column`, `sort_descending`, `search` and `filters`, the view asks it once for
    the ids of the rows shown, in order, and keeps only these ids (in an `array` when
    they are integers). `rows` gives the cells of the rows at some positions, formatted
    as `column_formats` says. It reads them from the source by windows of
    `SOURCE_TABLE_WINDOW` rows, and keeps the values of the last `SOURCE_TABLE_CACHE` rows.
    The source's `changed` makes it read the order and the cells again. A source of
    `SOURCE_TABLE_JOB_ROWS` rows or more orders them in a job on Qt and Textual
    (`is_ordering`), and `ordered` emits once the rows have their new order.

    The columns are the source's, by name: `sort_column`, the keys of `filters` and of
    `column_formats`. A filter is the text the user typed (see `parse_filter`), and the
    search looks in the text columns. The user selects rows as `selection_mode` allows:
    `selected_ids` holds their ids, and `selection_changed` emits them when the user
    changes them. The ids the app sets are kept as they are. A new order (a search, a
    filter, the source's `changed`) drops the selected rows it hides, and
    `selection_changed` emits. `row_activated` emits a row's id (a double click, Enter).

    A study saves the settings and `selected_ids`, as JSON values (e.g. integers), and
    never the rows or the source: the app gives the view its source again.

    Each backend scrolls the rows, drawing only those around the view. A click on a
    column's header sorts by it (`sort_by`). A click on a row selects it (`select_at`);
    on Qt and Textual, Shift extends the selection (`extend_to`), and a double click or
    Enter activates the row (`activate_at`). Ctrl+C copies the selected rows to the
    clipboard (`selection_text`). Export CSV writes the rows shown to a file
    (`export_csv`): Qt's button and context menu, Textual's key `e`, the web's link above the
    rows.
    `export_filename` None takes Export CSV away, e.g. from a list with nothing to keep.

    While `filterable_columns` names columns, a filter bar shows above the rows, as a
    `TableView`'s: a search, "+ Filter" opening an editor of a column and a value, and the
    filters as chips. It counts the rows shown while some are hidden (`count_text`).
    """

    _renderer_key = "source_table"

    def _check_sort_column(self, _attribute: attrs.Attribute[Any], column: Optional[str]) -> None:
        if column is not None:
            self._source_column(column, "sort by")

    def _check_filters(self, _attribute: attrs.Attribute[Any], filters: dict[str, str]) -> None:
        for column, text in filters.items():
            parse_filter(text, self._source_column(column, "filter").type)

    def loadable(self, name: str, value: Any) -> Any:
        """Get the part of the saved filters (`name`) that the source's columns still take."""
        if name != "filters":
            return value
        names = None if self.source is None else {c.name for c in self.source.columns}
        return {
            column: text
            for column, text in value.items()
            if (names is None or column in names) and self.filter_error(column, text) is None
        }

    def _check_selected_ids(self, _attribute: attrs.Attribute[Any], ids: list[Any]) -> None:
        name = type(self).__name__
        if self.selection_mode is SelectionMode.SINGLE and len(ids) > 1:
            msg = f"Cannot set {name}.selected_ids to {ids}: the table selects a single row."
            raise ValueError(msg)
        if len(set(ids)) != len(ids):
            msg = f"Cannot set {name}.selected_ids to {ids}: a row is selected twice."
            raise ValueError(msg)

    def _reconcile_source(
        self, attribute: attrs.Attribute[Any], source: Optional[TableSource[Any]]
    ) -> Optional[TableSource[Any]]:
        """Read the new source's rows, and read them again each time they change.

        The renderer shows the new source's columns, e.g. in the filter bar. The filters
        and the sort on columns it doesn't have go: they'd filter and sort nothing, and
        the bar couldn't show them.
        """
        set_value(self, attribute.name, source)
        if source is not None:
            self._drop_other_columns_settings(source)
        if self._listener is not None:
            # the old source's `changed` keeps it, inert: a signal can't drop one callback
            self._listener.drop()
            self._listener = None
        if source is not None:
            self._listener = _WeakCallback(self._read_source_again)
            source.changed.connect(self._listener)
        self._source_changed()
        renderer = self.renderer
        if isinstance(renderer, (Renderer, RendererContainer)):
            renderer.refresh_attribute(attribute.name, source)
        return source

    def _drop_other_columns_settings(self, source: TableSource[Any]) -> None:
        """Drop the filters and the sort on columns `source` doesn't have, e.g. set before it."""
        names = {column.name for column in source.columns}
        fields = attrs.fields(cast("type[AttrsInstance]", type(self)))
        filters = {name: text for name, text in self.filters.items() if name in names}
        if filters != self.filters:
            _store(self, fields.filters, filters)
        if self.sort_column is not None and self.sort_column not in names:
            _store(self, fields.sort_column, None)
            _store(self, fields.sort_descending, value=False)

    def _reconcile_mode(
        self, attribute: attrs.Attribute[Any], mode: SelectionMode
    ) -> SelectionMode:
        """Keep only the first selected row when the table comes to select a single one."""
        if mode is SelectionMode.SINGLE and len(self.selected_ids) > 1:
            self.selected_ids = self.selected_ids[:1]
        return cast("SelectionMode", notify_renderer(self, attribute, mode))

    def _reorder(self, attribute: attrs.Attribute[Any], value: Any) -> Any:
        """Read the order of the rows as `value` sorts or filters them."""
        if getattr(self, attribute.name) == value:
            return value
        _store(self, attribute, value)
        self._read_order()
        return value

    # first: the settings check their columns against it
    source: Optional[TableSource[Any]] = attrs.field(
        default=None, on_setattr=_reconcile_source, repr=False, metadata={OMIT: True}
    )
    #: the format of each column's values, by column name (e.g. ``".6g"``): `format`'s
    column_formats: dict[str, str] = attrs.field(factory=dict[str, str])
    #: the text the web shows (see `SOURCE_TABLE_TEXTS`)
    texts: dict[str, str] = attrs.field(
        factory=lambda: dict(SOURCE_TABLE_TEXTS), metadata={UI_TEXT: True}
    )
    #: the text of the filter bar, by what it's for (see `FILTER_TEXTS`)
    filter_texts: dict[str, str] = attrs.field(
        factory=lambda: dict(FILTER_TEXTS), metadata={UI_TEXT: True}
    )
    #: the columns the user filters in the table's bar, by name: none hides the bar
    filterable_columns: list[str] = attrs.field(factory=list[str])
    #: the name Export CSV offers for the file; the app's, not a study's. None: no Export CSV
    export_filename: Optional[str] = attrs.field(default="table.csv", metadata={OMIT: True})
    selection_mode: SelectionMode = attrs.field(
        default=SelectionMode.SINGLE, on_setattr=_reconcile_mode
    )
    sort_column: Optional[str] = attrs.field(
        default=None,
        validator=[_check_sort_column],
        on_setattr=[attrs.setters.validate, _reorder],
    )
    sort_descending: bool = attrs.field(default=False, on_setattr=_reorder)
    #: text the shown rows contain in a text column, ignoring case
    search: str = attrs.field(default="", on_setattr=_reorder)
    #: the filters by column name, as typed (see `parse_filter`)
    filters: dict[str, str] = attrs.field(
        factory=dict[str, str],
        validator=[_check_filters],
        on_setattr=[attrs.setters.validate, _reorder],
    )

    def _reconcile_selected(self, attribute: attrs.Attribute[Any], ids: list[Any]) -> list[Any]:
        """Keep the selected ids in a set too, for `is_selected`, and notify the renderer."""
        object.__setattr__(self, "_selected", set(ids))
        return cast("list[Any]", notify_renderer(self, attribute, ids))

    # after the settings: loading saved state selects the rows once in their order
    selected_ids: list[Any] = attrs.field(
        factory=list,
        validator=[_check_selected_ids],
        on_setattr=[attrs.setters.validate, _reconcile_selected],
    )
    # signals
    selection_changed: Signal[list[Any]] = attrs.Factory(Signal[list[Any]])
    row_activated: Signal[Any] = attrs.Factory(Signal[Any])
    #: the rows shown have a new order, e.g. to show `row_count`: a sort, a search, a
    #: filter, the source's change
    ordered: SignalNoArgs = attrs.Factory(SignalNoArgs)
    #: the ids of the rows shown, in order
    _order: Sequence[Any] = attrs.field(factory=list, init=False, repr=False, metadata={OMIT: True})
    #: the values of the rows read last, by id, the oldest first
    _cache: OrderedDict[Any, Sequence[Any]] = attrs.field(
        factory=OrderedDict, init=False, repr=False, metadata={OMIT: True}
    )
    #: `selected_ids`, as a set
    _selected: set[Any] = attrs.field(factory=set, init=False, repr=False, metadata={OMIT: True})
    #: the number of the source's rows, before any search or filter
    _total: int = attrs.field(default=0, init=False, repr=False, metadata={OMIT: True})
    #: the position the user selected last, where a range they extend starts
    _anchor: Optional[int] = attrs.field(
        default=None, init=False, repr=False, metadata={OMIT: True}
    )
    #: the source whose ids `_order` holds
    _order_source: Optional[TableSource[Any]] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: which rows the ids of the last source name (see `_drop_selection_of_other_rows`)
    _row_ids_scope: Optional[object] = attrs.field(
        default=_NO_ROW_IDS, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: a job is ordering the rows
    _ordering: bool = attrs.field(default=False, init=False, repr=False, metadata={OMIT: True})
    #: the main view's jobs' `running_changed` is connected
    _watches_jobs: bool = attrs.field(default=False, init=False, repr=False, metadata={OMIT: True})
    #: connected to the source's `changed`, until the source is replaced
    _listener: Optional[_WeakCallback] = attrs.field(
        default=None, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: the requests for the order: each new one makes the orders asked before outdated
    _order_request: int = attrs.field(default=0, init=False, repr=False, metadata={OMIT: True})
    #: the latest request waits for the job running to be over
    _order_pending: bool = attrs.field(default=False, init=False, repr=False, metadata={OMIT: True})
    #: the source changed since `_total` counted its rows: the next order counts them
    _recount: bool = attrs.field(default=False, init=False, repr=False, metadata={OMIT: True})
    #: whether new rows cleared the selection, not yet emitted: they are still being ordered
    _selection_cleared: bool = attrs.field(
        default=False, init=False, repr=False, metadata={OMIT: True}
    )
    #: whether the source of `_row_ids_scope` had no rows, so that its ids named none
    _scope_had_no_rows: bool = attrs.field(
        default=False, init=False, repr=False, metadata={OMIT: True}
    )

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._selected = set(self.selected_ids)
        self.source = self.source

    @property
    def headers(self) -> list[str]:
        """Get the headers of the source's columns, in its order."""
        if self.source is None:
            return []
        return [translate_again(column.header, self._tr) for column in self.source.columns]

    @property
    def column_names(self) -> list[str]:
        """Get the names of the source's columns, in its order."""
        return [] if self.source is None else [column.name for column in self.source.columns]

    @property
    def row_count(self) -> int:
        """Get the number of rows shown: the rows the search and the filters pass."""
        return len(self._order)

    def sort_by(self, column: str) -> None:
        """Sort as a click on the column's header does: ascending, descending, then not.

        The source orders the rows once, for the column and the direction together.
        """
        fields = attrs.fields(cast("type[AttrsInstance]", type(self)))
        self._check_sort_column(fields.sort_column, column)
        if self.sort_column != column:
            settings: tuple[Optional[str], bool] = (column, False)
        elif not self.sort_descending:
            settings = (column, True)
        else:
            settings = (None, False)
        for attribute, value in zip((fields.sort_column, fields.sort_descending), settings):
            _store(self, attribute, value)
        self._read_order()

    @property
    def count_text(self) -> str:
        """Count the rows shown, while the search or the filters hide some: else "".

        E.g. "1,234 of 1,000,000", in `filter_texts`' words.
        """
        if self.row_count == self._total or self._order_source is not self.source:
            return ""  # all shown, or the source's rows not ordered yet
        count = self.filter_texts.get("count", "")
        return count.format(shown=f"{self.row_count:,}", total=f"{self._total:,}")

    def filter_error(self, column: str, text: str) -> Optional[str]:
        """Say why `text` can't filter `column`, translated; None if it can."""
        return _filter_error(self.tr, text, self._source_column(column, "filter").type)

    def filter_takes_pattern(self, column: str) -> bool:
        """Tell whether a regular expression filters `column`: a text column."""
        column_type = self._source_column(column, "filter").type
        return take_filter_patterns() and column_kind(column_type) is ColumnKind.TEXT

    def filter_placeholder(self, column: str, *, is_pattern: bool = False) -> str:
        """Hint at what filters `column`, translated: a regular expression, or else text."""
        field_type = self._source_column(column, "filter").type
        return _filter_placeholder(self.tr, field_type, is_pattern=is_pattern)

    def filter_chip(self, column: str) -> str:
        """Show the filter of `column` as its chip does: its header, then the text typed."""
        header = self.header(column)
        takes_pattern = self.filter_takes_pattern(column)
        return _filter_chip(
            self.filter_texts, header, self.filters[column], takes_pattern=takes_pattern
        )

    def header(self, column: str) -> str:
        """Get the header of the source's column `column`, translated."""
        names = self.column_names
        return self.headers[names.index(column)] if column in names else column

    def selection_text(self) -> str:
        """Get the selected rows as Ctrl+C copies them: tab-separated text, a line per row.

        The rows in their order, the cells as the table shows them, without the headers,
        as a spreadsheet takes them. A tab or a line break in a cell is a space. The rows
        are read from the source a window at a time, outside the table's cache.
        """
        if self.source is None or len(self._selected) == 0:
            return ""
        selected = self._selected
        ids = [row_id for row_id in self._order if row_id in selected]
        columns = self.source.columns
        names = [column.name for column in columns]
        lines: list[str] = []
        for start in range(0, len(ids), SOURCE_TABLE_WINDOW):
            window = ids[start : start + SOURCE_TABLE_WINDOW]
            values = self.source.cells(window, names)
            for row_id in window:
                cells = self._cells(columns, values.get(row_id, ()))
                lines.append("\t".join(" ".join(cell.split()) for cell in cells))
        return "\n".join(lines)

    def csv_chunks(self) -> Iterator[str]:
        """Get the rows shown as CSV, in pieces: the headers, then a window of rows each.

        The rows in their order, each value in full, not as `column_formats` shows it:
        None as an empty cell, an enum by its value, a date as ISO. The order is the one
        shown at the call: a new order, while the pieces are read, changes none of them.
        The rows are read from the source a window at a time, outside the table's cache.
        """
        source, order = self.source, self._order
        if source is None:
            return iter(())
        names = [column.name for column in source.columns]
        headers = self.headers

        def chunks() -> Iterator[str]:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(headers)
            yield buffer.getvalue()
            for start in range(0, len(order), SOURCE_TABLE_WINDOW):
                buffer.seek(0)
                buffer.truncate()
                window = order[start : start + SOURCE_TABLE_WINDOW]
                values = source.cells(window, names)
                writer.writerows(
                    [_cell_text(value) for value in values.get(row_id, [None] * len(names))]
                    for row_id in window
                )
                yield buffer.getvalue()

        return chunks()

    def export_csv(self, path: Path) -> None:
        """Write the rows shown to the CSV file `path`, in UTF-8, as `csv_chunks` gives them.

        In an app, a job writes them, the app staying responsive, and the status bar says
        when it's done, or a notification why it failed. Else they are written before the
        call returns.
        """
        chunks, count = self.csv_chunks(), self.row_count
        main_view = None if self._main_view is None else self._main_view()
        if main_view is None:
            _write_csv(None, chunks, path)
            return
        job = main_view.jobs.start(_write_csv, chunks, path)
        done = self.tr("Exported {count} rows to {name}.")
        failed = self.tr("Can't export to {name}: {error}.")

        def report(is_written: bool) -> None:
            if is_written:
                main_view.status_bar.show_message(done.format(count=f"{count:,}", name=path.name))

        def report_failure(error: Exception) -> None:
            main_view.notify(failed.format(name=path.name, error=error), LogType.ERROR)

        job.finished.connect(report)
        job.failed.connect(report_failure)

    def is_selected(self, row_id: Any) -> bool:
        """Tell whether the row `row_id` is selected."""
        return row_id in self._selected

    def select_at(self, position: int) -> None:
        """Select the row at `position` as the user's click does, and say so if it changed.

        One row at most selects it; any number of rows add it, or remove it if selected.
        """
        ids = self.ids(position, position + 1)
        if len(ids) == 0:
            return
        self._anchor = position
        (row_id,) = ids
        if self.selection_mode is SelectionMode.SINGLE:
            selected = [row_id]
        elif row_id in self._selected:
            selected = [selected_id for selected_id in self.selected_ids if selected_id != row_id]
        else:
            selected = [*self.selected_ids, row_id]
        self._select(selected)

    def extend_to(self, position: int) -> None:
        """Add the rows from the one selected last to `position`, as a Shift+click does.

        One row at most, or none selected last: as `select_at`.
        """
        if self.selection_mode is SelectionMode.SINGLE or self._anchor is None:
            self.select_at(position)
            return
        first, last = sorted((self._anchor, position))
        added = [row_id for row_id in self.ids(first, last + 1) if row_id not in self._selected]
        self._select([*self.selected_ids, *added])

    def activate_at(self, position: int) -> None:
        """Emit `row_activated` with the id of the row at `position`, as a double click."""
        ids = self.ids(position, position + 1)
        if len(ids) > 0:
            self.row_activated.emit(ids[0])

    def _select(self, selected: list[Any]) -> None:
        if selected != self.selected_ids:
            self.selected_ids = selected
            self.selection_changed.emit(selected)

    def ids(self, start: int, stop: int) -> list[Any]:
        """Get the ids of the rows shown from position `start` to `stop` (excluded)."""
        return list(self._order[max(start, 0) : max(stop, 0)])

    def rows(self, start: int, stop: int) -> list[tuple[Any, list[str]]]:
        """Get the id and the formatted cells of the rows shown from `start` to `stop`.

        A row gone from the source since the order was read has empty cells, until its
        `changed` reads the order again.
        """
        ids = self.ids(start, stop)
        if self.source is None or len(ids) == 0:
            return []
        for row_id in ids:  # the latest read: the windows read next don't evict them
            if row_id in self._cache:
                self._cache.move_to_end(row_id)
        if any(row_id not in self._cache for row_id in ids):
            self._read_windows(self.source, max(start, 0), max(start, 0) + len(ids))
        columns = self.source.columns
        empty = [""] * len(columns)
        rows: list[tuple[Any, list[str]]] = []
        for row_id in ids:
            values = self._cache.get(row_id)
            cells = empty if values is None else self._cells(columns, values)
            rows.append((row_id, cells))
        return rows

    def _read_windows(self, source: TableSource[Any], start: int, stop: int) -> None:
        """Read the values of the windows of rows from `start` to `stop` into the cache."""
        first = start - start % SOURCE_TABLE_WINDOW
        last = min(-(-stop // SOURCE_TABLE_WINDOW) * SOURCE_TABLE_WINDOW, len(self._order))
        ids = [row_id for row_id in self._order[first:last] if row_id not in self._cache]
        values = source.cells(ids, [column.name for column in source.columns])
        for row_id in ids:
            # a row gone: its cells are empty until the source says it changed
            self._cache[row_id] = values.get(row_id, ())
        while len(self._cache) > max(SOURCE_TABLE_CACHE, last - first):
            self._cache.popitem(last=False)

    def _cells(self, columns: Sequence[SourceColumn], values: Sequence[Any]) -> list[str]:
        if len(values) == 0:  # gone
            return [""] * len(columns)
        return [
            self._format(value, self.column_formats.get(column.name, ""))
            for column, value in zip(columns, values)
        ]

    @staticmethod
    def _format(value: Any, spec: str) -> str:
        """Format a cell's value: None as an empty cell, an enum by its text, else by `spec`."""
        if value is None or spec == "" or isinstance(value, enum.Enum):
            return _cell_text(value)
        try:
            return format(value, spec)
        except (TypeError, ValueError):  # a format for another type of value
            return _cell_text(value)

    def _source_changed(self) -> None:
        """Count the rows of the source, new or changed, then order them."""
        source = self.source
        self._selection_cleared |= self._drop_selection_of_other_rows(source)
        self._cache.clear()
        if source is None:
            self._total, self._recount = 0, False
        elif source is not self._order_source or self._ordering_jobs() is None:
            # a new source: its count says whether a job orders its rows
            self._total, self._recount = source.count(), False
        else:
            self._recount = True  # in the ordering job, the rows' count costing a query too
        if source is not self._order_source and len(self._order) > 0:
            # the old source's ids: no row until the new source's order, selected ones kept
            self._order, self._order_source = [], None
            self._refresh_order()
        self._read_order()

    def _announce_cleared_selection(self) -> None:
        """Emit the selection cleared by new rows, now ordered, for what a callback reads."""
        is_announced, self._selection_cleared = self._selection_cleared, False
        # a selection made while a job ordered the rows was emitted, and is the current one
        if is_announced and len(self.selected_ids) == 0:
            self.selection_changed.emit([])

    def _drop_selection_of_other_rows(self, source: Optional[TableSource[Any]]) -> bool:
        """Clear the selection if `source`'s ids name other rows, and tell whether it did.

        A row's position in a frame is its id there only: the same number in new rows is
        another row. The first source keeps the selection, which a study may have restored,
        and so does a source that replaces one without rows: those ids named no row.
        """
        if source is None:
            return False
        previous, had_no_rows = self._row_ids_scope, self._scope_had_no_rows
        # optional: a source whose ids are its rows' own has none
        self._row_ids_scope = getattr(source, "row_ids_scope", None)
        # counted only for positions, in memory: another source's count can cost a query
        self._scope_had_no_rows = self._row_ids_scope is not None and source.count() == 0
        if (
            previous is _NO_ROW_IDS
            or had_no_rows
            or previous is self._row_ids_scope
            or len(self.selected_ids) == 0
        ):
            return False
        self.selected_ids = []
        return True

    @property
    def total(self) -> int:
        """Get the number of the source's rows, before the search and the filters."""
        return self._total

    @property
    def is_ordering(self) -> bool:
        """Tell whether a job is ordering the rows, the old order shown meanwhile."""
        return self._ordering

    def _read_order(self) -> None:
        """Ask the source for the ids of the rows shown, in their order, then show them.

        A source of `SOURCE_TABLE_JOB_ROWS` rows or more, in an app whose window the main
        thread draws (Qt, Textual), orders them in a job, the app staying responsive
        meanwhile (`is_ordering`). One job at a time: the settings changed while it runs
        order the rows again once it's over, its order dropped.
        """
        # any order asked before, a job's still running, is outdated
        self._order_request += 1
        self._order_pending = False
        source = self.source
        jobs = self._ordering_jobs()
        if source is None:
            self._show_order(None, _Order(0, [], frozenset()))
        elif jobs is None:
            settings = self._order_settings(source)
            selected = frozenset(self._selected)
            order = _ordered_ids(
                None, source, settings, is_counting=self._recount, selected=selected
            )
            self._show_order(source, order, selected)
        elif self._ordering:
            self._order_pending = True
        else:
            request = self._order_request
            self._set_ordering(is_ordering=True)
            settings = self._order_settings(source)
            # a copy: the user selects rows of the old order while the job runs
            selected = frozenset(self._selected)
            job = jobs.start(
                _ordered_ids, source, settings, is_counting=self._recount, selected=selected
            )
            job.finished.connect(lambda order: self._ordered(request, order, selected))
            job.failed.connect(lambda _error: self._ordered(request, None))

    def _ordering_jobs(self) -> Optional[Jobs]:
        """Get the jobs to order the rows in, or None to order them on the main thread."""
        main_view = None if self._main_view is None else self._main_view()
        if main_view is None or self._total < SOURCE_TABLE_JOB_ROWS:
            return None
        renderer = main_view.renderer
        if not isinstance(renderer, MainRenderer) or not renderer.draws_on_main_thread:
            return None
        if not self._watches_jobs:
            # New and Open drop the jobs, the ordering's too: its order never comes
            main_view.jobs.running_changed.connect(self._jobs_running)
            self._watches_jobs = True
        return main_view.jobs

    def _jobs_running(self, is_running: bool) -> None:
        if not is_running and self._ordering:  # dropped
            self._set_ordering(is_ordering=False)
            self._read_order()

    def _ordered(
        self, request: int, order: Optional[_Order], selected: frozenset[Any] = frozenset()
    ) -> None:
        """Show the order a job got for `request`, unless a newer one was asked meanwhile.

        A newer request waiting for the job orders now; one answered at once (e.g. the
        source got smaller) is shown already: the job's order is dropped.
        """
        self._set_ordering(is_ordering=False)
        if request == self._order_request:
            if order is not None:
                self._show_order(self.source, order, selected)
            else:  # it failed, logged: the old order stays
                self._announce_cleared_selection()
        elif self._order_pending:
            self._read_order()

    def _set_ordering(self, *, is_ordering: bool) -> None:
        self._ordering = is_ordering
        renderer = self.renderer
        if isinstance(renderer, (Renderer, RendererContainer)):
            renderer.refresh_attribute("is_ordering", is_ordering)

    def _refresh_order(self) -> None:
        """Give the renderer the new `row_count`: it shows the rows from their new order."""
        self._anchor = None  # a position of the old order
        renderer = self.renderer
        if isinstance(renderer, (Renderer, RendererContainer)):
            renderer.refresh_attribute("row_count", self.row_count)

    def _read_source_again(self) -> None:
        self._source_changed()

    def _show_order(
        self,
        source: Optional[TableSource[Any]],
        order: _Order,
        asked: frozenset[Any] = frozenset(),
    ) -> None:
        """Show the rows of `order`, drop the selected ones it hides, emit `ordered`.

        `asked` holds the ids selected when the order was asked, whose shown ones the order
        found. Only the rows selected since are looked for in the order, on this thread.
        """
        if order.total is not None:
            self._total, self._recount = order.total, False
        self._order, self._order_source = order.ids, source
        self._refresh_order()
        emit_if_made(self, "ordered")  # most tables' isn't connected: don't make it
        if len(self.selected_ids) > 0:
            selected_since = self._selected - asked
            shown = order.shown_selected
            if selected_since:  # e.g. clicked while a job ordered: a pass over every id
                shown = shown | {row_id for row_id in order.ids if row_id in selected_since}
            kept = [row_id for row_id in self.selected_ids if row_id in shown]
            if kept != self.selected_ids:
                self.selected_ids = kept
                self.selection_changed.emit(kept)
        self._announce_cleared_selection()

    def _order_settings(
        self, source: TableSource[Any]
    ) -> tuple[Optional[Sort], str, dict[str, Filter]]:
        """Get what `source` orders the rows by: the sort, the search, the filters parsed."""
        columns = {column.name: column for column in source.columns}
        filters: dict[str, Filter] = {}
        for name, text in self.filters.items():
            # a filter its column no longer takes (e.g. a new source) filters nothing
            with contextlib.suppress(FilterError):
                if name in columns:
                    filters[name] = parse_filter(text, columns[name].type)
        sort = None
        if self.sort_column is not None and self.sort_column in columns:
            sort = Sort(self.sort_column, descending=self.sort_descending)
        return sort, self.search, filters

    def _source_column(self, name: str, action: str) -> SourceColumn:
        """Get the source's column `name`, for `action`; any column without a source yet."""
        if self.source is None:
            return SourceColumn(name, name)
        column = next((column for column in self.source.columns if column.name == name), None)
        if column is None:
            msg = f"Cannot {action} {type(self).__name__}'s column {name!r}: its source has none."
            raise ValueError(msg)
        return column


class SourceTableLike(Protocol):
    """What `SourceTableByPosition` reads and sets of a `SourceTableView`."""

    search: str
    filters: dict[str, str]
    sort_column: Optional[str]
    sort_descending: bool

    @property
    def headers(self) -> list[str]: ...
    @property
    def column_names(self) -> list[str]: ...
    @property
    def filter_texts(self) -> dict[str, str]: ...
    @property
    def filterable_columns(self) -> list[str]: ...
    def header(self, column: str) -> str: ...
    def filter_error(self, column: str, text: str) -> Optional[str]: ...
    def filter_takes_pattern(self, column: str) -> bool: ...
    def filter_placeholder(self, column: str, *, is_pattern: bool = False) -> str: ...
    def filter_chip(self, column: str) -> str: ...
    def sort_by(self, column: str) -> None: ...
    def select_at(self, position: int) -> None: ...
    def extend_to(self, position: int) -> None: ...


class SourceTableByPosition:
    """A large table as a backend's widgets know it: its columns by their positions.

    A `SourceTableView` knows its columns by name, and the widgets (a header, a filter bar,
    as a `TableView`'s) by position in its source. The renderers of every backend read
    and set the view through it, so the names map to positions in one place.
    """

    def __init__(self, view: SourceTableLike) -> None:
        self._view = view

    @property
    def headers(self) -> list[str]:
        return self._view.headers

    @property
    def filter_texts(self) -> dict[str, str]:
        return self._view.filter_texts

    @property
    def search(self) -> str:
        return self._view.search

    @search.setter
    def search(self, text: str) -> None:
        self._view.search = text

    @property
    def filters(self) -> dict[int, str]:
        names = self._view.column_names
        return {
            names.index(name): text for name, text in self._view.filters.items() if name in names
        }

    @filters.setter
    def filters(self, filters: dict[int, str]) -> None:
        names = self._view.column_names
        self._view.filters = {names[column]: text for column, text in filters.items()}

    @property
    def filterable_columns(self) -> list[int]:
        return [column for column, _header in self.bar_columns(self._view.filterable_columns)]

    @property
    def sort(self) -> Optional[tuple[int, bool]]:
        """Get the sorted column's position and whether it's descending; None if none."""
        names = self._view.column_names
        if self._view.sort_column not in names:
            return None
        return names.index(self._view.sort_column), self._view.sort_descending

    def bar_columns(self, filterable_columns: list[str]) -> list[tuple[int, str]]:
        """Get the position and the header of each of `filterable_columns`, as a bar lists them.

        Takes the names, as a renderer refreshes them before the view holds them.
        """
        names = self._view.column_names
        return [
            (names.index(name), self._view.header(name))
            for name in names
            if name in filterable_columns
        ]

    def chips(self, filters: dict[str, str]) -> list[tuple[int, str, str, str]]:
        """Get each of `filters` as a bar's chip, by name: as `bar_columns` takes them.

        Each its position, the chip's text, the text typed and the header.
        """
        names = self._view.column_names
        return [
            (
                names.index(name),
                self._view.filter_chip(name),
                filters[name],
                self._view.header(name),
            )
            for name in names
            if name in filters
        ]

    def filter_error(self, column: int, text: str) -> Optional[str]:
        return self._view.filter_error(self._name(column), text)

    def filter_takes_pattern(self, column: int) -> bool:
        return self._view.filter_takes_pattern(self._name(column))

    def filter_placeholder(self, column: int, *, is_pattern: bool = False) -> str:
        return self._view.filter_placeholder(self._name(column), is_pattern=is_pattern)

    def filter_chip(self, column: int) -> str:
        return self._view.filter_chip(self._name(column))

    def add_filter(self, column: int, text: str) -> None:
        """Filter the column at `column` with `text`, as the bar's Add does."""
        self.filters = {**self.filters, column: text}

    def remove_filter(self, column: int) -> None:
        """Stop filtering the column at `column`, as its chip's remove button does."""
        self.filters = {other: text for other, text in self.filters.items() if other != column}

    def clear_filters(self) -> None:
        self._view.filters = {}

    def sort_by(self, column: int) -> None:
        """Sort by the column at `column`, as a click on its header does."""
        names = self._view.column_names
        assert column < len(names)  # a header's
        self._view.sort_by(names[column])

    def select(self, position: int, *, is_extended: bool) -> None:
        """Select the row at `position`, as a click does: extended to it with Shift."""
        if is_extended:
            self._view.extend_to(position)
        else:
            self._view.select_at(position)

    def _name(self, column: int) -> str:
        return self._view.column_names[column]
