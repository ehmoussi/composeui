"""Sorting and filtering a table's rows, in core: the rows shown, whatever the backend."""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

import pytest

from composeui.core.application import Application
from composeui.core.view import (
    FilterError,
    FilterProblem,
    SelectionMode,
    TableView,
    parse_filter,
)
from tests.tables import Room, SortedRoomsMainView

if TYPE_CHECKING:
    from pathlib import Path

#: the rooms' columns, by their fields
NAME, TEMPERATURE, OCCUPANTS, HEATED = range(4)


@pytest.fixture
def main_view() -> SortedRoomsMainView:
    return Application(build_main_view=SortedRoomsMainView).main_view


def _names(main_view: SortedRoomsMainView) -> list[str]:
    return [main_view.rooms.records[row].name for row in main_view.rooms.shown_rows]


def test_a_header_s_clicks_sort_ascending_descending_then_as_the_app_gave() -> None:
    table = SortedRoomsMainView().rooms

    table.sort_by(OCCUPANTS)
    # as numbers, 9 before 10, and the empty cell last
    assert [table.rows[row][OCCUPANTS] for row in table.shown_rows] == ["2", "9", "10", ""]
    table.sort_by(OCCUPANTS)
    assert [table.rows[row][OCCUPANTS] for row in table.shown_rows] == ["10", "9", "2", ""]
    table.sort_by(OCCUPANTS)
    assert (table.sort_column, table.shown_rows) == (None, [0, 1, 2, 3])

    # text ignoring case; another column starts ascending
    table.sort_by(OCCUPANTS)
    table.sort_by(NAME)
    assert (table.sort_column, table.sort_descending) == (NAME, False)
    assert [table.rows[row][NAME] for row in table.shown_rows] == [
        "Attic",
        "Bedroom",
        "Hall",
        "kitchen",
    ]


def test_a_table_of_text_sorts_stably_by_text() -> None:
    table = TableView(headers=["Count", "Place"], sortable_columns=[0])
    table.rows = [["10", "Lake"], ["9", "Harbour"], ["10", "Pond"], ["", "Field"]]

    table.sort_column = 0
    # text: "10" before "9"; equal cells in the app's order; the empty cell last
    assert table.shown_rows == [0, 2, 1, 3]
    table.sort_descending = True
    assert table.shown_rows == [1, 0, 2, 3]


@pytest.mark.parametrize(
    ("text", "field_type", "value", "matches"),
    [
        (">20", float, 20.5, True),
        (">20", float, 20.0, False),
        (">=20", float, 20.0, True),
        ("<20", int, 20, False),
        ("<= 20", int, 20, True),
        ("!=20", Optional[int], 21, True),
        ("!=20", Optional[int], None, False),
        ("18..24", float, 24.0, True),
        ("18..24", float, 17.9, False),
        ("20", Decimal, Decimal("20.0"), True),
        ("=", Optional[int], None, True),
        ("=", Optional[int], 0, False),
        ("true", bool, True, True),
        ("FALSE", bool, True, False),
        (">=2024-01-31", datetime.date, datetime.date(2024, 2, 1), True),
        (
            "2024-01-31 08:00+00:00",
            datetime.datetime,
            datetime.datetime(2024, 1, 31, 8, tzinfo=datetime.timezone.utc),
            True,
        ),
    ],
)
def test_a_filter_compares_a_number_a_date_or_a_boolean_by_value(
    text: str, field_type: Any, value: Any, *, matches: bool
) -> None:
    cell = "" if value is None else str(value)
    assert parse_filter(text, field_type).matches(value, cell) is matches


def test_a_text_filter_keeps_the_cells_containing_it_ignoring_case() -> None:
    contains = parse_filter("CHEN", str)
    assert contains.matches("Kitchen", "Kitchen")
    assert not contains.matches("Hall", "Hall")
    # ">" is text in a text column
    assert parse_filter(">2", str).matches("a>2", "a>2")
    assert parse_filter("=", str).matches("", "")


@pytest.mark.parametrize(
    ("text", "field_type", "problem"),
    [
        ("  ", str, FilterProblem.EMPTY),
        (">warm", float, FilterProblem.NOT_A_NUMBER),
        ("18..", float, FilterProblem.NOT_A_NUMBER),
        ("24..18", float, FilterProblem.REVERSED_RANGE),
        ("2024-13-01", datetime.date, FilterProblem.NOT_A_DATE),
        ("yes", bool, FilterProblem.NOT_A_BOOLEAN),
    ],
)
def test_a_filter_that_doesn_t_parse_says_why(
    text: str, field_type: Any, problem: FilterProblem
) -> None:
    with pytest.raises(FilterError) as error:
        parse_filter(text, field_type)
    assert error.value.problem is problem


