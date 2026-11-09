"""A large table's source of a dataframe's rows: pandas, Polars, PyArrow, and a lazy frame."""

from __future__ import annotations

import contextlib
import datetime
import decimal
import sys
from typing import TYPE_CHECKING, Any, Callable, Optional

import attrs
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

pytest.importorskip("narwhals")
pytest.importorskip("polars")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
import pandas as pd
import polars as pl

from composeui.core.dataframesource import (
    DataFrameSource,
    fill_from_frame,
    points_of,
    series_of,
)
from composeui.core.sqlitemodel import (
    CSVSqliteTable,
    RefusedError,
    SqliteModel,
    csv_field,
    define_csv_row,
    table,
)
from composeui.core.view import (
    FilterError,
    ListSource,
    MainView,
    MapPoint,
    Sort,
    SourceTableView,
    child,
    define_view,
    parse_filter,
)

if TYPE_CHECKING:
    from collections.abc import Hashable, Iterator
    from pathlib import Path

    from narwhals.typing import IntoFrame

    from composeui.core.view import TableSource


@attrs.frozen
class Reading:
    name: Optional[str]
    value: Optional[float]
    count: Optional[int]
    at: Optional[datetime.datetime]
    ok: Optional[bool]
    elapsed: Optional[datetime.timedelta] = None


READINGS = [
    Reading("Bravo", 20.5, 2, datetime.datetime.fromisoformat("2024-01-03T08:00"), ok=True),
    Reading("alpha", None, 10, datetime.datetime.fromisoformat("2024-01-01T09:00"), ok=False),
    Reading("", 18.0, None, None, ok=True),
    Reading(None, 25.0, 9, datetime.datetime.fromisoformat("2024-01-02T00:00"), ok=None),
    Reading("Charlie", 20.5, 2, datetime.datetime.fromisoformat("2024-01-01T12:00"), ok=False),
    Reading("bravo", 30.0, 1, datetime.datetime.fromisoformat("2024-01-05T00:00"), ok=True),
    Reading("Delta b", 12.0, 3, datetime.datetime.fromisoformat("2023-12-31T00:00"), ok=False),
]
HEADERS = {
    "name": "Name",
    "value": "Value",
    "count": "Count",
    "at": "At",
    "ok": "OK",
    "elapsed": "Elapsed",
}
SCHEMA = {
    "name": pl.String,
    "value": pl.Float64,
    "count": pl.Int64,
    "at": pl.Datetime,
    "ok": pl.Boolean,
    "elapsed": pl.Duration,
}


def _columns(readings: list[Reading]) -> dict[str, list[Any]]:
    return {name: [getattr(reading, name) for reading in readings] for name in HEADERS}


def _pandas(readings: list[Reading]) -> Any:
    # as pandas reads a file: NA in text, NaN in floats, NaT in dates
    return pd.DataFrame(_columns(readings)).astype(
        {
            "name": "string",
            "value": "float64",
            "count": "Int64",
            "at": "datetime64[ns]",
            "ok": "boolean",
            "elapsed": "timedelta64[ns]",
        }
    )


#: the source of each library's frame of some readings, by the library's name
FRAMES: dict[str, Callable[[list[Reading]], DataFrameSource]] = {
    "polars": lambda readings: DataFrameSource(
        pl.DataFrame(_columns(readings), schema=SCHEMA), HEADERS
    ),
    "pandas": lambda readings: DataFrameSource(_pandas(readings), HEADERS),
    "pyarrow": lambda readings: DataFrameSource(
        pl.DataFrame(_columns(readings), schema=SCHEMA).to_arrow(), HEADERS
    ),
    "lazy": lambda readings: DataFrameSource(
        pl.DataFrame(_columns(readings), schema=SCHEMA).with_row_index("key").lazy(),
        HEADERS,
        id_column="key",
    ),
}


@pytest.fixture(params=list(FRAMES))
def source(request: pytest.FixtureRequest) -> DataFrameSource:
    return FRAMES[request.param](READINGS)


#: (sort, search, filters by column): the same as a `ListSource` of the readings orders them
CASES: list[tuple[Optional[Sort], str, dict[str, str]]] = [
    (None, "", {}),
    *[(Sort(name, descending), "", {}) for name in HEADERS for descending in (False, True)],
    (None, " BRAVO ", {}),
    (Sort("value"), "a", {}),
    *[
        (None, "", {"name": text})
        for text in ["br", "!br", "=bravo", "!=bravo", "b*", "*a", "/^B.*O$/", "="]
    ],
    *[
        (None, "", {"value": text})
        for text in [">20", ">=20.5", "<20", "<=18", "!=20.5", "20.5", "18..25", "="]
    ],
    *[(None, "", {"at": text}) for text in [">2024-01-01T12:00", "2024-01-01..2024-01-03", "="]],
    *[(None, "", {"ok": text}) for text in ["true", "false", "="]],
    (Sort("name", descending=True), "", {"value": ">15", "count": "<10"}),
]


