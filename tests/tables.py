"""Tables whose cells the user edits, shared by the backend tests of editable cells."""

from __future__ import annotations

from typing import Optional

import attrs
from attrs import Factory

from composeui.core.view import (
    CellStyle,
    CellWidget,
    Column,
    HeaderGroup,
    MainView,
    NodeMark,
    RecordTableView,
    T,
    TableView,
    child,
    define_view,
)


@define_view
class EditableTableMainView(MainView):
    app_title = "Places"
    extension = ".places"

    places: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.places.headers = ["Place", "Note"]
        # the harbour has no note yet: its row is short of the cell
        self.places.rows = [["Lake", "Calm"], ["Harbour"]]
        self.places.editable_columns = [1]


@attrs.define
class Room:
    name: str
    temperature: float
    occupants: Optional[int] = None
    is_heated: bool = False


COLUMNS = [
    Column("name", T("Room"), editable=True),
    Column("temperature", T("Temperature"), editable=True),
    Column("occupants", T("Occupants"), editable=True),
    Column("is_heated", T("Heated"), editable=True),
]


@define_view
class RoomsTableView(RecordTableView[Room]):
    """Its records' type from its base, rather than from ``RecordTableView[Room]``."""


@define_view
class RoomsMainView(MainView):
    app_title = "Rooms"
    extension = ".rooms"

    rooms: RecordTableView[Room] = child(RecordTableView[Room], columns=COLUMNS)
    others: RoomsTableView = child(RoomsTableView, columns=COLUMNS[:2])

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.status_bar.timeout = 0
        self.rooms.records = [Room("Hall", 18), Room("Kitchen", 20.5, 2, is_heated=True)]


#: every column sortable and filterable
SORTED_COLUMNS = [
    Column(column.field, column.header, editable=True, sortable=True, filterable=True)
    for column in COLUMNS
]


@define_view
class SortedRoomsMainView(MainView):
    """A table the user sorts and filters by every column; a table of text that doesn't."""

    app_title = "Sorted rooms"
    extension = ".sorted"

    rooms: RecordTableView[Room] = child(RecordTableView[Room], columns=SORTED_COLUMNS)
    notes: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.status_bar.timeout = 0
        # numbers that sort otherwise as text (9 < 10), an empty cell, names in mixed case
        self.rooms.records = [
            Room("Hall", 18),
            Room("kitchen", 20.5, 10, is_heated=True),
            Room("Attic", 9, 2),
            Room("Bedroom", 21, 9, is_heated=True),
        ]
        self.notes.headers = ["Note"]
        self.notes.rows = [["Calm"], ["Busy"]]


@define_view
class CellWidgetsMainView(MainView):
    """A table of variables: kept or not, their role picked, a button and a link each."""

    app_title = "Variables"
    extension = ".variables"

    variables: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.variables.headers = ["Keep", "Variable", "Role", "Distribution", "Help"]
        self.variables.rows = [
            ["True", "Length", "Input", "Normal", "doc"],
            ["false", "Stress", "Output", "", "doc"],
        ]
        self.variables.editable_columns = [0, 2]
        self.variables.cell_widgets = {
            0: CellWidget.check_box(check_all=True),
            2: CellWidget.combobox(["Input", "Output"]),
            3: CellWidget.button(),
            4: CellWidget.link(),
        }


@define_view
class StyledTablesMainView(MainView):
    """A result's points, colored, marked and grouped, and a key/value table of its numbers."""

    app_title = "Results"
    extension = ".results"

    points: TableView = Factory(TableView)
    numbers: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.points.headers = ["Group", "Point", "Standard space", "Physical space", "Kept"]
        self.points.header_groups = [HeaderGroup("Coordinates", 2, 2)]
        self.points.rows = [
            ["A", "P1", "0.5", "12.0", "True"],
            ["", "P2", "nan", "nan", "False"],
            ["B", "P3", "1.5", "40.0", "True"],
        ]
        self.points.editable_columns = [1, 4]
        self.points.cell_widgets = {4: CellWidget.check_box(check_all=True)}
        self.points.cell_styles = {
            # group A over its two points
            (0, 0): CellStyle(row_span=2),
            (1, 2): CellStyle(background="#dc2626"),
            (1, 3): CellStyle(background="#dc2626"),
            (2, 3): CellStyle(background="#fde68a", mark=NodeMark.WARNING),
            (1, 1): CellStyle(is_disabled=True),
            (1, 4): CellStyle(is_disabled=True),
        }
        self.numbers.headers = ["Value"]
        self.numbers.row_headers = ["Number of calls", "Time (s)"]
        self.numbers.rows = [["2500"], ["3.2"]]
