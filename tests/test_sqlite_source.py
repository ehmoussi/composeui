"""A large table's rows from SQLite (`SqliteSource`): as a `ListSource` gives the same rows."""

from __future__ import annotations

import datetime
import enum
import re
import sqlite3
import threading
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

import attrs
import pytest

from composeui.core import sqlitemodel
from composeui.core.sqlitemodel import SqliteModel, SqliteSource, SqliteTable, as_parameters
from composeui.core.view import ListSource, Sort, SourceColumn, SourceTableView, parse_filter

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Iterator, Sequence

    from composeui.core.view import Filter


class Kind(enum.Enum):
    LAKE = "lake"
    HARBOUR = "harbour"


@attrs.frozen
class Place:
    id: int
    name: str
    depth: Optional[float]
    surveyed: Optional[datetime.date]
    kind: Kind


PLACES = [
    Place(1, "Lake", 12.5, datetime.date(2024, 1, 31), Kind.LAKE),
    Place(2, "harbour", 3.0, None, Kind.HARBOUR),
    Place(3, "Pond 100%", None, datetime.date(2023, 6, 1), Kind.LAKE),
    Place(4, "O'Brien bay", 7.25, datetime.date(2024, 5, 2), Kind.HARBOUR),
    Place(5, "lake", 12.5, None, Kind.LAKE),
    Place(6, "", 0.5, datetime.date(2022, 2, 2), Kind.HARBOUR),
    # SQLite folds the case of ASCII letters alone
    Place(8, "Grande École", None, None, Kind.LAKE),
    Place(9, "Straße", 1.0, None, Kind.HARBOUR),
]
HEADERS = {"name": "Name", "depth": "Depth", "surveyed": "Surveyed", "kind": "Kind"}


class Places(SqliteTable):
    create = (
        "CREATE TABLE place(id INTEGER PRIMARY KEY, name TEXT NOT NULL, depth REAL,"
        " surveyed TEXT, kind TEXT NOT NULL);"
        # a filter on depth may read by it: the rows mustn't come in its order
        "CREATE INDEX place_depth ON place(depth);"
    )

    def add(self, place: Place) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO place VALUES (:id, :name, :depth, :surveyed, :kind)",
                as_parameters(place),
            )


class PlacesModel(SqliteModel):
    def __init__(self) -> None:
        super().__init__()
        self.places = self.add_table(Places)


@pytest.fixture
def model() -> Iterator[PlacesModel]:
    model = PlacesModel()
    for place in PLACES:
        model.places.add(place)
    yield model
    model.close()


@pytest.fixture
def sql(model: PlacesModel) -> SqliteSource:
    listed = ListSource(Place, HEADERS)
    return SqliteSource(
        model.places,
        "SELECT * FROM place",
        id_column="id",
        columns=[
            SourceColumn(column.name, column.header, column.type) for column in listed.columns
        ],
    )


@pytest.fixture
def listed() -> ListSource[Place]:
    return ListSource(Place, HEADERS, PLACES, id_field="id")


def _both(
    sql: SqliteSource,
    listed: ListSource[Place],
    sort: Optional[Sort] = None,
    search: str = "",
    filters: Optional[dict[str, Filter]] = None,
) -> tuple[Sequence[Hashable], Sequence[Hashable]]:
    return (
        sql.ordered_ids(sort, search, filters or {}),
        listed.ordered_ids(sort, search, filters or {}),
    )


@pytest.mark.parametrize(
    ("column", "text"),
    [
        ("name", "LAKE"),
        ("name", "!lake"),
        ("name", "=lake"),
        ("name", "!=lake"),
        ("name", "o'*"),
        ("name", "*BAY"),
        ("name", "/^(pond|harbour)/"),
        ("name", "100%"),
        ("name", "="),
        ("name", "école"),
        ("name", "=GRANDE ÉCOLE"),
        ("name", "!=grande école"),
        ("name", "!école"),
        ("name", "*ÉCOLE"),
        ("name", "grande é*"),
        ("name", "Straße"),
        ("depth", ">7.25"),
        ("depth", ">=7.25"),
        ("depth", ">=3"),
        ("depth", "<3"),
        ("depth", "<=3"),
        ("depth", "!=12.5"),
        ("depth", "12.5"),
        ("depth", "3..12.5"),
        ("depth", "="),
        ("surveyed", ">=2024-01-31"),
        ("surveyed", "2023-06-01..2024-02-01"),
        ("kind", "=harbour"),
    ],
)
def test_each_filter_keeps_the_rows_a_list_source_keeps(
    sql: SqliteSource, listed: ListSource[Place], column: str, text: str
) -> None:
    field_type = next(c.type for c in listed.columns if c.name == column)
    found, expected = _both(sql, listed, filters={column: parse_filter(text, field_type)})
    assert found == expected, text  # in the source's order: unsorted, by id