@pytest.mark.parametrize(("sort", "search", "texts"), CASES)
def test_a_dataframe_source_orders_its_rows_as_a_list_source_does(
    source: DataFrameSource,
    sort: Optional[Sort],
    search: str,
    texts: dict[str, str],
) -> None:
    reference = ListSource(Reading, HEADERS, READINGS)
    types = {column.name: column.type for column in source.columns}
    filters = {name: parse_filter(text, types[name]) for name, text in texts.items()}
    fields = attrs.fields_dict(attrs.resolve_types(Reading))
    reference_filters = {
        name: parse_filter(text, fields[name].type) for name, text in texts.items()
    }
    expected = reference.ordered_ids(sort, search, reference_filters)

    # the ids are the rows' positions, or the lazy frame's key holding them
    assert source.ordered_ids(sort, search, filters) == expected


# Generated readings, from few values so that cells are often equal, or equal but for
# their case. Their text holds a regular expression's and LIKE's characters, which
# compare as text, and a letter in two cases. Not letters whose lower case isn't their
# `casefold` ("ß"): the frame's library compares in lower case, by design.
# half from a pool of names that lower case orders otherwise ("B" and "a", "A" and "_")
_NAMES = st.sampled_from(["a", "A", "B", "b_", "_", "é", "É", "a.b"]) | st.text(
    st.sampled_from("aAbB_%.*\\' !=éÉ"), max_size=3
)
_VALUES = [12.0, 18.0, 20.5]
_COUNTS = [1, 2, 10]
_DURATIONS = [
    datetime.timedelta(seconds=90),
    datetime.timedelta(days=2),
    datetime.timedelta(days=10),
]
_TIMES = [
    datetime.datetime.fromisoformat(text) for text in ("2024-01-01T09:00", "2024-01-03T08:00")
]


@attrs.frozen
class _Query:
    """Readings and what a table asks of them: a sort, a search, and filters' texts."""

    readings: list[Reading]
    sort: Optional[Sort]
    search: str
    texts: dict[str, str]


