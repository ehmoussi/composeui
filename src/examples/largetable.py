"""A large table: `python -m examples.largetable --backend qt` (or `textual`, or `web`).

A million sensor readings (``--rows`` sets how many) in a SQLite model, shown by a
`DataTableView` through a `SqliteSource`: SQLite sorts and filters them, and the table
reads only the rows it shows, as the user scrolls. Python holds the shown rows' ids, never
the readings. A click on a header sorts them, and the table's bar searches and filters
them; the label says how many rows pass and how long SQLite took. A click selects rows
(Shift+click a range, on Qt and Textual), and a double click or Enter shows a reading.
Ctrl+C copies the selected rows; Export CSV writes the rows shown to a file.
"""

from __future__ import annotations

import enum
import random
import time
from typing import TYPE_CHECKING, Any, Optional

import attrs

from composeui.core import application
from composeui.core.registry import RendererType
from composeui.core.signal import Signal
from composeui.core.sqlitemodel import SqliteModel, SqliteSource, SqliteTable, table
from composeui.core.view import (
    OMIT,
    DataTableView,
    LabelView,
    MainView,
    SelectionMode,
    SourceColumn,
    child,
    define_view,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterator, Mapping

    from composeui.core.jobs import Job
    from composeui.core.view import Filter, Sort

SITES = ("Lyon", "Grenoble", "Nantes", "Lille", "Toulouse")
#: the readings made up and written at once
BATCH = 100_000


class Status(enum.Enum):
    OK = "ok"
    WARNING = "warning"
    FAULT = "fault"


COLUMNS = (
    SourceColumn("sensor", "Sensor"),
    SourceColumn("site", "Site"),
    SourceColumn("temperature", "Temperature (°C)", float),
    SourceColumn("pressure", "Pressure (kPa)", Optional[float]),
    SourceColumn("status", "Status", Status),
)


def made_up(count: int) -> Iterator[tuple[str, str, float, Optional[float], str]]:
    """Make up `count` readings, the same each time, one at a time."""
    rng = random.Random(count)  # noqa: S311 (made-up data)
    gauss, choice, uniform = rng.gauss, rng.choice, rng.random
    sensors = [f"S-{number:04d}" for number in range(10_000)]
    # as often as their weights: 90 %, 8 % and 2 %
    statuses = [Status.OK.value] * 90 + [Status.WARNING.value] * 8 + [Status.FAULT.value] * 2
    for _ in range(count):
        yield (
            choice(sensors),
            choice(SITES),
            round(gauss(21, 4), 2),
            None if uniform() < 0.1 else round(gauss(101.3, 1.5), 2),  # noqa: PLR2004
            choice(statuses),
        )


#: an index per column that sorts: else SQLite reads every row to sort them
INDEXES = """
    CREATE INDEX reading_sensor ON reading(sensor COLLATE NOCASE);
    CREATE INDEX reading_temperature ON reading(temperature);
    CREATE INDEX reading_pressure ON reading(pressure);
"""


class Readings(SqliteTable):
    create = (
        """
        CREATE TABLE reading(
            id INTEGER PRIMARY KEY,
            sensor TEXT NOT NULL,
            site TEXT NOT NULL,
            temperature REAL NOT NULL,
            pressure REAL,
            status TEXT NOT NULL
        );
        """
        + INDEXES
    )

    def fill(self, count: int) -> int:
        """Write `count` made-up readings, a batch at a time: never all of them in memory.

        The indexes are built once the rows are in, faster than row by row.
        """
        readings, total = made_up(count), count
        with self.connection() as db:
            for name in ("reading_sensor", "reading_temperature", "reading_pressure"):
                db.execute(f"DROP INDEX {name}")
            for _ in range(0, total, BATCH):
                batch = [next(readings) for _ in range(min(BATCH, count))]
                db.executemany(
                    "INSERT INTO reading(sensor, site, temperature, pressure, status)"
                    " VALUES (?, ?, ?, ?, ?)",
                    batch,
                )
                count -= len(batch)
            for statement in INDEXES.strip().split(";"):
                if statement.strip() != "":
                    db.execute(statement)
        return total


def fill(_job: Job[int], readings: Readings, count: int) -> int:
    """Write the readings in a job's thread: the window shows meanwhile."""
    return readings.fill(count)


class ReadingsModel(SqliteModel):
    readings = table(Readings)


class TimedSource(SqliteSource):
    """The readings, saying how many pass and how long SQLite took to order (`ordered`)."""

    def __init__(self, readings: Readings) -> None:
        super().__init__(readings, "SELECT * FROM reading", id_column="id", columns=COLUMNS)
        self.readings = readings
        #: the rows passing and the seconds the order took, each time the table asks it
        self.ordered: Signal[int, float] = Signal[int, float]()

    def ordered_ids(
        self, sort: Optional[Sort], search: str, filters: Mapping[str, Filter]
    ) -> list[Any]:
        start = time.perf_counter()
        ids = super().ordered_ids(sort, search, filters)
        self.ordered.emit(len(ids), time.perf_counter() - start)
        return ids


@define_view
class LargeTableMainView(MainView):
    app_title = "Large Table"
    extension = ".largetable"

    info: LabelView = child(LabelView)
    table: DataTableView = child(
        DataTableView,
        column_formats={"temperature": ".2f", "pressure": ".2f"},
        selection_mode=SelectionMode.MULTIPLE,
        filterable_columns=[column.name for column in COLUMNS],
    )
    picked: LabelView = child(LabelView, text="No reading selected")
    #: the readings, in the model
    _source: Optional[TimedSource] = attrs.field(default=None, init=False, metadata={OMIT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.table.selection_changed.connect(self._show_selected)
        self.table.row_activated.connect(self._show_activated)

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--rows", type=int, default=1_000_000, help="the readings to generate")

    def connect_model(self, model: ReadingsModel) -> None:
        """Show the model's readings, read again whenever they change."""
        self._source = TimedSource(model.readings)
        self._source.ordered.connect(self._show_count)
        self.table.source = self._source

    def apply_arguments(self, args: argparse.Namespace) -> None:
        # a study opened with -f has its readings already
        if self._source is not None and self._source.count() == 0:
            self.info.text = f"Writing {args.rows:,} readings..."
            self.jobs.start(fill, self._source.readings, args.rows)

    def _show_selected(self, ids: list[Any]) -> None:
        self.picked.text = f"{len(ids):,} readings selected" if ids else "No reading selected"

    def _show_activated(self, row_id: Any) -> None:
        if self._source is not None:
            names = [column.name for column in COLUMNS]
            sensor, site, temperature, *_ = self._source.cells([row_id], names)[row_id]
            self.picked.text = f"{sensor} in {site}: {temperature} °C"

    def _show_count(self, count: int, seconds: float) -> None:
        total = 0 if self._source is None else self._source.count()
        self.info.text = f"{count:,} of {total:,} rows, ordered in {seconds * 1000:,.0f} ms"


def main() -> None:
    application.run(
        LargeTableMainView,
        build_model=ReadingsModel,
        setup_model=LargeTableMainView.connect_model,
        default_backend=RendererType.QT,
    )


if __name__ == "__main__":
    main()