@pytest.mark.parametrize("column", ["name", "depth", "surveyed", "kind"])
@pytest.mark.parametrize("descending", [False, True])
def test_a_sort_orders_as_a_list_source_empty_cells_last(
    sql: SqliteSource, listed: ListSource[Place], column: str, *, descending: bool
) -> None:
    found, expected = _both(sql, listed, sort=Sort(column, descending=descending))
    assert found == expected


def test_a_search_finds_its_text_as_typed_in_the_text_columns(
    model: PlacesModel, sql: SqliteSource, listed: ListSource[Place]
) -> None:
    # a quote, and LIKE's wildcards, are text
    for needle in ("o'b", "100%", "_", " HARBOUR ", "ÉCOLE", "straße"):
        found, expected = _both(sql, listed, search=needle)
        assert found == expected, needle
    assert sql.ordered_ids(None, "12.5", {}) == []  # no text column holds it
    # a source without text columns: no row holds any text
    columns = [SourceColumn("depth", "Depth", Optional[float])]
    numbers = SqliteSource(model.places, "SELECT * FROM place", id_column="id", columns=columns)
    numbered = ListSource(Place, {"depth": "Depth"}, PLACES, id_field="id")
    assert numbers.ordered_ids(None, "5", {}) == numbered.ordered_ids(None, "5", {}) == []


def test_cells_read_the_rows_asked_as_their_columns_types(sql: SqliteSource) -> None:
    assert sql.count() == len(PLACES)
    assert sql.cells([3, 2, 99], ["surveyed", "kind", "depth"]) == {
        3: [datetime.date(2023, 6, 1), Kind.LAKE, None],
        2: [None, Kind.HARBOUR, 3.0],
    }


def test_a_column_the_source_does_not_declare_is_refused(sql: SqliteSource) -> None:
    hostile = 'id" FROM place; --'  # a name that would end the query, were it pasted in
    with pytest.raises(ValueError, match="declares none"):
        sql.ordered_ids(Sort(hostile), "", {})
    with pytest.raises(ValueError, match="declares none"):
        sql.ordered_ids(None, "", {hostile: parse_filter("1")})
    with pytest.raises(ValueError, match="declares none"):
        sql.cells([1], [hostile])


def test_a_large_table_reads_the_rows_again_once_its_table_changes(
    model: PlacesModel, sql: SqliteSource
) -> None:
    table = SourceTableView(source=sql, sort_column="depth", sort_descending=True)
    assert table.rows(0, 1) == [(1, ["Lake", "12.5", "2024-01-31", "lake"])]

    model.places.add(Place(7, "Deep", 40.0, None, Kind.LAKE))

    assert table.row_count == len(PLACES) + 1
    assert table.rows(0, 1) == [(7, ["Deep", "40.0", "", "lake"])]


def test_the_rows_stay_in_sqlite_python_reading_only_the_ids_and_the_window(
    model: PlacesModel,
) -> None:
    reads: list[str] = []

    class Counted(SqliteSource):
        def cells(self, ids: Sequence[Any], columns: Sequence[str]) -> dict[Any, list[Any]]:
            reads.append(f"{len(ids)} rows")
            return super().cells(ids, columns)

    with model.places.connection() as db:
        db.executemany(
            "INSERT INTO place(name, depth, kind) VALUES (?, ?, 'lake')",
            ((f"p{i}", i / 10) for i in range(20_000)),
        )
    source = Counted(
        model.places,
        "SELECT * FROM place",
        id_column="id",
        columns=[SourceColumn("name", "Name"), SourceColumn("depth", "Depth", float)],
    )
    table = SourceTableView(source=source, sort_column="depth")
    table.rows(10_000, 10_010)
    assert table.row_count == 20_000 + len(PLACES)
    assert reads == ["200 rows"]