@st.composite
def _queries(draw: st.DrawFn) -> _Query:
    """Draw readings, and a search and filters often typed as a name is, maybe in other cases."""
    readings = draw(
        st.lists(
            st.builds(
                Reading,
                st.none() | _NAMES,
                st.none() | st.sampled_from(_VALUES),
                st.none() | st.sampled_from(_COUNTS),
                st.none() | st.sampled_from(_TIMES),
                ok=st.none() | st.booleans(),
                elapsed=st.none() | st.sampled_from(_DURATIONS),
            ),
            max_size=8,
        )
    )
    texts = _NAMES
    names = sorted({reading.name for reading in readings if reading.name is not None})
    if names:
        named = st.sampled_from(names)
        texts = texts | named | named.map(str.swapcase)
    comparison = st.sampled_from(["", "=", "!=", "<", "<=", ">", ">="])

    def compared(values: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
        return st.builds("{}{}".format, comparison, values) | st.builds(
            "{}..{}".format, values, values
        )

    name_filter = st.builds(
        "{}{}{}".format,
        st.sampled_from(["", "=", "!=", "!", "*"]),
        texts,
        st.sampled_from(["", "*"]),
    )
    filter_texts = st.one_of(
        # text filters half the time: they have the most ways to differ
        st.tuples(st.just("name"), name_filter),
        st.tuples(st.just("name"), name_filter),
        st.tuples(st.just("value"), compared(st.sampled_from(_VALUES).map(str))),
        st.tuples(st.just("count"), compared(st.sampled_from(_COUNTS).map(str))),
        st.tuples(
            st.just("at"), compared(st.sampled_from(_TIMES).map(datetime.datetime.isoformat))
        ),
        st.tuples(st.just("ok"), st.sampled_from(["true", "false", "="])),
        st.tuples(
            st.just("elapsed"),
            compared(st.sampled_from(_DURATIONS).map(lambda d: str(d.total_seconds()))),
        ),
    )
    # mostly a sort, by name half the time: text has the most ways to sort apart
    sorted_by = st.builds(
        Sort, st.sampled_from(["name", *HEADERS, "name"]), descending=st.booleans()
    )
    sort = st.none() | sorted_by | sorted_by
    return _Query(readings, draw(sort), draw(texts), dict(draw(st.lists(filter_texts, max_size=2))))


# cheap examples, many: a difference needs a few cells and a filter to meet
@settings(max_examples=300)
@given(_queries())
# an empty text and a missing one, both empty: in the frame's order, not "" first
@example(
    _Query(
        [Reading(None, None, None, None, ok=None), Reading("", None, None, None, ok=None)],
        Sort("name"),
        "",
        {},
    )
)
def test_any_query_orders_a_dataframe_s_rows_as_a_list_source_does(query: _Query) -> None:
    reference = ListSource(Reading, HEADERS, query.readings)
    fields = attrs.fields_dict(attrs.resolve_types(Reading))
    filters = {}
    for name, text in query.texts.items():
        with contextlib.suppress(FilterError):  # e.g. an empty text
            filters[name] = parse_filter(text, fields[name].type)
    expected = reference.ordered_ids(query.sort, query.search, filters)
    for library, source in FRAMES.items():
        frame_source = source(query.readings)
        types = {column.name: column.type for column in frame_source.columns}
        frame_filters = {name: parse_filter(query.texts[name], types[name]) for name in filters}
        found = frame_source.ordered_ids(query.sort, query.search, frame_filters)
        assert found == expected, library


def test_cells_give_python_values_by_id_and_leave_out_the_ids_gone(
    source: DataFrameSource,
) -> None:
    cells = source.cells([2, 0, 99], list(HEADERS))

    assert cells == {
        2: ["", 18.0, None, None, True, None],
        0: ["Bravo", 20.5, 2, datetime.datetime.fromisoformat("2024-01-03T08:00"), True, None],
    }
    assert type(cells[0][1]) is float  # not numpy's, which a cell's format would show
    assert source.cells([3], ["name", "value"]) == {3: [None, 25.0]}
    assert source.count() == len(READINGS)


@pytest.mark.parametrize("library", ["polars", "pandas"])
def test_cells_show_the_id_column_when_it_is_one_of_the_columns(library: str) -> None:
    columns = {"order": [10, 11, 12], "amount": [1.5, 2.5, 3.5]}
    frame = pl.DataFrame(columns) if library == "polars" else pd.DataFrame(columns)
    source = DataFrameSource(frame, {"order": "Order", "amount": "Amount"}, id_column="order")

    assert source.cells([12, 10], ["order", "amount"]) == {12: [12, 3.5], 10: [10, 1.5]}
    assert source.cells([11], ["amount", "order"]) == {11: [2.5, 11]}


def test_the_columns_types_come_from_the_frame_s_schema() -> None:
    frame = pl.DataFrame(
        {
            "day": [datetime.date(2024, 1, 1)],
            "kind": ["a"],
            "duration": [datetime.timedelta(seconds=1)],
        },
        schema={"day": pl.Date, "kind": pl.Categorical, "duration": pl.Duration},
    )

    source = DataFrameSource(frame)  # every column, under its name

    assert [(column.name, column.header, column.type) for column in source.columns] == [
        ("day", "day", datetime.date),
        ("kind", "kind", str),
        ("duration", "duration", datetime.timedelta),
    ]
    assert source.cells([0], ["day"]) == {0: [datetime.date(2024, 1, 1)]}
    # no text column holds a search
    assert DataFrameSource(frame, {"day": "Day"}).ordered_ids(None, "a", {}) == []


_DAYS_AND_NONE: list[Optional[datetime.timedelta]] = [
    datetime.timedelta(days=10),
    None,
    datetime.timedelta(days=2),
    datetime.timedelta(seconds=90),
]


def _duration_frame(library: str) -> Any:
    columns = {"elapsed": _DAYS_AND_NONE, "name": ["w", "x", "y", "z"]}
    if library == "pandas":
        return pd.DataFrame(columns).astype({"elapsed": "timedelta64[ns]"})
    frame = pl.DataFrame(columns, schema={"elapsed": pl.Duration, "name": pl.String})
    return frame if library == "polars" else frame.to_arrow()


@pytest.mark.parametrize("library", ["polars", "pandas", "pyarrow"])
def test_a_duration_column_sorts_by_length_and_a_search_passes_over_it(library: str) -> None:
    source = DataFrameSource(_duration_frame(library))

    assert source.ordered_ids(Sort("elapsed", descending=False), "", {}) == [3, 2, 0, 1]
    assert source.ordered_ids(None, "x", {}) == [1]


@pytest.mark.parametrize("library", ["polars", "pandas", "pyarrow"])
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (">3600", [0, 2]),
        ("<=90", [3]),
        ("90", [3]),
        ("100..172800", [2]),
        ("=", [1]),
        (">1d 12h", [0, 2]),
        ("1m 30s", [3]),
        ("1m..2m", [3]),
        ("-1d..2d", [2, 3]),
    ],
)
def test_a_duration_column_filters_in_seconds(library: str, text: str, expected: list[int]) -> None:
    source = DataFrameSource(_duration_frame(library))
    row_filter = parse_filter(text, datetime.timedelta)

    assert source.ordered_ids(None, "", {"elapsed": row_filter}) == expected


@pytest.mark.parametrize("library", ["polars", "pandas", "pyarrow"])
def test_a_duration_cell_is_python_s_timedelta(library: str) -> None:
    source = DataFrameSource(_duration_frame(library))

    cell = source.cells([3], ["elapsed"])[3][0]

    assert type(cell) is datetime.timedelta
    assert cell == datetime.timedelta(seconds=90)


