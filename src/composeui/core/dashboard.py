"""Shorter dashboard code: a main view, filters bound to a frame's columns, and frame helpers.

The helpers take any frame that `narwhals` reads (pandas, Polars, PyArrow...) and fill
ordinary views, or give plain values: no state is kept outside the views.
"""

from __future__ import annotations

import copy
import datetime
import decimal
import math
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar, Union, cast

import attrs
import narwhals.stable.v2 as nw
from typing_extensions import ParamSpec

from composeui.core.dataframesource import (
    DataFrameSource,
    _collected,
    _on_one_clock,
    _python_value,
)
from composeui.core.reactivity import untracked
from composeui.core.view import (
    ChartKind,
    ChartView,
    DateRangeInputMixin,
    FloatRangeSliderMixin,
    MainView,
    MultiValuesMixin,
    PageWidth,
    RangeSliderMixin,
    SourceTableView,
    StreamContent,
    View,
    child,
    define_view,
    view_fields,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path
    from typing import BinaryIO

    from narwhals.stable.v2.typing import IntoFrame
    from narwhals.typing import EagerAllowed, IntoBackend

__all__ = [
    "MAX_CHOICES",
    "MAX_COLUMNS",
    "MAX_PARQUET_METADATA_SIZE",
    "DashboardView",
    "bar_chart",
    "column_filter",
    "counts_of",
    "fill_filters",
    "filtered",
    "frame_content",
    "read_frame",
    "show_frame",
]

#: the most distinct values that a column's choice filter offers
MAX_CHOICES = 1000
#: the most columns of a CSV file that `read_frame` reads by default: a library can take seconds
#: to read a small file of many columns, e.g. pandas 4 s for a line of 16,385
MAX_COLUMNS = 1000
#: the largest description of its columns that a Parquet file read by `read_frame` holds
MAX_PARQUET_METADATA_SIZE = 16 * 1024 * 1024
#: the steps that `fill_filters` aims for between a decimal range's ends
_RANGE_STEPS = 100
#: the field metadata key of a filter's column (`column_filter`)
_FILTER_COLUMN = "composeui_filter_column"
#: the separators that a CSV file can use, the first winning a tie, and the longest first line
#: read to find it. Not `csv.Sniffer`: on a crafted file, it stops every session for seconds
_SEPARATORS = ",;\t|"
_MAX_HEADER_LENGTH = 64 * 1024
#: how a compressed file starts, which a frame's library would unpack: gzip, zstd, zlib, bzip2,
#: xz, zip and LZ4 (pandas and PyArrow unpack by the file's name). A small file can unpack to more
#: than the server's memory, whatever its size
_COMPRESSED_STARTS = (
    b"\x1f\x8b",
    b"\x28\xb5\x2f\xfd",
    b"\x78\x01",
    b"\x78\x5e",
    b"\x78\x9c",
    b"\x78\xda",
    *(b"BZh%d" % level for level in range(1, 10)),
    b"\xfd7zXZ\x00",
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x04\x22\x4d\x18",
)
#: the longest of `_COMPRESSED_STARTS`
_COMPRESSED_START_LENGTH = 6
#: how a Parquet file starts and ends, its description's length (4 bytes) before the end
_PARQUET_MARK = b"PAR1"
_PARQUET_FOOTER = 8

_P = ParamSpec("_P")
_ViewT = TypeVar("_ViewT", bound=View)
#: a view that `fill_filters` fills and `filtered` reads
_Filter = Union[MultiValuesMixin[Any], RangeSliderMixin, FloatRangeSliderMixin, DateRangeInputMixin]
_FILTER_TYPES = (MultiValuesMixin, RangeSliderMixin, FloatRangeSliderMixin, DateRangeInputMixin)


@define_view
class DashboardView(MainView):
    """A main view for a dashboard: wide, without the File menu of studies.

    A subclass that saves studies sets ``has_file_menu = True`` and its `extension`.
    """

    width = PageWidth.WIDE
    has_file_menu = False


def bar_chart(
    title: str,
    categories: Iterable[str],
    *,
    x_title: str = "",
    y_title: str = "",
    height: Optional[int] = None,
) -> ChartView:
    """Get a view field's default: a bar chart with a group of bars per category.

    E.g. ``by_hour: ChartView = bar_chart("Pickups by hour", HOURS)``.
    """
    return child(
        ChartView,
        kind=ChartKind.BAR,
        title=title,
        categories=list(categories),
        x_title=x_title,
        y_title=y_title,
        height=height,
    )


def column_filter(
    cls: Callable[_P, _ViewT], column: str, /, *args: _P.args, **kwargs: _P.kwargs
) -> _ViewT:
    """Get a view field's default: a `cls` view that filters the rows by a frame's `column`.

    E.g. ``bases: MultiComboBoxView[str] = column_filter(MultiComboBoxView[str], "Base")``,
    the arguments after the column going to `cls`. `fill_filters` gives it the column's
    values, and `filtered` keeps the rows that it accepts. `cls` is a choice of several
    values (`MultiComboBoxView`, `CheckListView`), a range slider (`RangeSliderView` for
    whole numbers, `FloatRangeSliderView`) or a `DateRangeInputView`, or one of their form
    rows, such as `LabelRowMultiComboBoxView`.
    """

    def build() -> _ViewT:
        # copied for each view built, as `child` does: a list among them is never shared
        return cls(*copy.deepcopy(args), **copy.deepcopy(kwargs))

    return cast("_ViewT", attrs.field(factory=build, metadata={_FILTER_COLUMN: column}))


def _filters_of(view: View) -> list[tuple[str, _Filter]]:
    """Get the filters that `view` and its child views hold, with their columns."""
    found: list[tuple[str, _Filter]] = []
    for field in view_fields(type(view)):
        # where the filters are isn't an input of the caller's reactive method: their choice is
        with untracked():
            value = getattr(view, field.name)
        column = field.metadata.get(_FILTER_COLUMN)
        if column is not None:
            if not isinstance(value, _FILTER_TYPES):
                msg = (
                    f"{type(view).__name__}.{field.name} can't filter a column: a filter is a "
                    "choice of several values, a range slider or a date range"
                )
                raise TypeError(msg)
            found.append((column, value))
        elif isinstance(value, View):
            found.extend(_filters_of(value))
    return found


def _checked_filters(view: View, schema: Any) -> list[tuple[str, _Filter]]:
    """Get the filters of `view`, refusing one of a column that the frame doesn't have."""
    found = _filters_of(view)
    for column, view_filter in found:
        if column not in schema:
            msg = f"The frame has no column {column!r} for {type(view_filter).__name__}"
            raise ValueError(msg)
    return found


def fill_filters(view: View, frame: IntoFrame) -> None:
    """Give each filter of `view` and its child views the values of its column in `frame`.

    A choice offers the column's values as texts, in order; a range slider and a date range
    take the column's smallest and largest values. Fill them from the whole frame, not from
    the rows filtered. Filled again, a filter keeps what the user chose: a choice the values
    still there, a range its ends, an end at its limit moving to the new limit.
    """
    native = nw.from_native(frame)
    schema = native.collect_schema()
    # the filters' fields are this method's outputs, not its inputs
    with untracked():
        for column, view_filter in _checked_filters(view, schema):
            values = native.select(column)
            if isinstance(view_filter, MultiValuesMixin):
                _fill_choices(view_filter, values, column, schema[column])
            elif isinstance(view_filter, (RangeSliderMixin, FloatRangeSliderMixin)):
                _fill_range(view_filter, values, column, schema[column])
            else:
                _fill_dates(view_filter, values, column, schema[column])


def filtered(frame: IntoFrame, view: View) -> Any:
    """Get the rows of `frame` that every filter of `view` and its child views accepts.

    A choice keeps the rows of its values, none while nothing is chosen. A range keeps the
    rows between its ends, both included. A filter of all its values, and an end at its
    limit (a range's first or last step, an empty date), keep every row, those without a
    value too. The frame comes back in its own library, lazy if it was.
    """
    native = nw.from_native(frame)
    schema = native.collect_schema()
    conditions = [
        condition
        for column, view_filter in _checked_filters(view, schema)
        for condition in _conditions(view_filter, column, schema[column])
    ]
    return (native.filter(*conditions) if conditions else native).to_native()


def _choice_texts(dtype: Any) -> Optional[Callable[[str], Any]]:
    """Get how a choice's text reads as a cell of a column of `dtype`; None if it can't."""
    if dtype in (nw.String, nw.Categorical, nw.Enum):
        return str
    if dtype.is_integer():
        return int
    if dtype == nw.Boolean:
        return lambda text: text == "True"
    return None


def _fill_choices(view: MultiValuesMixin[Any], values: Any, column: str, dtype: Any) -> None:
    if _choice_texts(dtype) is None:
        msg = (
            f"The column {column!r} of {dtype} can't be a choice: a choice takes texts, "
            "categories, whole numbers or booleans; filter it with a range"
        )
        raise TypeError(msg)
    unique = _collected(values.drop_nulls().unique().sort(column)).get_column(column)
    if len(unique) > MAX_CHOICES:
        msg = f"The column {column!r} has more than {MAX_CHOICES} values to choose from"
        raise ValueError(msg)
    # texts, so that each value's key is the value itself: never a position, which another
    # file's values would give to another value
    texts = [str(_python_value(value)) for value in unique.to_list()]
    was_all = view.selected == list(view.values.values())
    view.values = {text: text for text in texts}
    if was_all:
        view.selected = texts


def _number_limits(values: Any, column: str, dtype: Any) -> tuple[Any, Any]:
    """Get the smallest and the largest finite value of a column; None for none."""
    if not dtype.is_numeric():
        msg = f"The column {column!r} of {dtype} can't be a range of numbers"
        raise TypeError(msg)
    cell = nw.col(column)
    finite = cell.filter(cell.is_finite()) if dtype.is_float() else cell
    low, high = _collected(values.select(low=finite.min(), high=finite.max())).row(0)
    return _python_value(low), _python_value(high)


def _round_step(span: float) -> decimal.Decimal:
    """Get a step of 1, 2 or 5 times a power of 10, near a hundredth of `span`."""
    if span <= 0:
        return decimal.Decimal(1)
    rough = span / _RANGE_STEPS
    power = decimal.Decimal(10) ** math.floor(math.log10(rough))
    for factor in (1, 2, 5):
        if power * factor >= decimal.Decimal(repr(rough)):
            return power * factor
    return power * 10


def _fill_range(
    view: Union[RangeSliderMixin, FloatRangeSliderMixin], values: Any, column: str, dtype: Any
) -> None:
    is_whole = isinstance(view, RangeSliderMixin)
    if is_whole and not dtype.is_integer():
        msg = f"The column {column!r} of {dtype} needs a FloatRangeSliderView"
        raise TypeError(msg)
    low, high = _number_limits(values, column, dtype)
    if low is None:
        low, high = 0, 0
    step = _round_step(float(high) - float(low))
    if is_whole:
        step = max(decimal.Decimal(1), step.to_integral_value(decimal.ROUND_CEILING))
    # on a whole step, so that the ends show as few decimals as the step
    minimum = (_exact(low) / step).to_integral_value(decimal.ROUND_FLOOR) * step
    maximum = (_exact(high) / step).to_integral_value(decimal.ROUND_CEILING) * step
    number: Callable[[decimal.Decimal], Any] = int if is_whole else float
    _set_range(view, number(minimum), number(maximum), number(step))


def _exact(number: Union[float, decimal.Decimal]) -> decimal.Decimal:
    """Get a number as the decimal that it shows: 0.1 as 0.1, not as its binary value."""
    return number if isinstance(number, decimal.Decimal) else decimal.Decimal(repr(number))


def _set_range(
    # either slider: one of whole numbers gets whole numbers
    view: Any,
    minimum: float,
    maximum: float,
    step: float,
) -> None:
    """Set a slider's range, keeping its ends: one at a limit moves to the new limit."""
    rules = view.step_rules
    old_low, old_high = view.value
    at_minimum = old_low <= view.minimum
    at_maximum = old_high >= rules.value_at(
        rules.last_position(view.minimum, view.maximum, view.step), view.minimum, view.step
    )
    # a step over both ranges first: each limit set on its own then takes one step at most,
    # far below the slider's limit of steps
    hull = max(view.maximum, maximum) - min(view.minimum, minimum)
    view.step = max(view.step, step, hull)
    view.minimum, view.maximum = minimum, maximum
    view.step = step
    low = minimum if at_minimum else min(max(old_low, minimum), maximum)
    high = maximum if at_maximum else min(max(old_high, low), maximum)
    view.value = (low, high)


def _fill_dates(view: DateRangeInputMixin, values: Any, column: str, dtype: Any) -> None:
    if dtype not in (nw.Date, nw.Datetime):
        msg = f"The column {column!r} of {dtype} can't be a range of dates"
        raise TypeError(msg)
    low, high = (
        None if end is None else _as_date(end)
        for end in (
            _python_value(end)
            for end in _collected(
                values.select(low=nw.col(column).min(), high=nw.col(column).max())
            ).row(0)
        )
    )
    view.minimum, view.maximum = low, high
    start, end = view.value
    # an end out of the column's days is no limit any more
    view.value = (
        None if start is None or low is None or start < low else start,
        None if end is None or high is None or end > high else end,
    )


def _as_date(value: Union[datetime.date, datetime.datetime]) -> datetime.date:
    return value.date() if isinstance(value, datetime.datetime) else value


def _conditions(view: _Filter, column: str, dtype: Any) -> list[nw.Expr]:
    """Get what a filter asks of its column's cells: nothing while it keeps every row."""
    cell = nw.col(column)
    if isinstance(view, MultiValuesMixin):
        if view.selected == list(view.values.values()):
            return []
        if not view.selected:
            # false on every row: not `is_in([])`, which PyArrow can't type, nor a bare
            # `lit(False)`, which Narwhals takes for an aggregate
            return [cell.is_null() & ~cell.is_null()]
        read = cast("Callable[[str], Any]", _choice_texts(dtype))
        return [cell.is_in([read(text) for text in view.selected])]
    if isinstance(view, (RangeSliderMixin, FloatRangeSliderMixin)):
        rules = view.step_rules
        last = rules.value_at(
            rules.last_position(view.minimum, view.maximum, view.step), view.minimum, view.step
        )
        low, high = view.value
        conditions = []
        if low > view.minimum:
            conditions.append(cell >= low)
        if high < last:
            conditions.append(cell <= high)
        if conditions and dtype.is_float():
            # Polars sorts NaN above every number
            conditions.append(~cell.is_nan())
        return conditions
    return _date_conditions(view.value, cell, dtype)


def _date_conditions(
    days: tuple[Optional[datetime.date], Optional[datetime.date]], cell: nw.Expr, dtype: Any
) -> list[nw.Expr]:
    start, end = days
    if dtype == nw.Date:
        return [
            *([] if start is None else [cell >= start]),
            *([] if end is None else [cell <= end]),
        ]
    # a time of the end day is in the range: up to the next day's midnight
    time_zone = getattr(dtype, "time_zone", None)
    conditions = []
    if start is not None:
        compared, value = _on_one_clock(
            cell, datetime.datetime.combine(start, datetime.time()), time_zone
        )
        conditions.append(compared >= value)
    if end is not None:
        next_day = datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time())
        compared, value = _on_one_clock(cell, next_day, time_zone)
        conditions.append(compared < value)
    return conditions


