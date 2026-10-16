"""Tables whose cells the user edits, shared by the backend tests of editable cells."""

from typing import Optional

import attrs
from attrs import Factory

from composeui.core.view import (
    Column,
    MainView,
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