@pytest.mark.parametrize("library", ["polars", "pandas", "pyarrow"])
def test_a_duration_filter_near_the_longest_is_compared(library: str) -> None:
    source = DataFrameSource(_duration_frame(library))
    row_filter = parse_filter(">9223372036854", datetime.timedelta)

    assert source.ordered_ids(None, "", {"elapsed": row_filter}) == []


@given(
    st.timedeltas(
        min_value=datetime.timedelta(days=-30, seconds=-5),
        max_value=datetime.timedelta(days=30, seconds=5),
    )
)
def test_a_duration_reads_back_as_its_cell_shows_it(duration: datetime.timedelta) -> None:
    table = SourceTableView(source=DataFrameSource(pl.DataFrame({"elapsed": [duration]})))
    text = table.rows(0, 1)[0][1][0]

    assert parse_filter(f"={text}", datetime.timedelta).value == duration


@pytest.mark.parametrize(
    "text", [">soon", ">1e400", ">9223372036855", ">1h 2d", ">-", ">1d 99999999999999d"]
)
def test_a_duration_filter_that_is_no_number_of_seconds_is_refused(text: str) -> None:
    with pytest.raises(FilterError):
        parse_filter(text, datetime.timedelta)


@pytest.mark.parametrize(
    ("duration", "text"),
    [
        (datetime.timedelta(0), "0s"),
        (datetime.timedelta(minutes=2), "2m"),
        (datetime.timedelta(days=1, hours=2, minutes=30), "1d 2h 30m"),
        (datetime.timedelta(seconds=-1.5), "-1.5s"),
        (datetime.timedelta(days=1, seconds=5, microseconds=10), "1d 5.00001s"),
    ],
)
def test_a_duration_cell_shows_its_units(duration: datetime.timedelta, text: str) -> None:
    table = SourceTableView(source=DataFrameSource(pl.DataFrame({"elapsed": [duration]})))

    assert table.rows(0, 1) == [(0, [text])]


_INSTANTS = [
    datetime.datetime(2024, 1, 1, 23, 30, tzinfo=datetime.timezone.utc),  # 00:30 in Paris
    datetime.datetime(2024, 1, 2, 0, 30, tzinfo=datetime.timezone.utc),  # 01:30 in Paris
    None,
]


def _paris_frame(library: str) -> Any:
    if library == "pandas":
        return pd.DataFrame(
            {"time": pd.to_datetime(pd.Series(_INSTANTS), utc=True).dt.tz_convert("Europe/Paris")}
        )
    utc = pl.DataFrame({"time": _INSTANTS}, schema={"time": pl.Datetime("us", "UTC")})
    frame = utc.with_columns(pl.col("time").dt.convert_time_zone("Europe/Paris"))
    return frame if library == "polars" else frame.to_arrow()


@pytest.mark.parametrize(
    "library",
    [
        "polars",
        "pandas",
        pytest.param(
            "pyarrow",
            marks=pytest.mark.skipif(
                sys.platform == "win32" and sys.version_info < (3, 10),
                reason="PyArrow 21 has no time zone database on Windows",
            ),
        ),
    ],
)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # the clock of the column: read in UTC, the first row would be before it
        (">2024-01-02", [0, 1]),
        # an instant: on the clock of the column, the first row would be after it
        (">2024-01-02T01:00:00+01:00", [1]),
        ("2024-01-01T23:00:00+00:00..2024-01-02T01:00:00+01:00", [0]),
        ("2024-01-02T00:00:00..2024-01-02T01:00:00", [0]),
        ("=", [2]),
    ],
)
def test_a_date_filter_on_a_column_with_a_time_zone(
    library: str, text: str, expected: list[int]
) -> None:
    source = DataFrameSource(_paris_frame(library))
    row_filter = parse_filter(text, datetime.datetime)

    assert source.ordered_ids(None, "", {"time": row_filter}) == expected


@pytest.mark.parametrize("library", ["polars", "pandas", "pyarrow"])
def test_a_date_with_a_zone_filters_a_column_without_one_by_its_clock(library: str) -> None:
    times = ["2024-01-02T00:30:00", "2024-01-01T00:00:00"]
    columns = {"time": [datetime.datetime.fromisoformat(time) for time in times]}
    frame: Any = pd.DataFrame(columns) if library == "pandas" else pl.DataFrame(columns)
    frame = frame.to_arrow() if library == "pyarrow" else frame
    source = DataFrameSource(frame)
    row_filter = parse_filter(">2024-01-02T00:00:00+05:00", datetime.datetime)

    assert source.ordered_ids(None, "", {"time": row_filter}) == [0]