def counts_of(frame: IntoFrame, column: str, categories: Iterable[Any]) -> list[int]:
    """Count the rows of `frame` with each of `categories` in `column`, 0 for those of none.

    E.g. the bars of a chart by hour: ``counts_of(rows, "Hour", range(24))``. The counts keep
    the order of `categories`, so that the bars stay in place while the rows change.
    """
    counted = _collected(nw.from_native(frame).group_by(column, drop_null_keys=True).agg(nw.len()))
    counts = {_python_value(value): count for value, count in counted.iter_rows()}
    return [int(counts.get(category, 0)) for category in categories]


def show_frame(table: SourceTableView, frame: IntoFrame, *, filterable: bool = True) -> None:
    """Show the rows of `frame` in `table`, its filter bar offering every column if `filterable`.

    A lazy frame needs a `DataFrameSource` with its `id_column`: set the table's source
    yourself, or collect the frame first.

    Without `filterable`, the table keeps its own `filterable_columns`. The table keeps its
    sort and its filters on the columns that the new frame still has.
    """
    columns = nw.from_native(frame).collect_schema().names()
    table.source = DataFrameSource(frame)
    with untracked():  # the table's field is this function's output, not its input
        filterable_columns = table.filterable_columns
    if filterable and filterable_columns != columns:
        table.filterable_columns = columns


