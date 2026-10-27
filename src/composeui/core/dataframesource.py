"""A dataframe's rows in a large table, a chart or a map: pandas, Polars, PyArrow, lazy...

`narwhals` (the ``dataframe`` extra) reads each library's frame through one API, so the
library sorts and filters the rows with its own expressions, never row by row in Python.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, Optional, Union

import narwhals as nw

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
    from collections.abc import Hashable, Mapping, Sequence

    from narwhals.typing import IntoFrame

    from composeui.core.view import Filter, Sort

__all__ = ["DataFrameSource", "points_of", "series_of"]

#: the column of the rows' ids added to a frame without an `id_column`
ROW_ID = "__composeui_id"
_EMPTY_KEY = "__composeui_empty"
_SORT_KEY = "__composeui_key"

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
    if dtype == nw.Boolean:
        return bool
    if dtype.is_integer():
        return int
    if dtype.is_numeric():  # a float or a decimal
        return float
    if dtype == nw.Datetime:
        return datetime.datetime
    if dtype == nw.Date:
        return datetime.date
    return str  # a text, a category, or a type shown as its text


class DataFrameSource:
    """A `TableSource` of a dataframe's rows, which a large table reads a window at a time.

    Build it with any frame `narwhals` reads (pandas, Polars, PyArrow, a Polars
    ``LazyFrame``...) and the headers by column: ``DataFrameSource(frame, {"lat":
    T("Latitude")})``, every column under its name without them. A row's id is its
    position in the frame, or its `id_column` when it has one: a lazy frame needs one, its
    rows having no position of their own. Assign a new `frame` to change the rows, which
    emits `changed`.

    The frame's library sorts and filters: a text compares in lower case, which isn't
    Python's ``casefold`` ("ß" doesn't find "SS"), and a ``/regex/`` is in the library's
    syntax (Rust's ``regex`` for Polars, ``re`` for pandas). Equal cells, and the rows
    unsorted, keep the frame's order.
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
        schema = self._frame.collect_schema()
        names = list(schema) if headers is None else list(headers)
        for name in [*names, *([] if id_column is None else [id_column])]:
            if name not in schema:
                msg = f"Cannot build a DataFrameSource: the frame has no column {name!r}."
                raise ValueError(msg)
        self._columns = {
            name: SourceColumn(
                name, name if headers is None else headers[name], _python_type(schema[name])
            )
            for name in names
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
        self._native, self._frame = frame, wrapped
        self._changed.emit()

    @property
    def _id(self) -> str:
        return ROW_ID if self._id_column is None else self._id_column

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
        conditions = [
            self._condition(self._column(name), row_filter) for name, row_filter in filters.items()
        ]
        needle = search.strip().casefold()
        if needle != "":
            texts = [
                _text(name)
                for name, column in self._columns.items()
                if column_kind(column.type) is ColumnKind.TEXT
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
            empty = cell.is_null() | (cell.cast(nw.String) == "") if is_text else cell.is_null()
            key = cell.cast(nw.String).str.to_lowercase() if is_text else cell
            ordered = (
                frame.select(self._id, empty.alias(_EMPTY_KEY), key.alias(_SORT_KEY))
                # the empty cells last in both orders, equal cells in the frame's order
                .sort(
                    _EMPTY_KEY,
                    _SORT_KEY,
                    self._id,
                    descending=[False, sort.descending, False],
                    nulls_last=True,
                )
                .select(self._id)
            )
        return list(_collected(ordered).get_column(self._id).to_list())

    def cells(self, ids: Sequence[Hashable], columns: Sequence[str]) -> dict[Hashable, list[Any]]:
        names = [self._column(name).name for name in columns]
        rows = _collected(
            self._frame.filter(nw.col(self._id).is_in(list(ids))).select(self._id, *names)
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
    def _condition(column: SourceColumn, row_filter: Filter) -> nw.Expr:
        """Get the expression of `row_filter` on `column`, as `Filter.matches` reads a cell.

        An empty cell's text is "", and it fails a comparison.
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
            text = cell.cast(nw.String).fill_null("")
            return text.str.contains(f"(?i){value.pattern}")
        if operator is FilterOperator.RANGE:
            compared = cell.is_between(value, row_filter.upper)
        else:
            compared = _comparison(cell, operator, value)
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
    return nw.col(name).cast(nw.String).fill_null("").str.to_lowercase()


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
    if hasattr(value, "item"):  # a numpy scalar
        return value.item()
    return value


def _collected(frame: Union[nw.DataFrame[Any], nw.LazyFrame[Any]]) -> nw.DataFrame[Any]:
    return frame.collect() if isinstance(frame, nw.LazyFrame) else frame
