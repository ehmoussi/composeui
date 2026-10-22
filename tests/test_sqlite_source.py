"""A large table's rows from SQLite (`SqliteSource`): as a `ListSource` gives the same rows."""

from __future__ import annotations

import datetime
import enum
import re
import threading
from typing import TYPE_CHECKING, Any, Optional

import attrs
import pytest

from composeui.core import sqlitemodel
from composeui.core.sqlitemodel import SqliteModel, SqliteSource, SqliteTable, as_parameters
from composeui.core.view import DataTableView, ListSource, Sort, SourceColumn, parse_filter

if TYPE_CHECKING:
    from collections.abc import Hashable, Iterator, Sequence

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
]
HEADERS = {"name": "Name", "depth": "Depth", "surveyed": "Surveyed", "kind": "Kind"}


class Places(SqliteTable):
    create = (
        "CREATE TABLE place(id INTEGER PRIMARY KEY, name TEXT NOT NULL, depth REAL,"
        " surveyed TEXT, kind TEXT NOT NULL);"
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
        ("depth", ">7.25"),
        ("depth", ">=7.25"),
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
    assert sorted(found) == sorted(expected), text  # type: ignore[type-var]


@pytest.mark.parametrize("column", ["name", "depth", "surveyed", "kind"])
@pytest.mark.parametrize("descending", [False, True])
def test_a_sort_orders_as_a_list_source_empty_cells_last(
    sql: SqliteSource, listed: ListSource[Place], column: str, *, descending: bool
) -> None:
    found, expected = _both(sql, listed, sort=Sort(column, descending=descending))
    assert found == expected


def test_a_search_finds_its_text_as_typed_in_the_text_columns(
    sql: SqliteSource, listed: ListSource[Place]
) -> None:
    # a quote, and LIKE's wildcards, are text
    for needle in ("o'b", "100%", "_", " HARBOUR "):
        found, expected = _both(sql, listed, search=needle)
        assert sorted(found) == sorted(expected), needle  # type: ignore[type-var]
    assert sql.ordered_ids(None, "12.5", {}) == []  # no text column holds it


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
    table = DataTableView(source=sql, sort_column="depth", sort_descending=True)
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
    table = DataTableView(source=source, sort_column="depth")
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