def test_a_table_s_cells_are_read_while_another_thread_orders_its_rows(
    model: PlacesModel, sql: SqliteSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, gate = threading.Event(), threading.Event()

    def slow_regexp(pattern: str, value: Any) -> bool:  # held up, as a slow query is
        started.set()
        gate.wait(10)
        return re.search(pattern, value, re.IGNORECASE) is not None

    monkeypatch.setattr(sqlitemodel, "_regexp", slow_regexp)
    ordered: list[Sequence[Hashable]] = []
    read: list[dict[Any, list[Any]]] = []
    filters = {"name": parse_filter("/^lake$/", str)}
    ordering = threading.Thread(target=lambda: ordered.append(sql.ordered_ids(None, "", filters)))
    ordering.start()
    assert started.wait(5)

    try:
        # as a job's order would: the table draws its rows meanwhile, the order still held
        reading = threading.Thread(target=lambda: read.append(sql.cells([4], ["name"])))
        reading.start()
        reading.join(5)
        assert read == [{4: ["O'Brien bay"]}]
        model.new()  # New, while the order reads the old study's rows
    finally:
        gate.set()
    ordering.join(5)

    assert ordered == [[1, 5]]


def test_a_table_s_rows_are_read_while_a_write_is_uncommitted(
    model: PlacesModel, sql: SqliteSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sqlitemodel, "WAIT_SECONDS", 1.0)  # a reader locked out fails soon
    read: list[tuple[int, dict[Any, list[Any]], Sequence[Hashable]]] = []

    def read_rows() -> None:
        deepest = sql.ordered_ids(Sort("depth", descending=True), "", {})[:2]
        read.append((sql.count(), sql.cells([4], ["name"]), deepest))

    # as a job writing many rows in one transaction: it holds the model's connection
    with model.places.connection() as db:
        db.execute("PRAGMA cache_size = 10")  # the write spills to the disk
        db.executemany(
            "INSERT INTO place(name, depth, kind) VALUES (?, 99, 'lake')",
            ((f"sea {i}" * 20,) for i in range(5_000)),
        )
        reading = threading.Thread(target=read_rows)
        reading.start()
        reading.join(5)

    assert read == [(len(PLACES), {4: ["O'Brien bay"]}, [1, 5])]  # the rows committed
    assert sql.count() == len(PLACES) + 5_000


def test_reads_reuse_a_connection_and_see_each_write_committed(
    model: PlacesModel, sql: SqliteSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    connect = sqlite3.connect

    def counted(database: str, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        opened.append(database)
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counted)
    table = SourceTableView(source=sql)
    for start in range(len(PLACES)):  # as many reads as a table's windows
        table.rows(start, start + 1)
        table.source = None
        table.source = sql
    assert len(opened) <= 1

    model.places.add(Place(7, "Deep", 40.0, None, Kind.LAKE))  # committed: seen at once
    assert sql.count() == len(PLACES) + 1
    assert sql.cells([7], ["name"]) == {7: ["Deep"]}


def _plans(model: PlacesModel, order: Callable[[], object]) -> list[str]:
    """Get SQLite's plan of each query `order` runs, on the model's read connection."""
    queries: list[str] = []
    with model.places.reading() as db:  # the pool gives it back to the next read
        db.set_trace_callback(queries.append)
    order()
    with model.places.reading() as db:
        db.set_trace_callback(None)
        selects = [query for query in queries if query.startswith("SELECT")]
        return [
            " ".join(row[-1] for row in db.execute(f"EXPLAIN QUERY PLAN {query}").fetchall())
            for query in selects
        ]


def test_a_sort_reads_its_column_s_index_unless_something_filters_the_rows(
    model: PlacesModel, sql: SqliteSource
) -> None:
    # the rows with a depth in its index's order, then the empty ones
    plans = _plans(model, lambda: sql.ordered_ids(Sort("depth", descending=True), "", {}))
    assert "place_depth" in plans[0]
    assert "TEMP B-TREE FOR ORDER BY" not in plans[0]
    # filtered: reading the table in the index's order would cost more than sorting
    plans = _plans(
        model, lambda: sql.ordered_ids(Sort("depth"), "", {"kind": parse_filter("=lake")})
    )
    assert "place_depth" not in plans[0]


def test_a_filter_by_a_decimal_keeps_the_rows_a_list_source_keeps(
    sql: SqliteSource, listed: ListSource[Place]
) -> None:
    # e.g. a column of a record whose field is a `Decimal`, compared as SQLite's numbers
    found, expected = _both(sql, listed, filters={"depth": parse_filter(">3", Decimal)})

    assert found == expected