@pytest.mark.parametrize("text", [">0001-01-01T00:00:00+05:00", ">9999-12-31T23:59:59-05:00"])
def test_a_date_with_a_zone_at_the_end_of_the_calendar_is_refused(text: str) -> None:
    with pytest.raises(FilterError):
        parse_filter(text, datetime.datetime)


def test_a_date_range_with_a_time_zone_at_one_end_only_is_refused() -> None:
    with pytest.raises(FilterError):
        parse_filter("2024-01-02T00:00:00..2024-01-03T00:00:00+00:00", datetime.datetime)


@pytest.mark.parametrize(
    "column",
    [
        pd.Series(["apple", None], dtype=object),
        pd.Series(["apple", float("nan")], dtype=object),
        pd.Series(["apple", None], dtype="category"),
    ],
    ids=["none", "nan", "category"],
)
@pytest.mark.parametrize(("search", "row_filter"), [("n", None), ("", "/n/"), ("", "=none")])
def test_an_empty_pandas_cell_has_no_text_to_find(
    column: pd.Series, search: str, row_filter: Optional[str]
) -> None:
    source = DataFrameSource(pd.DataFrame({"name": column}))
    filters = {} if row_filter is None else {"name": parse_filter(row_filter)}

    assert source.ordered_ids(None, search, filters) == []


@pytest.mark.parametrize("descending", [False, True])
def test_empty_pandas_cells_sort_together_in_the_frame_s_order(*, descending: bool) -> None:
    frame = pd.DataFrame({"name": pd.Series(["", None, "", "b"], dtype=object)})

    ids = DataFrameSource(frame).ordered_ids(Sort("name", descending=descending), "", {})

    assert ids == [3, 0, 1, 2]


_DECIMALS = [decimal.Decimal("1.10"), decimal.Decimal("2.25"), None]


def _decimal_frame(library: str) -> Any:
    if library == "pandas":
        return pd.DataFrame({"amount": pd.Series(_DECIMALS, dtype=object)})
    frame = pl.DataFrame({"amount": _DECIMALS}, schema={"amount": pl.Decimal(10, 2)})
    return frame if library == "polars" else frame.to_arrow()


@pytest.mark.parametrize("library", ["polars", "pandas", "pyarrow"])
@pytest.mark.parametrize(
    ("text", "expected"), [("=1.10", [0]), (">1.5", [1]), ("1..2", [0]), ("=", [2])]
)
def test_a_decimal_column_filters_as_numbers(library: str, text: str, expected: list[int]) -> None:
    source = DataFrameSource(_decimal_frame(library))
    row_filter = parse_filter(text, source.columns[0].type)

    assert source.ordered_ids(None, "", {"amount": row_filter}) == expected


@pytest.mark.parametrize("library", ["polars", "pandas", "pyarrow"])
def test_a_decimal_column_sorts_as_numbers_and_a_search_passes_over_it(library: str) -> None:
    source = DataFrameSource(_decimal_frame(library))

    assert source.ordered_ids(Sort("amount", descending=True), "", {}) == [1, 0, 2]
    assert source.ordered_ids(None, "1", {}) == []
    assert source.cells([0], ["amount"]) == {0: [decimal.Decimal("1.10")]}


def test_a_pandas_object_column_not_all_decimals_is_text() -> None:
    values = [decimal.Decimal("1.10"), "a", None]
    source = DataFrameSource(pd.DataFrame({"amount": pd.Series(values, dtype=object)}))

    assert source.columns[0].type is str


@pytest.mark.parametrize(
    ("first", "second", "row_filter", "kept"),
    [
        (pl.DataFrame({"a": [1, 2]}), pl.DataFrame({"a": ["x", ">1"]}), ">1", [1]),
        (pl.DataFrame({"a": ["x"]}), pl.DataFrame({"a": [1, 2]}), ">1", [1]),
        (
            pd.DataFrame({"a": pd.Series([decimal.Decimal(2)], dtype=object)}),
            pd.DataFrame({"a": ["x", ">1"]}),
            ">1",
            [1],
        ),
        # a date that a duration column can't read filters nothing
        (
            pl.DataFrame({"a": [datetime.date(2024, 1, 1)]}),
            pl.DataFrame({"a": [datetime.timedelta(days=1)]}),
            ">2023-01-01",
            [0],
        ),
    ],
    ids=["number to text", "text to number", "decimal to text", "date to duration"],
)
def test_a_table_s_filter_follows_the_types_of_a_new_frame(
    first: Any, second: Any, row_filter: str, kept: list[int]
) -> None:
    source = DataFrameSource(first)
    table = SourceTableView(source=source, filters={"a": row_filter})

    source.frame = second

    assert table.ids(0, 5) == kept


def test_a_new_frame_keeps_the_columns_and_their_headers() -> None:
    source = DataFrameSource(pl.DataFrame({"a": [1]}), {"a": "First"})

    source.frame = pl.DataFrame({"a": ["x"], "b": [2]})

    assert [(c.name, c.header, c.type) for c in source.columns] == [("a", "First", str)]