def read_frame(
    path: Path, *, backend: IntoBackend[EagerAllowed], max_columns: int = MAX_COLUMNS
) -> nw.DataFrame[Any]:
    """Read a CSV or Parquet file that a user gave, such as an `UploadedFile`'s `path`.

    `backend` is the library that reads it, such as ``"polars"`` or ``"pandas"``. A file
    ending in ``.parquet`` reads as Parquet, any other as CSV. A CSV file's separator is
    the most frequent of ``,``, ``;``, a tab and ``|`` on its first line. Refuses with a
    `ValueError` a compressed CSV file, which could unpack to more than the server's memory,
    a CSV file of more than `max_columns` columns, or whose first line is longer than 64 KiB,
    and a Parquet file whose description of its columns is damaged or larger than
    `MAX_PARQUET_METADATA_SIZE`. A Parquet file's columns are compressed: it can still take
    much more memory than its size.
    """
    if path.suffix.lower() == ".parquet":
        _check_parquet(path)
        return nw.read_parquet(str(path), backend=backend)
    _check_not_compressed(path)
    separator = _csv_separator(path, max_columns)
    return nw.read_csv(str(path), backend=backend, separator=separator)


def _csv_separator(path: Path, max_columns: int) -> str:
    """Find the separator of a CSV file: the most frequent on its first line, outside quotes.

    Refuse a file of more than `max_columns` columns, or a first line too long to count them.
    """
    with path.open(encoding="utf-8", errors="replace", newline="") as file:
        header = file.readline(_MAX_HEADER_LENGTH)
    if len(header) == _MAX_HEADER_LENGTH and not header.endswith(("\n", "\r")):
        msg = f"the first line is longer than {_MAX_HEADER_LENGTH // 1024} KiB"
        raise ValueError(msg)
    counts = dict.fromkeys(_SEPARATORS, 0)
    is_quoted = False
    for character in header:
        if character == '"':
            is_quoted = not is_quoted
        elif character in counts and not is_quoted:
            counts[character] += 1
    separator = max(_SEPARATORS, key=lambda separator: counts[separator])
    if counts[separator] + 1 > max_columns:
        msg = f"a file of more than {max_columns} columns isn't accepted"
        raise ValueError(msg)
    return separator


