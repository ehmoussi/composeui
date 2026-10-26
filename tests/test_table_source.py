"""A large table's source of rows, in core: `ListSource`, on records in memory."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any, Optional, cast

import attrs
import pytest

from composeui.core.view import ListSource, Sort, parse_filter
from tests.tables import Room

if TYPE_CHECKING:
    from collections.abc import Hashable, Sequence

    from composeui.core.view import TableSource


class Exposure(enum.Enum):
    NORTH = "north"
    SOUTH = "south"


@attrs.frozen
class Facade:
    name: str
    exposure: Exposure
    area: Optional[float] = None


ROOMS = [
    Room("kitchen", 21.5, 2),
    Room("Hall", 18.0, 10),
    Room("Attic", 15.0),
    Room("Bedroom", 19.0, 9),
    Room("Office", 21.5, 2),
]


@pytest.fixture
def source() -> ListSource[Room]:
    return ListSource(
        Room,
        {"name": "Room", "temperature": "Temperature", "occupants": "Occupants"},
        ROOMS,
    )


def _names(source: ListSource[Room], ids: Sequence[Hashable]) -> list[str]:
    """Get the rooms' names, by their ids: their indexes in `records`."""
    return [source.records[cast("int", row_id)].name for row_id in ids]


def test_a_list_source_keeps_its_order_or_sorts_by_value_empty_cells_last(
    source: ListSource[Room],
) -> None:
    assert source.ordered_ids(None, "", {}) == [0, 1, 2, 3, 4]
    # as numbers, 9 before 10; equal cells in the records' order; the empty cell last
    occupants = source.ordered_ids(Sort("occupants"), "", {})
    assert _names(source, occupants) == ["kitchen", "Office", "Bedroom", "Hall", "Attic"]
    occupants = source.ordered_ids(Sort("occupants", descending=True), "", {})
    assert _names(source, occupants) == ["Hall", "Bedroom", "kitchen", "Office", "Attic"]
    names = source.ordered_ids(Sort("name"), "", {})
    assert _names(source, names) == ["Attic", "Bedroom", "Hall", "kitchen", "Office"]


def test_a_search_keeps_the_rows_whose_text_cells_contain_it_ignoring_case(
    source: ListSource[Room],
) -> None:
    assert _names(source, source.ordered_ids(None, " ICE ", {})) == ["Office"]
    # only text columns: no room is named with a 2, though two hold 2 occupants
    assert source.ordered_ids(None, "2", {}) == []
    assert len(source.ordered_ids(None, "  ", {})) == len(ROOMS)


def test_filters_keep_the_rows_each_column_s_filter_passes(source: ListSource[Room]) -> None:
    filters = {
        "temperature": parse_filter(">=19", float),
        "name": parse_filter("!=office"),
    }
    assert _names(source, source.ordered_ids(Sort("temperature"), "", filters)) == [
        "Bedroom",
        "kitchen",
    ]
    empty = {"occupants": parse_filter("=", Optional[int])}
    assert _names(source, source.ordered_ids(None, "", empty)) == ["Attic"]


def test_an_enum_sorts_searches_and_filters_by_its_text_and_reads_as_itself() -> None:
    facades = ListSource(
        Facade,
        {"name": "Facade", "exposure": "Exposure"},
        [Facade("Front", Exposure.SOUTH), Facade("Back", Exposure.NORTH)],
    )

    assert facades.ordered_ids(Sort("exposure"), "", {}) == [1, 0]
    assert facades.ordered_ids(None, "sou", {}) == [0]
    assert facades.ordered_ids(None, "", {"exposure": parse_filter("=north")}) == [1]
    assert facades.cells([0], ["exposure"]) == {0: [Exposure.SOUTH]}


def test_cells_give_the_values_of_the_rows_asked_in_the_columns_asked(
    source: ListSource[Room],
) -> None:
    assert source.cells([2, 0], ["occupants", "name"]) == {2: [None, "Attic"], 0: [2, "kitchen"]}
    # an id gone since the table read the order
    assert source.cells([4, 5], ["name"]) == {4: ["Office"]}


def test_an_id_field_keeps_the_ids_of_the_records_across_new_records() -> None:
    source = ListSource(Room, {"temperature": "Temperature"}, ROOMS, id_field="name")
    changes: list[None] = []
    source.changed.connect(lambda: changes.append(None))

    source.records = [ROOMS[3], ROOMS[1]]
    assert changes == [None]
    assert source.ordered_ids(Sort("temperature"), "", {}) == ["Hall", "Bedroom"]
    assert source.cells(["Bedroom", "kitchen"], ["temperature"]) == {"Bedroom": [19.0]}
    with pytest.raises(ValueError, match="two have the same name"):
        source.records = [ROOMS[0], ROOMS[0]]


def test_an_order_reads_the_records_it_started_with_new_ones_assigned_meanwhile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"name": "Room", "temperature": "Temperature"}
    source = ListSource(Room, headers, ROOMS, id_field="name")
    text = source._text  # noqa: SLF001 (replace records after the order reads its snapshot)

    def replacing_text(record: Any, name: str) -> str:
        if source.records == tuple(ROOMS):
            source.records = [Room("Garage", 5.0)]
        return text(record, name)

    monkeypatch.setattr(source, "_text", replacing_text)

    ordered = source.ordered_ids(Sort("temperature"), "o", {})  # replaced as it searches

    assert [room.name for room in source.records] == ["Garage"]
    assert ordered == ["Bedroom", "Office"]  # the old rooms holding "o", sorted


def test_a_column_the_source_does_not_have_is_refused(source: ListSource[Room]) -> None:
    with pytest.raises(ValueError, match="'is_heated'"):
        source.ordered_ids(Sort("is_heated"), "", {})
    with pytest.raises(ValueError, match="'area'"):
        source.ordered_ids(None, "", {"area": parse_filter(">1", float)})
    with pytest.raises(ValueError, match="'area'"):
        source.cells([0], ["area"])
    with pytest.raises(ValueError, match="no field 'area'"):
        ListSource(Room, {"area": "Area"})


def test_a_list_source_is_a_table_source(source: ListSource[Room]) -> None:
    # checked by mypy: a source the large table takes
    table_source: TableSource[Hashable] = source
    assert [column.type for column in table_source.columns] == [str, float, Optional[int]]
