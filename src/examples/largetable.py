"""A large table: `python -m examples.largetable --backend qt` (or `textual`, or `web`).

A million sensor readings (``--rows`` sets how many), in a `ListSource`, shown by a
`DataTableView`: the table reads the rows it shows from the source, as the user scrolls
(on the web, turns its pages). The form sorts, searches and filters them; the label says
how many rows pass and how long the source took.

It follows the "Large tables" plan of ``ROADMAP.md``: the table itself doesn't sort,
filter or select its rows yet.
"""

from __future__ import annotations

import enum
import functools
import random
import time
from typing import TYPE_CHECKING, Optional

import attrs

from composeui.core import application
from composeui.core.registry import RendererType
from composeui.core.view import (
    OMIT,
    DataTableView,
    FilterError,
    GroupFormView,
    LabelRowCheckBoxView,
    LabelRowComboboxView,
    LabelRowInputView,
    LabelView,
    ListSource,
    LogType,
    MainView,
    child,
    define_view,
)

if TYPE_CHECKING:
    import argparse

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


@define_view
class SortRowView(LabelRowComboboxView[str]):
    pass


@define_view
class SourceForm(GroupFormView):
    sort: SortRowView = child(
        SortRowView,
        label="Sort by",
        values={"Source order": "", **{header: name for name, header in HEADERS.items()}},
        value="",
    )
    descending: LabelRowCheckBoxView = child(LabelRowCheckBoxView, label="Descending")
    search: LabelRowInputView = child(
        LabelRowInputView, label="Search", placeholder="A sensor, a site, a status"
    )
    temperature: LabelRowInputView = child(
        LabelRowInputView, label="Temperature", placeholder=">25, 18..24, !=21"
    )


@define_view
class LargeTableMainView(MainView):
    app_title = "Large Table"
    extension = ".largetable"

    form: SourceForm = child(SourceForm, title="Source")
    info: LabelView = child(LabelView)
    table: DataTableView = child(
        DataTableView, column_formats={"temperature": ".2f", "pressure": ".2f"}
    )
    #: the readings generated
    _total: int = attrs.field(default=0, init=False, metadata={OMIT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        form = self.form
        form.sort.value_changed.connect(self.order)
        form.descending.toggled.connect(self.order)
        form.search.editing_finished.connect(self.order)
        form.temperature.editing_finished.connect(self.order)

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--rows", type=int, default=1_000_000, help="the readings to generate")

    def apply_arguments(self, args: argparse.Namespace) -> None:
        made = readings(args.rows)
        self._total = args.rows
        start = time.perf_counter()
        # not saved with a study: the readings come from the command line
        self.table.source = ListSource(Reading, HEADERS, made)
        self._show_count(time.perf_counter() - start)

    def order(self) -> None:
        """Give the table the form's sort, search and filter: it asks the source again."""
        form, table = self.form, self.table
        form.temperature.log_message = ""
        text = form.temperature.text.strip()
        start = time.perf_counter()
        try:
            table.filters = {"temperature": text} if text != "" else {}
        except FilterError as error:
            form.temperature.log_type = LogType.ERROR
            form.temperature.log_message = (
                f"Not a filter: {error.problem.name.lower().replace('_', ' ')}"
            )
            return
        table.sort_column = form.sort.value or None
        table.sort_descending = form.descending.is_checked
        table.search = form.search.text
        self._show_count(time.perf_counter() - start)

    def _show_count(self, seconds: float) -> None:
        self.info.text = (
            f"{self.table.row_count:,} of {self._total:,} rows, ordered in {seconds * 1000:,.0f} ms"
        )


def main() -> None:
    application.run(LargeTableMainView, default_backend=RendererType.QT)


if __name__ == "__main__":
    main()
