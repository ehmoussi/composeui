"""A dataframe's rows in a large table, a chart or a map: pandas, Polars, PyArrow, lazy...

`narwhals` reads each library's frame through one API, so the library sorts and filters the
rows with its own expressions, never row by row in Python.
"""

from __future__ import annotations

import datetime
import decimal
import operator
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NamedTuple, Optional, Union

import attrs
import narwhals.stable.v2 as nw

from composeui.core._views.graphics import MAP_LATITUDE_LIMIT
from composeui.core._views.tables import ColumnKind, column_kind
from composeui.core.model import RefusedError
from composeui.core.signal import SignalNoArgs
from composeui.core.view import FilterOperator, MapPoint, Series, SourceColumn

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Hashable, Iterator, Mapping, Sequence

    from narwhals.stable.v2.typing import IntoFrame

    from composeui.core.sqlitemodel import CSVSqliteTable, Parameters, _CSVField
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
    """Make a chart's line of a frame's columns `x` and `y`, under `name`, else `y`.

    The rows missing either value are left out, in the frame's order otherwise.
    """
    rows = _collected(nw.from_native(frame).select(x, y).drop_nulls())
    return Series.line(
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

    The frame's library checks the columns. Python checks each row when the row class runs
    its own code, such as a converter, or when a column needs a conversion, such as text for a
    number. The rows refused, and the messages, are the same.

    Exhaust the generator to commit, or use ``contextlib.closing`` to roll back when
    stopping early, as with `CSVSqliteTable.fill`. A row that its row class refuses raises
    `RefusedError`.
    """
    collected = _collected(nw.from_native(frame))
    yield from table._insert_rows(  # noqa: SLF001 (the table's import, from a frame's columns)
        _frame_parameters(table, collected, batch_size=batch_size, limit=limit),
        batch_size=batch_size,
        limit=limit,
    )


def _frame_parameters(
    table: CSVSqliteTable, frame: nw.DataFrame[Any], *, batch_size: int, limit: Optional[int]
) -> Iterator[Parameters]:
    """Get the SQL parameters of `frame`'s rows, checked in the frame's library if it can.

    A generator: the import checks its own arguments before any row is read.
    """
    if limit is not None:
        frame = frame.head(limit)  # as the rows' import, refuse no row after the limit
    columns = _stored_columns(table, frame)
    if columns is None:
        yield from (
            table.row_parameters(table._typed_row(row))  # noqa: SLF001 (as `fill_rows`)
            for row in _frame_rows(frame, batch_size)
        )
        return
    # in Python a batch at a time, as `_frame_rows`: the frame's values take less memory
    for start in range(0, len(frame), batch_size):
        stop = min(start + batch_size, len(frame))
        yield from zip(*(column.cells(start, stop) for column in columns))


#: the comparisons of attrs' number validators (`attrs.validators.ge`...), in the frame
_BOUNDS: Mapping[str, Callable[[Any, Any], Any]] = MappingProxyType(
    {"<": operator.lt, "<=": operator.le, ">=": operator.ge, ">": operator.gt}
)
_NUMBER_VALIDATOR: type[Any] = type(attrs.validators.ge(0))
_AND_VALIDATOR: type[Any] = type(attrs.validators.and_())
_OPTIONAL_VALIDATOR: type[Any] = type(attrs.validators.optional(attrs.validators.ge(0)))
#: a date's text in SQLite: its own method, as pandas' adds the nanoseconds to Python's
_ISO_TEXT = operator.methodcaller("isoformat")
#: the integers that SQLite stores, in absolute value, at most
_INTEGER_BOUND = float(2**63)  # a float: PyArrow compares a column to a C long
#: the integer types that `_INTEGER_BOUND` holds
_INTEGERS = (nw.Int8, nw.Int16, nw.Int32, nw.Int64, nw.UInt8, nw.UInt16, nw.UInt32)


class _Column(NamedTuple):
    values: nw.Series[Any]
    #: where the row has no value: a null, or NaN
    missing: nw.Series[Any]
    #: the value that SQLite stores for each cell, if not the cell itself
    stored: Optional[Callable[[Any], Any]] = None

    def cells(self, start: int, stop: int) -> list[Any]:
        """Get the values that SQLite stores for the rows from `start` to `stop`."""
        cells = self.values[start:stop].to_list()
        stored = self.stored
        missing = self.missing[start:stop]
        if missing.any():
            nones = missing.to_list()
            if stored is None:
                return [None if is_missing else cell for cell, is_missing in zip(cells, nones)]
            return [None if is_missing else stored(cell) for cell, is_missing in zip(cells, nones)]
        return cells if stored is None else [stored(cell) for cell in cells]


class _Default(NamedTuple):
    """The cells of a field that the frame doesn't give: its default."""

    value: Any

    def cells(self, start: int, stop: int) -> list[Any]:
        return [self.value] * (stop - start)


class _Refusal(NamedTuple):
    """The first row that a check refuses, which the import refuses if no check is earlier."""

    row: int
    #: the checks of a row, in the order of `CSVSqliteTable.fill_rows`: the types of its
    #: values, then each field's missing value, then the row class's validators
    step: int
    position: int
    refuse: Callable[[int], None]


def _stored_columns(
    table: CSVSqliteTable, frame: nw.DataFrame[Any]
) -> Optional[list[Union[_Column, _Default]]]:
    """Get the columns whose values `fill_rows` would store, one per column of the table.

    Check the columns in the frame's library, and refuse the first row that `fill_rows`
    refuses, with its message. None when the rows need Python: a field with a converter or
    another validator than a number's, a column of text for a number...
    """
    if _runs_own_code(table):
        return None
    csv_fields = iter(table._csv_fields)  # noqa: SLF001 (the table's import)
    columns: list[Union[_Column, _Default]] = []
    refusals: list[_Refusal] = []
    for position, field in enumerate(attrs.fields(table.row_type)):
        csv_field_ = next(csv_fields) if field.init else None
        if csv_field_ is None or csv_field_.header not in frame.columns:
            cells: Optional[Union[_Column, _Default]] = _default_cells(field)
        else:
            cells = _field_cells(frame[csv_field_.header], field, csv_field_, position, refusals)
        if cells is None:
            return None
        columns.append(cells)
    if refusals:
        first = min(refusals)
        first.refuse(first.row)
        # the frame's library and Python differ on its value, such as a nanosecond that
        # Python's date doesn't hold: Python checks every row
        return None
    return columns


def _runs_own_code(table: CSVSqliteTable) -> bool:
    """Tell whether the table's row class or its import runs code of the app on each row."""
    from composeui.core.sqlitemodel import CSVSqliteTable  # noqa: PLC0415 (loaded: `table` is one)

    return (
        hasattr(table.row_type, "__attrs_post_init__")
        or hasattr(table.row_type, "__attrs_init__")  # the class's own `__init__` calls it
        or type(table).row_parameters is not CSVSqliteTable.row_parameters
        or any(field.converter is not None for field in attrs.fields(table.row_type))
    )


def _default_cells(field: attrs.Attribute[Any]) -> Optional[_Default]:
    """Get the cells of a field that the frame doesn't give: its default, if a plain value."""
    default = field.default
    if (
        field.validator is not None
        or default is attrs.NOTHING  # the row class refuses the row, with its message
        or isinstance(default, attrs.Factory)  # type: ignore[arg-type]
    ):
        return None
    from composeui.core.sqlitemodel import _STORED_AS_IS, _csv_cell  # noqa: PLC0415 (loaded)

    return _Default(default if type(default) in _STORED_AS_IS else _csv_cell(default))


def _field_cells(
    series: nw.Series[Any],
    field: attrs.Attribute[Any],
    csv_field_: _CSVField,
    position: int,
    refusals: list[_Refusal],
) -> Optional[_Column]:
    """Get the column of a field, and add its refusals."""
    column = _typed_column(series, csv_field_, position, refusals)
    if column is None:
        return None
    if csv_field_.is_required:
        refusals.extend(_first_refusal(column.missing, 1, position, _no_value(csv_field_.header)))
    if field.validator is not None and not attrs.validators.get_disabled():
        fails = _validator_fails(field.validator, column)
        if fails is None:
            return None
        refusals.extend(_first_refusal(fails, 2, position, _validator_refusal(field, column)))
    return column


def _typed_column(
    series: nw.Series[Any], field: _CSVField, position: int, refusals: list[_Refusal]
) -> Optional[_Column]:
    """Get a column of the frame as `_typed_value` gets its values, or None if it can't."""
    from composeui.core.sqlitemodel import _typed_value  # noqa: PLC0415 (loaded with the table)

    def refuse(row: int) -> None:
        _typed_value(_cell(series, row), field.value_type, field.header)

    missing = series.is_null()
    if series.dtype.is_float():
        missing = (missing | series.is_nan()).fill_null(value=True)
    if isinstance(series.dtype, (nw.Date, nw.Datetime)):
        return _date_column(series, missing, field.value_type, _Refuse(refusals, position, refuse))
    return _plain_column(series, missing, field.value_type, _Refuse(refusals, position, refuse))


class _Refuse(NamedTuple):
    """Where a column's type refuses its first row: in `refusals`."""

    refusals: list[_Refusal]
    position: int
    refuse: Callable[[int], None]

    def first(self, refused: nw.Series[Any]) -> None:
        self.refusals.extend(_first_refusal(refused, 0, self.position, self.refuse))


def _plain_column(
    series: nw.Series[Any], missing: nw.Series[Any], value_type: Any, refuse: _Refuse
) -> Optional[_Column]:
    dtype = series.dtype
    if (value_type is str and dtype == nw.String) or (value_type is bool and dtype == nw.Boolean):
        return _Column(series, missing)
    if value_type is float and (dtype.is_float() or isinstance(dtype, _INTEGERS)):
        return _Column(series.cast(nw.Float64), missing)
    if value_type is int and isinstance(dtype, _INTEGERS):
        return _Column(series, missing)
    if value_type is int and dtype.is_float():
        kept = ~missing
        if (kept & (series.abs() >= _INTEGER_BOUND)).any():
            return None  # SQLite doesn't store it: as a row's error
        fraction = kept & (series % 1 != 0)
        refuse.first(fraction)
        zeros = missing.cast(nw.Float64) * 0
        return _Column(series.zip_with(kept & ~fraction, zeros).cast(nw.Int64), missing)
    return None


def _date_column(
    series: nw.Series[Any], missing: nw.Series[Any], value_type: Any, refuse: _Refuse
) -> Optional[_Column]:
    dtype = series.dtype
    if isinstance(dtype, nw.Datetime) and dtype.time_zone is not None:
        return None
    if value_type is datetime.date and dtype == nw.Date:
        return _Column(series, missing, _ISO_TEXT)
    if value_type is datetime.date:
        times = series.dt.hour() + series.dt.minute() + series.dt.second() + series.dt.nanosecond()
        refuse.first(~missing & (times != 0))
        return _Column(series, missing, _date_text)
    if value_type is datetime.datetime and dtype == nw.Date:
        return _Column(series, missing, _midnight_text)
    if value_type is datetime.datetime:
        return _Column(series, missing, _ISO_TEXT)
    return None


def _date_text(value: datetime.datetime) -> str:
    return value.date().isoformat()


def _midnight_text(value: datetime.date) -> str:
    return datetime.datetime.combine(value, datetime.time()).isoformat()


def _cell(series: nw.Series[Any], row: int) -> Any:
    """Get a cell as `_frame_rows` does: a missing value as None."""
    return None if series.is_null()[row] else series[row : row + 1].to_list()[0]


def _first_refusal(
    refused: nw.Series[Any], step: int, position: int, refuse: Callable[[int], None]
) -> list[_Refusal]:
    rows = refused.fill_null(value=False).arg_true().head(1).to_list()
    return [_Refusal(rows[0], step, position, refuse)] if rows else []


def _no_value(header: str) -> Callable[[int], None]:
    def refuse(_row: int) -> None:
        msg = f"The row has no value for {header}"
        raise RefusedError(msg)

    return refuse


def _validator_fails(validator: Any, column: _Column) -> Optional[nw.Series[Any]]:
    """Get where `validator` refuses a number of `column`; None for another validator."""
    if type(validator) is _AND_VALIDATOR:
        fails = column.missing & ~column.missing
        for each in validator._validators:  # noqa: SLF001 (attrs' `and_`, read alone)
            each_fails = _validator_fails(each, column)
            if each_fails is None:
                return None
            fails = fails | each_fails
        return fails
    if type(validator) is _OPTIONAL_VALIDATOR:
        inner = _validator_fails(validator.validator, column)
        return None if inner is None else inner & ~column.missing
    if (
        type(validator) is _NUMBER_VALIDATOR
        and type(validator.bound) in (int, float)
        and column.values.dtype.is_numeric()
    ):
        compare = _BOUNDS[validator.compare_op]
        # None fails: Python can't compare it
        return ~(compare(column.values, validator.bound).fill_null(value=False) & ~column.missing)
    return None


def _validator_refusal(field: attrs.Attribute[Any], column: _Column) -> Callable[[int], None]:
    def refuse(row: int) -> None:
        # the row class's own validator, for its message
        value = None if column.missing[row] else column.values[row : row + 1].to_list()[0]
        try:
            field.validator(None, field, value)  # type: ignore[misc]
        except (ValueError, TypeError) as error:
            raise RefusedError(str(error)) from error

    return refuse