def test_the_search_and_the_filters_combine(main_view: SortedRoomsMainView) -> None:
    table = main_view.rooms

    table.search = "ROOM"
    assert _names(main_view) == ["Bedroom"]
    table.search = ""
    table.filters = {TEMPERATURE: ">=20", HEATED: "true"}
    assert _names(main_view) == ["kitchen", "Bedroom"]
    table.filters = {TEMPERATURE: "18..20.5"}
    assert _names(main_view) == ["Hall", "kitchen"]
    table.filters = {OCCUPANTS: "="}
    assert _names(main_view) == ["Hall"]


def test_a_filter_the_table_can_t_take_is_refused_saying_why(
    main_view: SortedRoomsMainView,
) -> None:
    table = main_view.rooms
    with pytest.raises(FilterError):
        table.filters = {TEMPERATURE: ">warm"}
    assert table.filter_error(TEMPERATURE, ">warm") == '"warm" isn\'t a number'
    assert table.filter_error(TEMPERATURE, ">20") is None

    # translated, as the rest of the bar
    main_view.set_language("fr")
    assert table.filter_error(TEMPERATURE, ">warm") == "« warm » n'est pas un nombre"
    assert table.filter_texts["add_filter"] == "+ Filtre"

    with pytest.raises(ValueError, match="filterable"):
        main_view.notes.filters = {0: "Calm"}
    with pytest.raises(ValueError, match="sortable"):
        main_view.notes.sort_column = 0


def test_hiding_a_selected_row_deselects_it_the_indexes_staying_those_of_the_rows(
    main_view: SortedRoomsMainView,
) -> None:
    table = main_view.rooms
    table.selection_mode = SelectionMode.MULTIPLE
    emitted: list[list[int]] = []
    table.selection_changed.connect(emitted.append)
    table.sort_by(NAME)
    table.selected_rows = [0, 1]  # the hall and the kitchen, wherever they show

    table.filters = {HEATED: "true"}
    assert table.selected_records == [Room("kitchen", 20.5, 10, is_heated=True)]
    assert emitted == [[1]]
    # a sort hides nothing
    table.sort_by(NAME)
    assert emitted == [[1]]


def test_new_records_keep_the_sort_and_the_filters(main_view: SortedRoomsMainView) -> None:
    table = main_view.rooms
    table.sort_by(TEMPERATURE)
    table.filters = {TEMPERATURE: "<21"}
    table.selected_rows = [1]  # the kitchen

    # the hall colder, first now; the attic too warm, hidden; the kitchen still selected
    table.records = [
        Room("Hall", 5),
        Room("kitchen", 20.5, 10, is_heated=True),
        Room("Attic", 22, 2),
        Room("Bedroom", 21, 9, is_heated=True),
    ]
    assert _names(main_view) == ["Hall", "kitchen"]
    assert table.selected_rows == [1]


def test_a_study_reopens_sorted_and_filtered_dropping_what_its_columns_no_longer_take(
    main_view: SortedRoomsMainView, tmp_path: Path
) -> None:
    table = main_view.rooms
    table.sort_by(OCCUPANTS)
    table.sort_by(OCCUPANTS)
    table.search = "e"
    table.filters = {TEMPERATURE: ">18"}
    path = tmp_path / "rooms.sorted"
    main_view.save_state(path)

    other = Application(build_main_view=SortedRoomsMainView).main_view
    other.load_state(path)
    assert (other.rooms.sort_column, other.rooms.sort_descending) == (OCCUPANTS, True)
    assert (other.rooms.search, other.rooms.filters) == ("e", {TEMPERATURE: ">18"})
    assert _names(other) == ["kitchen", "Bedroom"]

    # a filter its column no longer parses, and a column gone, are dropped, not refused
    data = json.loads(path.read_text())
    data["rooms"]["filters"] = {str(TEMPERATURE): ">warm", "9": "x", str(NAME): "en"}
    data["rooms"]["sort_column"] = 9
    other.load_state_data(data)
    assert (other.rooms.sort_column, other.rooms.filters) == (None, {NAME: "en"})
