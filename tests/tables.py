"""Tables shared by the backend tests: cells the user edits, and a large table's rows."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

import attrs
from attrs import Factory

from composeui.core.signal import SignalNoArgs
from composeui.core.view import (
    DATA_TABLE_JOB_ROWS,
    CellStyle,
    CellWidget,
    Column,
    DataTableView,
    HeaderGroup,
    ListSource,
    MainView,
    NodeMark,
    RecordTableView,
    SourceColumn,
    T,
    TableView,
    child,
    define_view,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from composeui.core.view import Filter, Sort


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


class MillionSource:
    """A million rows (`size`), as a database would give them: an integer id each.

    It records the ids whose cells a table reads (`read`).
    """

    columns = (SourceColumn("value", "Value", int), SourceColumn("half", "Half", float))

    def __init__(self) -> None:
        self.changed = SignalNoArgs()
        self.size = 1_000_000
        self.read: list[int] = []

    def ordered_ids(
        self, _sort: Optional[Sort], _search: str, _filters: Mapping[str, Filter]
    ) -> range:
        return range(self.size)

    def count(self) -> int:
        return self.size

    def cells(self, ids: Sequence[int], _columns: Sequence[str]) -> dict[int, list[float]]:
        self.read.extend(ids)
        return {row_id: [row_id * 2, row_id / 2] for row_id in ids if row_id < self.size}


@define_view
class MillionRowsMainView(MainView):
    app_title = "Million"
    extension = ".million"

    table: DataTableView = child(DataTableView, column_formats={"half": ".1f"})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.table.source = MillionSource()


@define_view
class RoomsDataMainView(MainView):
    """Rooms in a large table whose bar searches them and filters two of their columns."""

    app_title = "Rooms"
    extension = ".rooms"

    rooms: DataTableView = child(DataTableView, filterable_columns=["name", "temperature"])

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.rooms.source = ListSource(
            Room,
            {"name": T("Room"), "temperature": T("Temperature"), "occupants": T("Occupants")},
            [Room("Kitchen", 21.5, 2), Room("Hall", 18.0), Room("Bedroom", 19.5, 1)],
        )


class GatedSource:
    """`size` rows, valued by their ids, whose order waits for `gate` to be set.

    So a test sees a table while a job orders its rows. It records the sort of each order
    asked (`orders`). Descending reverses the rows; any other order keeps them.
    """

    columns = (SourceColumn("value", "Value", int),)

    def __init__(self) -> None:
        self.changed = SignalNoArgs()
        self.size = DATA_TABLE_JOB_ROWS
        self.gate = threading.Event()
        self.gate.set()
        self.orders: list[Optional[Sort]] = []

    def ordered_ids(
        self, sort: Optional[Sort], _search: str, _filters: Mapping[str, Filter]
    ) -> range:
        self.orders.append(sort)
        self.gate.wait(10)
        if sort is not None and sort.descending:
            return range(self.size - 1, -1, -1)
        return range(self.size)

    def count(self) -> int:
        return self.size

    def cells(self, ids: Sequence[int], _columns: Sequence[str]) -> dict[int, list[int]]:
        return {row_id: [row_id] for row_id in ids if row_id < self.size}


@define_view
class GatedMainView(MainView):
    app_title = "Gated"
    extension = ".gated"

    table: DataTableView = child(DataTableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.table.source = GatedSource()