def test_a_new_frame_without_a_column_is_refused_and_changes_nothing() -> None:
    first = pl.DataFrame({"a": [1], "id": [7]})
    source = DataFrameSource(first)
    changes: list[None] = []
    source.changed.connect(lambda: changes.append(None))

    with pytest.raises(ValueError, match="no column 'a'"):
        source.frame = pl.DataFrame({"id": [8]})

    assert source.frame is first
    assert changes == []
    assert source.columns[0].type is int


def _list_frame(library: str, dtype: Any) -> Any:
    frame = pl.DataFrame(
        {"values": [[3, 1], [2, 2]], "name": ["a", "b"]},
        schema={"values": dtype, "name": pl.String},
    )
    return frame if library == "polars" else frame.to_arrow()


_LIST_FRAMES = [
    ("polars", pl.List(pl.Int64)),
    ("polars", pl.Array(pl.Int64, 2)),
    ("pyarrow", pl.List(pl.Int64)),
]


@pytest.mark.parametrize(("library", "dtype"), _LIST_FRAMES)
def test_a_search_passes_over_a_column_of_lists(library: str, dtype: Any) -> None:
    source = DataFrameSource(_list_frame(library, dtype))

    assert source.ordered_ids(None, "b", {}) == [1]


@pytest.mark.parametrize(("library", "dtype"), _LIST_FRAMES)
def test_a_filter_and_a_sort_on_a_column_of_lists_do_nothing(library: str, dtype: Any) -> None:
    source = DataFrameSource(_list_frame(library, dtype))
    row_filter = parse_filter("=nothing")

    assert source.ordered_ids(Sort("values", descending=True), "", {"values": row_filter}) == [
        0,
        1,
    ]


def test_a_new_frame_changes_the_rows_and_emits_changed() -> None:
    first = pl.DataFrame({"name": ["a", "b"]})
    source = DataFrameSource(first)
    changes: list[None] = []
    source.changed.connect(lambda: changes.append(None))

    second = pl.DataFrame({"name": ["c"]})
    source.frame = second

    assert changes == [None]
    assert source.frame is second
    assert source.count() == 1
    assert source.cells([0, 1], ["name"]) == {0: ["c"]}


_FIRST_ROWS = pl.DataFrame({"id": [10, 11, 12], "name": ["a", "b", "c"]})
_OTHER_ROWS = pl.DataFrame({"id": [20, 21, 22], "name": ["x", "y", "z"]})


def _assign_frame(table: SourceTableView) -> None:
    source = table.source
    assert isinstance(source, DataFrameSource)
    source.frame = _OTHER_ROWS


def _assign_source(table: SourceTableView) -> None:
    table.source = DataFrameSource(_OTHER_ROWS)


@pytest.mark.parametrize("replace", [_assign_frame, _assign_source])
def test_new_rows_clear_the_selection_of_positions_and_emit_it(
    replace: Callable[[SourceTableView], None],
) -> None:
    table = SourceTableView(source=DataFrameSource(_FIRST_ROWS))
    table.selected_ids = [1]
    emitted: list[list[Any]] = []
    table.selection_changed.connect(emitted.append)

    replace(table)

    assert table.selected_ids == []
    assert emitted == [[]]


def test_a_positional_source_replacing_one_with_ids_clears_the_selection() -> None:
    table = SourceTableView(source=DataFrameSource(_FIRST_ROWS, id_column="id"))
    table.selected_ids = [11]

    table.source = DataFrameSource(pl.DataFrame({"name": [str(n) for n in range(20)]}))

    assert table.selected_ids == []


def test_new_rows_with_ids_keep_the_selection_of_the_rows_still_there() -> None:
    source = DataFrameSource(_FIRST_ROWS, id_column="id")
    table = SourceTableView(source=source)
    table.selected_ids = [11]
    emitted: list[list[Any]] = []
    table.selection_changed.connect(emitted.append)

    source.frame = pl.DataFrame({"id": [11, 13], "name": ["new b", "d"]})

    assert (table.selected_ids, emitted) == ([11], [])


@define_view
class _FrameMainView(MainView):
    table: SourceTableView = child(SourceTableView)


def test_a_study_opened_before_its_frame_is_given_keeps_the_selection(tmp_path: Path) -> None:
    main_view = _FrameMainView()
    main_view.table.source = DataFrameSource(_FIRST_ROWS)
    main_view.table.selected_ids = [1]
    path = tmp_path / "study.json"
    main_view.save_state(path)

    reopened = _FrameMainView()
    reopened.load_state(path)
    reopened.table.source = DataFrameSource(_FIRST_ROWS)

    assert reopened.table.selected_ids == [1]


