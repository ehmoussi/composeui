"""A large table's source of a dataframe's rows: pandas, Polars, and a Polars lazy frame."""

from __future__ import annotations

import contextlib
import datetime
from typing import TYPE_CHECKING, Any, Callable, Optional

import attrs
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

pytest.importorskip("narwhals")
pytest.importorskip("polars")
pytest.importorskip("pandas")
import pandas as pd
import polars as pl

from composeui.core.dataframesource import DataFrameSource, points_of, series_of
from composeui.core.view import FilterError, ListSource, MapPoint, Sort, parse_filter

if TYPE_CHECKING:
    from collections.abc import Hashable

    from narwhals.typing import IntoFrame

    from composeui.core.view import TableSource


@attrs.frozen
class Reading:
    name: Optional[str]
    value: Optional[float]
    count: Optional[int]
    at: Optional[datetime.datetime]
    ok: Optional[bool]


READINGS = [
    Reading("Bravo", 20.5, 2, datetime.datetime.fromisoformat("2024-01-03T08:00"), ok=True),
    Reading("alpha", None, 10, datetime.datetime.fromisoformat("2024-01-01T09:00"), ok=False),
    Reading("", 18.0, None, None, ok=True),
    Reading(None, 25.0, 9, datetime.datetime.fromisoformat("2024-01-02T00:00"), ok=None),
    Reading("Charlie", 20.5, 2, datetime.datetime.fromisoformat("2024-01-01T12:00"), ok=False),
    Reading("bravo", 30.0, 1, datetime.datetime.fromisoformat("2024-01-05T00:00"), ok=True),
    Reading("Delta b", 12.0, 3, datetime.datetime.fromisoformat("2023-12-31T00:00"), ok=False),
]
HEADERS = {"name": "Name", "value": "Value", "count": "Count", "at": "At", "ok": "OK"}
SCHEMA = {
    "name": pl.String,
    "value": pl.Float64,
    "count": pl.Int64,
    "at": pl.Datetime,
    "ok": pl.Boolean,
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
        }
    )


#: the source of each library's frame of some readings, by the library's name
FRAMES: dict[str, Callable[[list[Reading]], DataFrameSource]] = {
    "polars": lambda readings: DataFrameSource(
        pl.DataFrame(_columns(readings), schema=SCHEMA), HEADERS
    ),
    "pandas": lambda readings: DataFrameSource(_pandas(readings), HEADERS),
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
        2: ["", 18.0, None, None, True],
        0: ["Bravo", 20.5, 2, datetime.datetime.fromisoformat("2024-01-03T08:00"), True],
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
        ("duration", "duration", str),
    ]
    assert source.cells([0], ["day"]) == {0: [datetime.date(2024, 1, 1)]}
    # no text column holds a search
    assert DataFrameSource(frame, {"day": "Day"}).ordered_ids(None, "a", {}) == []


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
    ]


@pytest.mark.parametrize("library", ["polars", "pandas"])
def test_a_series_reads_two_columns_leaving_out_the_rows_missing_a_value(library: str) -> None:
    columns = {"hour": [0, 1, 2, 3], "pickups": [5.0, None, 7.0, 2.5]}
    frame = pl.DataFrame(columns) if library == "polars" else pd.DataFrame(columns)

    series = series_of(frame, "hour", "pickups")

    assert (series.name, series.x, series.y) == ("pickups", [0, 2, 3], [5.0, 7.0, 2.5])
    assert series_of(frame, "hour", "pickups", name="Pickups").name == "Pickups"


@pytest.mark.parametrize("library", ["polars", "pandas", "lazy"])
def test_map_points_leave_out_the_rows_missing_a_value_or_off_the_map(library: str) -> None:
    columns = {"lat": [40.7, None, 90.0, 40.8, 40.9], "lon": [-73.9, -73.8, 0.0, 200.0, None]}
    frames: dict[str, Callable[[], IntoFrame]] = {
        "polars": lambda: pl.DataFrame(columns),
        "pandas": lambda: pd.DataFrame(columns),
        "lazy": lambda: pl.LazyFrame(columns),
    }

    assert points_of(frames[library](), "lat", "lon") == [MapPoint(latitude=40.7, longitude=-73.9)]
