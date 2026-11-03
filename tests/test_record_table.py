"""A table of typed records: shown, edited, saved and loaded through its records."""

from __future__ import annotations

import datetime
import decimal
import enum
import json
from typing import TYPE_CHECKING, Optional, TypeVar

import attrs
import pytest
from hypothesis import given
from hypothesis import strategies as st

from composeui.core.application import Application
from composeui.core.model import RefusedError
from composeui.core.view import (
    CellWidget,
    Column,
    InvalidStateError,
    MainView,
    RecordTableView,
    T,
    child,
    define_view,
)
from tests.tables import COLUMNS, Room, RoomsMainView

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def main_view() -> RoomsMainView:
    return Application(build_main_view=RoomsMainView).main_view


def test_records_show_as_cells_under_their_columns(
    main_view: RoomsMainView, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = main_view.rooms
    assert table.headers == ["Room", "Temperature", "Occupants", "Heated"]
    assert table.editable_columns == [0, 1, 2, 3]
    assert table.rows == [["Hall", "18", "", "False"], ["Kitchen", "20.5", "2", "True"]]
    table.selected_rows = [1]
    assert table.selected_record == Room("Kitchen", 20.5, 2, is_heated=True)
    assert table.selected_records == [table.selected_record]

    # the headers follow the language, new columns' too
    (tmp_path / "fr.json").write_text(json.dumps({"Room": "Pièce"}), encoding="utf-8")
    monkeypatch.setattr(RoomsMainView, "translations_dir", tmp_path)
    main_view.set_language("fr")
    assert table.headers[:2] == ["Pièce", "Temperature"]
    table.columns = [Column("name", T("Room"))]
    assert table.headers == ["Pièce"]
    assert table.rows == [["Hall"], ["Kitchen"]]
    assert table.editable_columns == []


def test_a_field_s_column_index_styles_its_cells(main_view: RoomsMainView) -> None:
    table = main_view.rooms
    assert table.column_index("occupants") == table.headers.index("Occupants")
    with pytest.raises(ValueError, match="has no column showing 'area'"):
        table.column_index("area")


@pytest.mark.parametrize(
    ("column", "text", "edited", "cells"),
    [
        (1, "21", Room("Kitchen", 21.0, 2, is_heated=True), ["Kitchen", "21.0", "2", "True"]),
        (2, "", Room("Kitchen", 20.5, None, is_heated=True), ["Kitchen", "20.5", "", "True"]),
        (3, "false", Room("Kitchen", 20.5, 2), ["Kitchen", "20.5", "2", "False"]),
    ],
)
def test_an_edit_emits_the_records_then_shows_the_new_one_still_selected(
    main_view: RoomsMainView, column: int, text: str, edited: Room, cells: list[str]
) -> None:
    table = main_view.rooms
    table.selected_rows = [1]
    emitted: list[tuple[Room, Room, list[Room]]] = []
    table.record_edited.connect(lambda old, new: emitted.append((old, new, table.records)))
    hall, kitchen = table.records

    table.emit_cell_edited(1, column, text)

    # emitted while the table still holds the old record
    assert emitted == [(kitchen, edited, [hall, kitchen])]
    assert table.records == [hall, edited]
    assert table.rows[1] == cells
    assert table.selected_record == edited


def test_records_the_app_assigns_answer_an_edit_keeping_its_record_selected(
    main_view: RoomsMainView,
) -> None:
    table = main_view.rooms
    table.selected_rows = [0]

    def sort_by_name(_old: Room, new: Room) -> None:
        table.records = sorted([new, table.records[1]], key=lambda room: room.name)

    table.record_edited.connect(sort_by_name)
    table.emit_cell_edited(0, 0, "Pantry")

    assert [room.name for room in table.records] == ["Kitchen", "Pantry"]
    assert table.selected_record == Room("Pantry", 18)


@pytest.mark.parametrize(("column", "text"), [(1, "warm"), (2, "2.5"), (3, "yes")])
def test_a_cell_that_doesn_t_parse_refuses_the_edit_and_says_why(
    main_view: RoomsMainView, column: int, text: str
) -> None:
    table = main_view.rooms
    records, rows = table.records, table.rows
    emitted: list[Room] = []
    table.record_edited.connect(lambda _old, new: emitted.append(new))

    table.emit_cell_edited(1, column, text)

    assert (table.records, table.rows, emitted) == (records, rows, [])
    header = table.headers[column]
    assert main_view.status_bar.message == f'{header}: "{text}" isn\'t a valid value'
    # in the app's language too
    main_view.set_language("fr")
    assert main_view.status_bar.message == f"{header} : « {text} » n'est pas une valeur valide"


def test_a_refusal_in_record_edited_refuses_the_edit(main_view: RoomsMainView) -> None:
    table = main_view.rooms
    records = table.records

    def refuse(_old: Room, _new: Room) -> None:
        reason = "too cold"
        with table.refusing("Can't edit the room: {error}"):
            raise RefusedError(reason)

    table.record_edited.connect(refuse)
    table.emit_cell_edited(0, 1, "5")

    assert table.records == records
    assert main_view.status_bar.message == "Can't edit the room: too cold"


class Role(enum.Enum):
    INPUT = "Input"
    OUTPUT = "Output"


@attrs.define
class Variable:
    name: str
    role: Role
    is_kept: bool = False


def test_a_column_s_widgets_edit_its_records_and_check_every_shown_row() -> None:
    table = RecordTableView[Variable](
        columns=[
            Column(
                "is_kept", T("Keep"), editable=True, widget=CellWidget.check_box(check_all=True)
            ),
            Column("name", T("Variable"), filterable=True),
            Column("role", T("Role"), editable=True, widget=CellWidget.combobox()),
        ]
    )
    table.records = [
        Variable("Length", Role.INPUT),
        Variable("Stress", Role.OUTPUT, is_kept=True),
        Variable("Width", Role.INPUT),
    ]
    # a combobox without options offers the enum's
    assert table.cell_widgets[2].options == ("Input", "Output")
    assert table.column_checked(0) is None
    table.emit_cell_edited(0, 2, "Output")
    assert table.records[0].role is Role.OUTPUT

    # checking every shown row edits each record, the selection staying on its row
    edited: list[Variable] = []
    table.record_edited.connect(lambda _old, new: edited.append(new))
    table.filters = {1: "!Width"}
    table.selected_rows = [0]
    table.check_all(0, is_checked=True)
    assert edited == [Variable("Length", Role.OUTPUT, is_kept=True)]
    assert [variable.is_kept for variable in table.records] == [True, True, False]
    assert (table.column_checked(0), table.is_checked(2, 0)) == (True, False)
    assert table.selected_rows == [0]


def test_a_study_saves_and_loads_the_records_by_their_type(tmp_path: Path) -> None:
    main_view = RoomsMainView()
    main_view.rooms.records = [Room("Attic", 12.5, 1)]
    main_view.rooms.selected_rows = [0]
    main_view.others.records = [Room("Cellar", 9)]
    path = tmp_path / "study.rooms"
    main_view.save_state(path)
    # the records alone: the rows show them
    saved = json.loads(path.read_text())["views"]["rooms"]
    assert saved["records"] == [
        {"name": "Attic", "temperature": 12.5, "occupants": 1, "is_heated": False}
    ]
    assert "rows" not in saved

    loaded = RoomsMainView()
    loaded.load_state(path)
    assert loaded.rooms.records == [Room("Attic", 12.5, 1)]
    assert loaded.rooms.rows == [["Attic", "12.5", "1", "False"]]
    assert loaded.rooms.selected_rows == [0]
    assert loaded.others.records == [Room("Cellar", 9.0)]

    loaded.reset_state()
    assert loaded.rooms.records == RoomsMainView().rooms.records
    assert loaded.others.records == []


class _Level(enum.Enum):
    LOW = 1
    HIGH = 2


class _Size(enum.IntEnum):
    SMALL = 1
    LARGE = 2


class _Shade(str, enum.Enum):
    LIGHT = "light"
    DARK = "dark"


@attrs.frozen
class _Sample:
    """A record with a field of each type a cell parses."""

    name: str
    count: int
    ratio: float
    is_kept: bool
    price: decimal.Decimal
    day: datetime.date
    taken: datetime.datetime
    level: _Level
    size: _Size
    shade: _Shade
    spare: Optional[int]


@define_view
class _SamplesMainView(MainView):
    app_title = "Samples"
    extension = ".samples"

    samples: RecordTableView[_Sample] = child(
        RecordTableView[_Sample],
        columns=[Column(name, name, editable=True) for name in attrs.fields_dict(_Sample)],
    )


_SAMPLE = _Sample(
    name="Pump",
    count=2,
    ratio=0.5,
    is_kept=True,
    price=decimal.Decimal("9.50"),
    day=datetime.date(2026, 11, 3),
    taken=datetime.datetime(2026, 11, 3, 8, tzinfo=datetime.timezone.utc),
    level=_Level.HIGH,
    size=_Size.LARGE,
    shade=_Shade.DARK,
    spare=None,
)


_SAMPLES = st.builds(
    _Sample,
    st.text(),
    st.integers(),
    st.floats(allow_nan=False),
    st.booleans(),
    st.decimals(allow_nan=False, allow_infinity=False),
    st.dates(),
    st.datetimes(timezones=st.none() | st.just(datetime.timezone.utc)),
    st.sampled_from(_Level),
    st.sampled_from(_Size),
    st.sampled_from(_Shade),
    st.none() | st.integers(),
)


def test_a_cell_edited_to_the_text_another_shows_takes_its_value() -> None:
    main_view = Application(build_main_view=_SamplesMainView).main_view
    table = main_view.samples

    @given(_SAMPLES, _SAMPLES)
    def edit(record: _Sample, other: _Sample) -> None:
        table.records = [record, other]
        main_view.status_bar.clear_message()
        for column, name in enumerate(attrs.fields_dict(_Sample)):
            table.emit_cell_edited(0, column, table.rows[1][column])
            # the other's value, of the field's type: an enum's member, not its value
            edited, expected = getattr(table.records[0], name), getattr(other, name)
            assert (edited, type(edited)) == (expected, type(expected)), name
            assert main_view.status_bar.message == "", name

    edit()


# a decimal that isn't a number; an enum's name, which no cell shows: its value does
@pytest.mark.parametrize(("field", "text"), [("price", "cheap"), ("level", "HIGH")])
def test_a_decimal_or_an_enum_cell_that_doesn_t_parse_refuses_the_edit(
    field: str, text: str
) -> None:
    main_view = Application(build_main_view=_SamplesMainView).main_view
    table = main_view.samples
    column = list(attrs.fields_dict(_Sample)).index(field)
    table.records = [_SAMPLE]

    table.emit_cell_edited(0, column, text)

    assert table.records == [_SAMPLE]
    assert main_view.status_bar.message == f'{field}: "{text}" isn\'t a valid value'


def test_a_study_saves_decimals_as_they_are_and_enums_of_numbers(tmp_path: Path) -> None:
    main_view = _SamplesMainView()
    main_view.samples.records = [_SAMPLE]
    path = tmp_path / "study.samples"
    main_view.save_state(path)
    saved = json.loads(path.read_text())["views"]["samples"]["records"][0]
    assert (saved["price"], saved["level"], saved["size"]) == ("9.50", 2, 2)  # exact

    opened = _SamplesMainView()
    opened.load_state(path)
    assert opened.samples.records == [_SAMPLE]


def test_a_study_with_records_that_don_t_fit_is_refused() -> None:
    main_view = RoomsMainView()
    data = main_view.state_data()
    data["rooms"]["records"] = [{"name": "Attic", "temperature": "warm"}]
    with pytest.raises(InvalidStateError):
        main_view.load_state_data(data)
    assert main_view.rooms.records == RoomsMainView().rooms.records


def test_a_table_not_knowing_its_records_type_says_how_to_build_it() -> None:
    with pytest.raises(TypeError, match=r"RecordTableView\[Room\]"):
        _ = RecordTableView(columns=COLUMNS).record_type


def test_a_cell_that_doesn_t_parse_outside_an_app_is_refused_saying_nothing() -> None:
    view = RoomsMainView()  # not shown by an application: no status bar to tell
    table = view.rooms
    records = table.records

    table.emit_cell_edited(1, 1, "warm")

    assert table.records == records
    assert view.status_bar.message == ""


_T = TypeVar("_T", bound=attrs.AttrsInstance)


@define_view
class _AnyRecordsTable(RecordTableView[_T]):
    """A table generic in its records: still not knowing their type."""


def test_a_generic_table_not_told_its_records_type_says_how_to_build_it() -> None:
    with pytest.raises(TypeError, match=r"RecordTableView\[Room\]"):
        _ = _AnyRecordsTable(columns=COLUMNS).record_type