@pytest.mark.parametrize("library", ["polars", "pandas"])
@pytest.mark.parametrize("descending", [False, True])
def test_equal_cells_keep_the_frame_s_order_whatever_their_ids(
    library: str, *, descending: bool
) -> None:
    columns = {"id": [3, 1, 2], "score": [5, 5, 5]}
    frame = pl.DataFrame(columns) if library == "polars" else pd.DataFrame(columns)
    source = DataFrameSource(frame, id_column="id")
    assert source.ordered_ids(Sort("score", descending), "", {}) == [3, 1, 2]


def test_a_lazy_frame_needs_an_id_column() -> None:
    with pytest.raises(TypeError, match="lazy frame without an id_column"):
        DataFrameSource(pl.LazyFrame({"name": ["a"]}))


def test_a_column_the_frame_does_not_have_is_refused(source: DataFrameSource) -> None:
    with pytest.raises(ValueError, match="'area'"):
        source.ordered_ids(Sort("area"), "", {})
    with pytest.raises(ValueError, match="'area'"):
        source.ordered_ids(None, "", {"area": parse_filter(">1", float)})
    with pytest.raises(ValueError, match="'area'"):
        source.cells([0], ["area"])
    with pytest.raises(ValueError, match="no column 'area'"):
        DataFrameSource(pl.DataFrame({"name": ["a"]}), {"area": "Area"})
    with pytest.raises(ValueError, match="no column 'key'"):
        DataFrameSource(pl.DataFrame({"name": ["a"]}), id_column="key")


def test_a_dataframe_source_is_a_table_source(source: DataFrameSource) -> None:
    # checked by mypy: a source the large table takes
    table_source: TableSource[Hashable] = source
    assert [column.type for column in table_source.columns] == [
        str,
        float,
        int,
        datetime.datetime,
        bool,
        datetime.timedelta,
    ]


@pytest.mark.parametrize("library", ["polars", "pandas"])
def test_a_series_reads_two_columns_leaving_out_the_rows_missing_a_value(library: str) -> None:
    columns = {"hour": [0, 1, 2, 3], "pickups": [5.0, None, 7.0, 2.5]}
    frame = pl.DataFrame(columns) if library == "polars" else pd.DataFrame(columns)

    series = series_of(frame, "hour", "pickups")

    assert (series.name, series.x, series.y) == ("pickups", [0, 2, 3], [5.0, 7.0, 2.5])
    assert series_of(frame, "hour", "pickups", name="Pickups").name == "Pickups"


@pytest.mark.parametrize("library", ["polars", "pandas", "lazy", "pyarrow"])
def test_map_points_leave_out_the_rows_missing_a_value_or_off_the_map(library: str) -> None:
    columns = {"lat": [40.7, None, 90.0, 40.8, 40.9], "lon": [-73.9, -73.8, 0.0, 200.0, None]}
    frames: dict[str, Callable[[], IntoFrame]] = {
        "polars": lambda: pl.DataFrame(columns),
        "pandas": lambda: pd.DataFrame(columns),
        "lazy": lambda: pl.LazyFrame(columns),
        "pyarrow": lambda: pl.DataFrame(columns).to_arrow(),
    }

    assert points_of(frames[library](), "lat", "lon") == [MapPoint(latitude=40.7, longitude=-73.9)]


@define_csv_row
class _Measure:
    name: str
    count: int
    level: float
    day: datetime.date
    at: datetime.datetime = csv_field("taken at", date_format="%d/%m/%Y %H:%M")
    note: Optional[str] = None
    extra: Optional[int] = None


class _Measures(CSVSqliteTable, row_type=_Measure, name="measures"):
    pass


class _MeasuresModel(SqliteModel):
    measures = table(_Measures)


_DAY = datetime.date(2026, 1, 2)
_AT = datetime.datetime(2026, 1, 2, 3, 4)  # noqa: DTZ001 (naive on purpose)
_MEASURES: dict[str, list[Any]] = {
    "name": ["a", "b"],
    "count": [1, 2],
    "level": [0.5, 1.5],
    "day": [_DAY, _DAY],
    "taken at": [_AT, _AT],
    "note": ["kept", None],
    "extra": [7, None],
    "ignored": [0, 0],
}
_MEASURE_FRAMES: dict[str, Callable[[], IntoFrame]] = {
    "polars": lambda: pl.DataFrame(_MEASURES),
    "pyarrow": lambda: pl.DataFrame(_MEASURES).to_arrow(),
    "lazy": lambda: pl.LazyFrame(_MEASURES),
    "pandas, NaN": lambda: pd.DataFrame(_MEASURES),
    "pandas, NA": lambda: pd.DataFrame(_MEASURES).astype({"extra": "Int64"}),
}


@pytest.fixture
def measures_model() -> Iterator[_MeasuresModel]:
    model = _MeasuresModel()
    yield model
    model.close()