def _check_not_compressed(path: Path) -> None:
    with path.open("rb") as file:
        start = file.read(_COMPRESSED_START_LENGTH)
    if start.startswith(_COMPRESSED_STARTS):
        msg = "a compressed file isn't accepted"
        raise ValueError(msg)


def _check_parquet(path: Path) -> None:
    """Refuse a file that isn't Parquet, or whose description is too large to read."""
    size = path.stat().st_size
    with path.open("rb") as file:
        start = file.read(len(_PARQUET_MARK))
        file.seek(max(0, size - _PARQUET_FOOTER))
        footer = file.read(_PARQUET_FOOTER)
    if (
        size < len(_PARQUET_MARK) + _PARQUET_FOOTER
        or start != _PARQUET_MARK
        or footer[4:] != _PARQUET_MARK
    ):
        msg = "not a Parquet file"
        raise ValueError(msg)
    length = int.from_bytes(footer[:4], "little")
    if length > size - len(_PARQUET_MARK) - _PARQUET_FOOTER:
        msg = "a damaged Parquet file"
        raise ValueError(msg)
    if length > MAX_PARQUET_METADATA_SIZE:
        msg = f"a Parquet file describes its columns in more than {MAX_PARQUET_METADATA_SIZE} bytes"
        raise ValueError(msg)


def frame_content(frame: IntoFrame, *, is_parquet: bool = False) -> StreamContent:
    """Get the rows of `frame` as a file that a `DownloadView` gives: CSV, else Parquet.

    E.g. ``self.download.content = lambda: frame_content(rows)``. The frame's library writes
    the file as the user receives it, a lazy frame collected then.
    """
    native = nw.from_native(frame)

    def write(sink: BinaryIO) -> None:
        rows = _collected(native)
        if is_parquet:
            rows.write_parquet(cast("Any", sink))
        else:
            rows.write_csv(cast("Any", sink))

    return StreamContent(write)
