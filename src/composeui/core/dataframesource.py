"""A dataframe's rows in a large table, a chart or a map: pandas, Polars, PyArrow, lazy...

`narwhals` reads each library's frame through one API, so the library sorts and filters the
rows with its own expressions, never row by row in Python.
"""

from __future__ import annotations

import datetime
import decimal
from typing import TYPE_CHECKING, Any, Optional, Union

import narwhals.stable.v2 as nw

from composeui.core.signal import SignalNoArgs
from composeui.core.view import (
    MAP_LATITUDE_LIMIT,
    ColumnKind,
    FilterOperator,
    MapPoint,
    Series,
    SourceColumn,
    column_kind,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Hashable, Iterator, Mapping, Sequence

    from narwhals.stable.v2.typing import IntoFrame

    from composeui.core.sqlitemodel import CSVSqliteTable
    from composeui.core.view import Filter, Sort

__all__ = ["DataFrameSource", "fill_from_frame", "points_of", "series_of"]

#: the column of the rows' ids added to a frame without an `id_column`
ROW_ID = "__composeui_id"
_EMPTY_KEY = "__composeui_empty"
_SORT_KEY = "__composeui_key"
#: the rows' ids in `cells`, apart from the id column that a column may show too
_CELL_ID_KEY = "__composeui_cell_id"
#: a frame's row positions, which break a sort's ties when the ids aren't them
_POSITION_KEY = "__composeui_position"

_PYTHON_TYPES = (
    (nw.Boolean, bool),
    (nw.Datetime, datetime.datetime),
    (nw.Date, datetime.date),
    (nw.Duration, datetime.timedelta),
)
_TEXT_OPERATORS = (
    FilterOperator.CONTAINS,
    FilterOperator.NOT_CONTAINS,
    FilterOperator.TEXT_EQUAL,
    FilterOperator.TEXT_NOT_EQUAL,
    FilterOperator.STARTS_WITH,
    FilterOperator.ENDS_WITH,
)


def _python_type(dtype: Any) -> Any:
    """Get the Python type of a column's values, which sets how it sorts and filters."""
    if dtype.is_integer():
        return int
    if dtype.is_numeric():  # a float or a decimal
        return float
    for frame_type, python_type in _PYTHON_TYPES:
        if dtype == frame_type:
            return python_type
    return str  # a text, a category, or a type shown as its text


class DataFrameSource:
    """A `TableSource` of a dataframe's rows, which a large table reads a window at a time.

    Build it with any frame `narwhals` reads (pandas, Polars, PyArrow, a Polars
    ``LazyFrame``...) and the headers by column: ``DataFrameSource(frame, {"lat":
    T("Latitude")})``, every column under its name without them. A row's id is its
    position in the frame, or its `id_column` when it has one: a lazy frame needs one, its
    rows having no position of their own. Assign a new `frame` to change the rows, which
    emits `changed`: it must hold the same columns, whose types may differ. New rows without
    an `id_column` clear a table's selection, as a position doesn't say which row it was.

    The frame's library sorts and filters. A text compares in lower case, which isn't
    Python's ``casefold`` ("ß" doesn't find "SS"), and a ``/regex/`` is in the library's
    syntax (Rust's ``regex`` for Polars, ``re`` for pandas, RE2 for PyArrow). Equal cells, and
    the rows unsorted, keep the frame's order; a lazy frame's equal cells are in the order of
    their ids.
    """

    def __init__(
        self,
        frame: IntoFrame,
        headers: Optional[Mapping[str, str]] = None,
        *,
        id_column: Optional[str] = None,
    ) -> None:
        self._id_column = id_column
        self._changed = SignalNoArgs()
        self._native = frame
        self._frame = self._wrapped(frame)
        self.row_ids_scope = self._new_row_ids_scope()
        names = self._frame.collect_schema() if headers is None else headers
        self._columns = self._read_columns(
            self._frame, {name: name if headers is None else headers[name] for name in names}
        )

    def _read_columns(
        self, frame: Union[nw.DataFrame[Any], nw.LazyFrame[Any]], headers: Mapping[str, str]
    ) -> dict[str, SourceColumn]:
        """Get the columns of `headers` with their types in `frame`, which must hold them."""
        schema = frame.collect_schema()
        id_columns = [] if self._id_column is None else [self._id_column]
        for name in [*headers, *id_columns]:
            if name not in schema:
                msg = f"Cannot build a DataFrameSource: the frame has no column {name!r}."
                raise ValueError(msg)
        return {
            name: SourceColumn(name, header, self._type_of(frame, name, schema[name]))
            for name, header in headers.items()
            if name != ROW_ID
        }

    @property
    def columns(self) -> Sequence[SourceColumn]:
        return tuple(self._columns.values())

    @property
    def changed(self) -> SignalNoArgs:
        return self._changed

    @property
    def frame(self) -> IntoFrame:
        """Get the frame given, in its own library."""
        return self._native

    @frame.setter
    def frame(self, frame: IntoFrame) -> None:
        wrapped = self._wrapped(frame)
        # the same columns, for the headers that a table shows; their types can differ
        columns = self._read_columns(
            wrapped, {column.name: column.header for column in self._columns.values()}
        )
        self._native, self._frame, self._columns = frame, wrapped, columns
        self.row_ids_scope = self._new_row_ids_scope()
        self._changed.emit()

    @property
    def _id(self) -> str:
        return ROW_ID if self._id_column is None else self._id_column

    @staticmethod
    def _type_of(frame: Union[nw.DataFrame[Any], nw.LazyFrame[Any]], name: str, dtype: Any) -> Any:
        """Get a column's Python type: pandas holds decimals as objects, so read the values."""
        if dtype == nw.Object and isinstance(frame, nw.DataFrame):
            values = frame.get_column(name).drop_nulls().to_list()
            if all(isinstance(value, decimal.Decimal) for value in values):
                return decimal.Decimal
        return _python_type(dtype)

    def _new_row_ids_scope(self) -> Optional[object]:
        """Get what a table compares to tell that the ids now name other rows, if they can."""
        return None if self._id_column is not None else object()

    def _wrapped(self, frame: IntoFrame) -> Union[nw.DataFrame[Any], nw.LazyFrame[Any]]:
        wrapped = nw.from_native(frame)
        if self._id_column is not None:
            return wrapped
        if isinstance(wrapped, nw.LazyFrame):
            msg = "Cannot build a DataFrameSource of a lazy frame without an id_column."
            raise TypeError(msg)
        return wrapped.with_row_index(ROW_ID)

    def count(self) -> int:
        return int(_collected(self._frame.select(nw.len())).item())

    def ordered_ids(
        self, sort: Optional[Sort], search: str, filters: Mapping[str, Filter]
    ) -> list[Hashable]:
        for name in [*filters, *([] if sort is None else [sort.column])]:
            self._column(name)
        # the frame once: in a job, the main thread may assign a new one meanwhile
        frame = self._frame
        schema = frame.collect_schema()
        without_text = {name for name, dtype in schema.items() if dtype in (nw.List, nw.Array)}
        if sort is not None and sort.column in without_text:
            sort = None
        filters = {name: value for name, value in filters.items() if name not in without_text}
        conditions = [
            self._condition(
                self._column(name), row_filter, getattr(schema[name], "time_zone", None)
            )
            for name, row_filter in filters.items()
        ]
        needle = search.strip().casefold()
        if needle != "":
            texts = [
                _text(name)
                for name, column in self._columns.items()
                if column_kind(column.type) is ColumnKind.TEXT and name not in without_text
            ]
            if len(texts) == 0:
                return []  # no text column holds it, as a `ListSource` finds
            conditions.append(
                nw.any_horizontal(
                    *(text.str.contains(needle, literal=True) for text in texts),
                    ignore_nulls=True,
                )
            )
        if len(conditions) > 0:
            frame = frame.filter(*conditions)
        if sort is None:
            ordered = frame.select(self._id)
        else:
            column = self._column(sort.column)
            is_text = column_kind(column.type) is ColumnKind.TEXT
            cell = nw.col(column.name)
            text = _as_text(cell)
            empty = cell.is_null() | (text == "") if is_text else cell.is_null()
            # an empty text's key is null, as a missing one's: the empty cells in the
            # frame's order, "" sorting before null otherwise
            key = nw.when(text != "").then(text.str.to_lowercase()) if is_text else cell
            tie = self._id
            if self._id_column is not None and isinstance(frame, nw.DataFrame):
                frame, tie = frame.with_row_index(_POSITION_KEY), _POSITION_KEY
            ordered = (
                frame.select(
                    *dict.fromkeys((self._id, tie)),
                    empty.alias(_EMPTY_KEY),
                    key.alias(_SORT_KEY),
                )
                # the empty cells last in both orders, equal cells in the frame's order
                .sort(
                    _EMPTY_KEY,
                    _SORT_KEY,
                    tie,
                    descending=[False, sort.descending, False],
                    nulls_last=True,
                )
                .select(self._id)
            )
        return list(_collected(ordered).get_column(self._id).to_list())

    def cells(self, ids: Sequence[Hashable], columns: Sequence[str]) -> dict[Hashable, list[Any]]:
        names = [self._column(name).name for name in columns]
        rows = _collected(
            self._frame.filter(nw.col(self._id).is_in(list(ids))).select(
                nw.col(self._id).alias(_CELL_ID_KEY), *names
            )
        )
        return {
            _python_value(row[0]): [_python_value(value) for value in row[1:]]
            for row in rows.iter_rows()
        }

    def _column(self, name: str) -> SourceColumn:
        column = self._columns.get(name)
        if column is None:
            msg = f"Cannot read the column {name!r} of a DataFrameSource: it has none so."
            raise ValueError(msg)
        return column

    @staticmethod
    def _condition(column: SourceColumn, row_filter: Filter, time_zone: Optional[str]) -> nw.Expr:
        """Get the expression of `row_filter` on `column`, as `Filter.matches` reads a cell.

        An empty cell's text is "", and it fails a comparison. `time_zone` is the column's.
        """
        cell = nw.col(column.name)
        operator, value = row_filter.operator, row_filter.value
        if operator is FilterOperator.EMPTY:
            if column_kind(column.type) is ColumnKind.TEXT:
                return cell.is_null() | (cell.cast(nw.String) == "")
            return cell.is_null()
        if operator in _TEXT_OPERATORS:
            return _text_condition(_text(column.name), operator, value)
        if operator is FilterOperator.MATCHES:
            text = _as_text(cell)
            return text.str.contains(f"(?i){value.pattern}")
        if operator is FilterOperator.RANGE:
            on_one_clock, lower = _on_one_clock(cell, value, time_zone)
            _, upper = _on_one_clock(cell, row_filter.upper, time_zone)
            compared = on_one_clock.is_between(lower, upper)
        else:
            on_one_clock, compared_value = _on_one_clock(cell, value, time_zone)
            compared = _comparison(on_one_clock, operator, compared_value)
        # an empty cell fails, though pandas' NaN differs from any value
        return ~cell.is_null() & compared


def series_of(frame: IntoFrame, x: str, y: str, *, name: Optional[str] = None) -> Series:
    """Make a chart's series of a frame's columns `x` and `y`, under `name`, else `y`.

    The rows missing either value are left out, in the frame's order otherwise.
    """
    rows = _collected(nw.from_native(frame).select(x, y).drop_nulls())
    return Series(
        y if name is None else name, rows.get_column(x).to_list(), rows.get_column(y).to_list()
    )


def points_of(frame: IntoFrame, latitude: str, longitude: str) -> list[MapPoint]:
    """Get a map's points of a frame's columns `latitude` and `longitude`, in degrees.

    The rows missing either value, or out of a Web Mercator map (see `MapPoint`), are left out.
    """
    rows = _collected(
        nw.from_native(frame)
        .select(latitude, longitude)
        .drop_nulls()
        .filter(
            nw.col(latitude).is_between(-MAP_LATITUDE_LIMIT, MAP_LATITUDE_LIMIT),
            nw.col(longitude).is_between(-180, 180),
        )
    )
    return [MapPoint(latitude=lat, longitude=lon) for lat, lon in rows.iter_rows()]


def _text(name: str) -> nw.Expr:
    """Get a cell's text in lower case, an empty cell's being ""."""
    return _as_text(nw.col(name)).str.to_lowercase()


def _as_text(cell: nw.Expr) -> nw.Expr:
    """Get a cell's text, an empty cell's being "": pandas casts it to "None" or "nan"."""
    # not `otherwise`: in `narwhals.stable.v2` it returns an `Expr` of the unstable API
    return nw.when(~cell.is_null()).then(cell.cast(nw.String)).fill_null("")


def _text_condition(text: nw.Expr, operator: FilterOperator, value: str) -> nw.Expr:
    if operator is FilterOperator.CONTAINS:
        return text.str.contains(value, literal=True)
    if operator is FilterOperator.NOT_CONTAINS:
        return ~text.str.contains(value, literal=True)
    if operator is FilterOperator.TEXT_EQUAL:
        return text == value
    if operator is FilterOperator.TEXT_NOT_EQUAL:
        return text != value
    if operator is FilterOperator.STARTS_WITH:
        return text.str.starts_with(value)
    return text.str.ends_with(value)


def _on_one_clock(cell: nw.Expr, value: Any, time_zone: Optional[str]) -> tuple[nw.Expr, Any]:
    """Get a cell and a filter's value that the frame's library can compare.

    A library refuses to compare a time with a zone and one without. A time typed without a zone is
    the clock's in the column's zone, as the cell shows it. One typed with a zone is an instant.
    A column without a zone has no instant to compare with: its clock is read instead.
    """
    if not isinstance(value, datetime.datetime):
        return cell, value
    if value.tzinfo is None:
        return (cell if time_zone is None else cell.dt.replace_time_zone(None)), value
    if time_zone is None:
        return cell, value.replace(tzinfo=None)
    utc = cell.dt.convert_time_zone("UTC").dt.replace_time_zone(None)
    return utc, value.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _comparison(cell: nw.Expr, operator: FilterOperator, value: Any) -> nw.Expr:
    if operator is FilterOperator.EQUAL:
        return cell == value
    if operator is FilterOperator.NOT_EQUAL:
        return cell != value
    if operator is FilterOperator.LESS:
        return cell < value
    if operator is FilterOperator.LESS_OR_EQUAL:
        return cell <= value
    if operator is FilterOperator.GREATER:
        return cell > value
    return cell >= value


def _python_value(value: Any) -> Any:
    """Get a cell as Python's value: pandas gives numpy's scalars, and NaN or NaT for none."""
    try:
        if value is None or bool(value != value):  # noqa: PLR0124 (NaN and NaT differ from themselves)
            return None
    except TypeError:  # pandas' NA, which is neither true nor false
        return None
    if hasattr(value, "to_pydatetime"):  # a pandas Timestamp
        return value.to_pydatetime()
    if hasattr(value, "to_pytimedelta"):  # a pandas Timedelta
        return value.to_pytimedelta()
    if hasattr(value, "item"):  # a numpy scalar
        return value.item()
    return value


def _collected(frame: Union[nw.DataFrame[Any], nw.LazyFrame[Any]]) -> nw.DataFrame[Any]:
    return frame.collect() if isinstance(frame, nw.LazyFrame) else frame


def _frame_rows(frame: nw.DataFrame[Any], window: int) -> Iterator[dict[str, Any]]:
    """Get the rows of `frame` as dictionaries, a window of them in Python at a time."""
    for start in range(0, len(frame), window):
        part = frame[start : start + window]
        # a library's own mark for a missing value, such as pandas' NaN or NaT, becomes None
        columns = [
            [
                None if is_null else value
                for value, is_null in zip(part[name].to_list(), part[name].is_null().to_list())
            ]
            for name in part.columns
        ]
        for values in zip(*columns):
            yield dict(zip(part.columns, values))


def fill_from_frame(
    table: CSVSqliteTable,
    frame: IntoFrame,
    *,
    batch_size: int = 100_000,
    limit: Optional[int] = None,
) -> Generator[int]:
    """Import the rows of a frame into `table`, and yield cumulative row counts.

    Build the frame with any library that `narwhals` reads, such as a Parquet file read with
    ``polars.read_parquet``. A column gives the field of its name, and its null values give
    None. A lazy frame is collected first: the data stays in memory during the import.

    Exhaust the generator to commit, or use ``contextlib.closing`` to roll back when
    stopping early, as with `CSVSqliteTable.fill`. A row that its row class refuses raises
    `RefusedError`.
    """
    collected = _collected(nw.from_native(frame))
    yield from table.fill_rows(
        _frame_rows(collected, batch_size), batch_size=batch_size, limit=limit
    )