def _stored(model: _MeasuresModel) -> list[tuple[Any, ...]]:
    with model.measures.connection() as db:
        return [tuple(row) for row in db.execute("SELECT * FROM measures ORDER BY name")]


_STORED = [
    ("a", 1, 0.5, "2026-01-02", "2026-01-02T03:04:00", "kept", 7),
    ("b", 2, 1.5, "2026-01-02", "2026-01-02T03:04:00", None, None),
]


@pytest.mark.parametrize("batch_size", [1, 100])
@pytest.mark.parametrize("library", _MEASURE_FRAMES)
def test_a_frame_fills_a_table_with_its_typed_values_and_its_nulls(
    measures_model: _MeasuresModel, library: str, batch_size: int
) -> None:
    frame = _MEASURE_FRAMES[library]()

    counts = list(fill_from_frame(measures_model.measures, frame, batch_size=batch_size))

    assert counts[-1] == 2
    assert _stored(measures_model) == _STORED


def test_a_parquet_file_fills_a_table_through_the_app_s_own_reader(
    measures_model: _MeasuresModel, tmp_path: Path
) -> None:
    path = tmp_path / "measures.parquet"
    pl.DataFrame(_MEASURES).write_parquet(path)

    for _ in fill_from_frame(measures_model.measures, pl.scan_parquet(path)):
        pass

    assert _stored(measures_model) == _STORED


def test_an_import_of_a_frame_stopped_or_refused_keeps_no_row(
    measures_model: _MeasuresModel,
) -> None:
    frame = pl.DataFrame(_MEASURES)
    with contextlib.closing(
        fill_from_frame(measures_model.measures, frame, batch_size=1)
    ) as batches:
        assert next(batches) == 1  # as a canceled job stops reading
    assert _stored(measures_model) == []

    # a null where the row class wants a value, after a good row: as a text too, not "None"
    for column in ("count", "name"):
        refused = pl.DataFrame({**_MEASURES, column: [_MEASURES[column][0], None]})
        with pytest.raises(RefusedError, match=f"no value for {column}"):
            list(fill_from_frame(measures_model.measures, refused, batch_size=1))
        assert _stored(measures_model) == []


def test_a_number_is_refused_in_a_date_field_with_a_format(
    measures_model: _MeasuresModel,
) -> None:
    frame = pl.DataFrame({**_MEASURES, "taken at": [1, 2]})

    with pytest.raises(RefusedError):
        list(fill_from_frame(measures_model.measures, frame))

    assert _stored(measures_model) == []


@pytest.mark.parametrize(
    ("column", "values"),
    [
        ("count", [1.9, 2.0]),  # would be stored as 1
        ("day", [_AT, _DAY]),  # its hour would be lost
    ],
    ids=["a fraction in an int", "an hour in a date"],
)
def test_a_frame_s_value_that_would_lose_something_is_refused(
    measures_model: _MeasuresModel, column: str, values: list[Any]
) -> None:
    frame = pd.DataFrame({**_MEASURES, column: values})

    with pytest.raises(RefusedError, match=column):
        list(fill_from_frame(measures_model.measures, frame))

    assert _stored(measures_model) == []


def test_a_nan_of_polars_is_a_missing_value(measures_model: _MeasuresModel) -> None:
    """Not its null: `is_null` doesn't find it. SQLite would store it as NULL anyway."""
    frame = pl.DataFrame({**_MEASURES, "level": [float("nan"), 1.5]})

    with pytest.raises(RefusedError, match="no value for level"):
        list(fill_from_frame(measures_model.measures, frame))

    assert _stored(measures_model) == []


def test_a_frame_without_an_optional_column_gives_its_field_s_default(
    measures_model: _MeasuresModel,
) -> None:
    columns = {name: values for name, values in _MEASURES.items() if name != "extra"}

    list(fill_from_frame(measures_model.measures, pl.DataFrame(columns)))

    assert [row[-1] for row in _stored(measures_model)] == [None, None]


def test_a_frame_s_value_converts_when_nothing_is_lost(
    measures_model: _MeasuresModel,
) -> None:
    """Pandas holds an int column with a null as floats, and any date as a date and time."""
    midnight = datetime.datetime.combine(_DAY, datetime.time())
    frame = pd.DataFrame(
        {**_MEASURES, "count": [1.0, 2.0], "day": pd.to_datetime([midnight, midnight])}
    )

    list(fill_from_frame(measures_model.measures, frame))

    assert _stored(measures_model) == _STORED


def test_a_date_of_a_frame_fits_a_date_field_with_a_format(
    measures_model: _MeasuresModel,
) -> None:
    """A date column in a field of date and time: no text to parse with the format."""
    frame = pl.DataFrame({**_MEASURES, "taken at": [_DAY, _DAY]})

    list(fill_from_frame(measures_model.measures, frame))

    assert _stored(measures_model)[0][4] == "2026-01-02T00:00:00"
