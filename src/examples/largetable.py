"""A large table: `python -m examples.largetable --backend qt` (or `textual`, or `web`).

A million sensor readings (``--rows`` sets how many), in a `ListSource`, shown by a
`DataTableView`: the table reads the rows it shows from the source, as the user scrolls.
A click on a header sorts them, and the table's bar
searches and filters them; the label says how many rows pass and how long the source
took. A click selects rows (Shift+click a range, on Qt and Textual), and a double click or
Enter shows a reading.

It follows the "Large tables" plan of ``ROADMAP.md``: the source is in memory, and sorts
and filters the readings in Python.
"""

from __future__ import annotations

import enum
import functools
import random
import time
from typing import TYPE_CHECKING, Any, Optional

import attrs

from composeui.core import application
from composeui.core.registry import RendererType
from composeui.core.signal import Signal
from composeui.core.view import (
    OMIT,
    DataTableView,
    Filter,
    LabelView,
    ListSource,
    MainView,
    SelectionMode,
    Sort,
    child,
    define_view,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Hashable, Mapping, Sequence

SITES = ("Lyon", "Grenoble", "Nantes", "Lille", "Toulouse")


class Status(enum.Enum):
    OK = "ok"
    WARNING = "warning"
    FAULT = "fault"


@attrs.frozen
class Reading:
    sensor: str
    site: str
    #: °C
    temperature: float
    #: kPa; None when the sensor has no pressure gauge
    pressure: Optional[float]
    status: Status


HEADERS = {
    "sensor": "Sensor",
    "site": "Site",
    "temperature": "Temperature (°C)",
    "pressure": "Pressure (kPa)",
    "status": "Status",
}


@functools.lru_cache(maxsize=1)
def readings(count: int) -> tuple[Reading, ...]:
    """Make up `count` readings, the same each time: once, shared by the web's sessions."""
    rng = random.Random(count)  # noqa: S311 (made-up data)
    gauss, choice, uniform = rng.gauss, rng.choice, rng.random
    sensors = [f"S-{number:04d}" for number in range(10_000)]
    # as often as their weights: 90 %, 8 % and 2 %
    statuses = [Status.OK] * 90 + [Status.WARNING] * 8 + [Status.FAULT] * 2
    return tuple(
        Reading(
            choice(sensors),
            choice(SITES),
            round(gauss(21, 4), 2),
            None if uniform() < 0.1 else round(gauss(101.3, 1.5), 2),  # noqa: PLR2004
            choice(statuses),
        )
        for _ in range(count)
    )


class TimedSource(ListSource[Reading]):
    """The readings, saying how many pass and how long they took to order (`ordered`)."""

    def __init__(self, made: Sequence[Reading]) -> None:
        super().__init__(Reading, HEADERS, made)
        #: the rows passing and the seconds the order took, each time the table asks it
        self.ordered: Signal[int, float] = Signal[int, float]()

    def ordered_ids(
        self, sort: Optional[Sort], search: str, filters: Mapping[str, Filter]
    ) -> list[Hashable]:
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
        filterable_columns=list(HEADERS),
    )
    picked: LabelView = child(LabelView, text="No reading selected")
    #: the readings generated
    _total: int = attrs.field(default=0, init=False, metadata={OMIT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.table.selection_changed.connect(self._show_selected)
        self.table.row_activated.connect(self._show_activated)

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--rows", type=int, default=1_000_000, help="the readings to generate")

    def apply_arguments(self, args: argparse.Namespace) -> None:
        self._total = args.rows
        source = TimedSource(readings(args.rows))
        source.ordered.connect(self._show_count)
        # not saved with a study: the readings come from the command line
        self.table.source = source

    def _show_selected(self, ids: list[Any]) -> None:
        self.picked.text = f"{len(ids):,} readings selected" if ids else "No reading selected"

    def _show_activated(self, row_id: Any) -> None:
        source = self.table.source
        if isinstance(source, TimedSource):
            reading = source.records[row_id]  # a row's id is its index in the readings
            self.picked.text = f"{reading.sensor} in {reading.site}: {reading.temperature} °C"

    def _show_count(self, count: int, seconds: float) -> None:
        self.info.text = f"{count:,} of {self._total:,} rows, ordered in {seconds * 1000:,.0f} ms"


def main() -> None:
    application.run(LargeTableMainView, default_backend=RendererType.QT)


if __name__ == "__main__":
    main()
