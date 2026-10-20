"""A sweep of a pipe's radius, a worker thread writing its runs to a SQLite model.

`python -m examples.pipesweep --backend qt` (or `textual`, or `web`). Run sweeps the
outer radius of a pipe under pressure: a job, in a thread of its own, works out the wall's
hoop stress at each radius, one radius at a time, and writes each run to the model's
database as it is done. The views never hear from the worker: each write's `changed` is
emitted on the main thread (see `Job.call_on_main_thread`), where the table, the chart
and the progress bar show the runs written so far. Cancel stops the sweep after the run
it's working on; File saves and opens the runs with the views.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import attrs
from attrs import Factory

from composeui.core.application import run
from composeui.core.sqlitemodel import SqliteModel, SqliteTable, as_parameters, table
from composeui.core.view import (
    Align,
    ButtonVariant,
    ButtonView,
    ChartView,
    GroupFormView,
    HorizontalView,
    LabelRowFloatInputView,
    LabelRowIntInputView,
    MainView,
    ProgressBarView,
    Series,
    TableView,
    child,
    define_view,
)

if TYPE_CHECKING:
    from composeui.core.jobs import Job

#: how long the worker takes over a run, in seconds, as a solver would
SOLVE_SECONDS = 0.3


@attrs.frozen
class SweepRun:
    """The stress a run found in the pipe's wall at one outer radius."""

    #: the outer radius (mm)
    radius: float
    #: the hoop stress (MPa)
    stress: float


class SweepRuns(SqliteTable):
    create = """
        CREATE TABLE sweep_run(
            id INTEGER PRIMARY KEY,
            radius REAL NOT NULL,
            stress REAL NOT NULL
        );
    """

    def add(self, sweep_run: SweepRun) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO sweep_run(radius, stress) VALUES (:radius, :stress)",
                as_parameters(sweep_run),
            )

    def clear(self) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM sweep_run")

    def all(self) -> list[SweepRun]:
        return self.fetch(SweepRun, "SELECT radius, stress FROM sweep_run ORDER BY radius")


class PipeSweepModel(SqliteModel):
    runs = table(SweepRuns)


def hoop_stress(pressure: float, radius: float, thickness: float) -> float:
    """Get the hoop stress (MPa) in a thin wall, under `pressure` (MPa), sizes in mm."""
    return pressure * (radius - thickness) / thickness


def sweep(
    job: Job[int],
    model: PipeSweepModel,
    pressure: float,
    thickness: float,
    radii: list[float],
) -> int:
    """Run the sweep in the job's thread, writing each run as it's done; get their count."""
    for count, radius in enumerate(radii):
        if not job.sleep(SOLVE_SECONDS):
            return count
        found = SweepRun(radius, round(hoop_stress(pressure, radius, thickness), 2))
        with model.runs.connection():
            # checked within the transaction: New and Open drop the job before they replace
            # the database, so a run canceled meanwhile never lands in the next study
            if job.is_canceled:
                return count
            model.runs.add(found)
    return len(radii)


@define_view
class PositiveInputView(LabelRowFloatInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.minimum = 0


@define_view
class SweepForm(GroupFormView):
    pressure: PositiveInputView = child(PositiveInputView, label="Pressure (MPa)", value=2)
    thickness: PositiveInputView = child(PositiveInputView, label="Wall Thickness (mm)", value=5)
    min_radius: PositiveInputView = child(
        PositiveInputView, label="Minimum Outer Radius (mm)", value=20
    )
    max_radius: PositiveInputView = child(
        PositiveInputView, label="Maximum Outer Radius (mm)", value=100
    )
    steps: LabelRowIntInputView = child(
        LabelRowIntInputView, label="Radii", value=17, minimum=2, maximum=100
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Sweep"
        sizes = (self.pressure, self.thickness, self.min_radius, self.max_radius)
        self.add_validator(
            self._check_positive, *(row.editing_finished for row in sizes), rows=sizes
        )
        radii = (self.thickness, self.min_radius, self.max_radius, self.steps)
        self.add_validator(self._check_radii, *(row.editing_finished for row in radii), rows=radii)

    def _check_positive(self) -> Optional[str]:
        values = (
            self.pressure.value,
            self.thickness.value,
            self.min_radius.value,
            self.max_radius.value,
        )
        if any(value is None or value <= 0 for value in values):
            return "Every value must be greater than 0"
        return None

    def _check_radii(self) -> Optional[str]:
        thickness, minimum = self.thickness.value, self.min_radius.value
        maximum, steps = self.max_radius.value, self.steps.value
        if steps is None or steps < 2:  # noqa: PLR2004 (a sweep's two ends)
            return "A sweep takes at least 2 radii"
        if minimum is not None and maximum is not None and minimum >= maximum:
            return "The minimum radius must be smaller than the maximum radius"
        if thickness is not None and minimum is not None and minimum <= thickness:
            return "The wall must be thinner than the minimum radius"
        return None

    def radii(self) -> list[float]:
        """Get the radii swept, evenly spaced from the minimum to the maximum."""
        minimum, maximum = self.min_radius.value or 0, self.max_radius.value or 0
        steps = self.steps.value or 2
        return [round(minimum + (maximum - minimum) * i / (steps - 1), 2) for i in range(steps)]


@define_view
class SweepButtons(HorizontalView):
    align = Align.END
    run: ButtonView = child(ButtonView, text="Run")
    cancel: ButtonView = child(
        ButtonView, text="Cancel", variant=ButtonVariant.DANGER, is_enabled=False
    )


@define_view
class PipeSweepMainView(MainView):
    app_title = "Pipe Sweep"
    extension = ".sweep"

    form: SweepForm = Factory(SweepForm)
    buttons: SweepButtons = Factory(SweepButtons)
    #: the runs written, out of the radii swept
    progress: ProgressBarView = child(ProgressBarView, maximum=17)
    chart: ChartView = child(
        ChartView,
        title="Hoop Stress",
        x_title="Outer Radius",
        x_unit="mm",
        y_title="Stress",
        y_unit="MPa",
        height=280,
    )
    runs: TableView = child(TableView, headers=["Outer Radius (mm)", "Hoop Stress (MPa)"])

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # the callbacks get the model through their `model` parameter
        self.buttons.run.clicked.connect(self.start)
        self.buttons.cancel.clicked.connect(self.jobs.cancel)
        self.jobs.running_changed.connect(self._show_running)

    def start(self, model: PipeSweepModel) -> None:
        """Start a sweep, replacing the runs of the last one."""
        if self.jobs.is_running:
            return
        self.form.validate()
        if self.form.log_view.log_message != "":
            self.status_bar.show_message("Fix the sweep first")
            return
        radii = self.form.radii()
        model.runs.clear()
        self.progress.maximum = len(radii)
        job = self.jobs.start(
            sweep, model, self.form.pressure.value or 0, self.form.thickness.value or 0, radii
        )
        job.finished.connect(self._report)

    def show_runs(self, model: PipeSweepModel) -> None:
        """Show the runs written so far, on the main thread, as each is written."""
        runs = model.runs.all()
        self.runs.rows = [[f"{found.radius:g}", f"{found.stress:g}"] for found in runs]
        self.chart.series = [
            Series(
                name="Hoop Stress",
                x=[found.radius for found in runs],
                y=[found.stress for found in runs],
            )
        ]
        self.progress.value = len(runs)

    def _report(self, count: int) -> None:
        total = self.progress.maximum
        self.status_bar.show_message(f"Swept {count} of {total} radii")

    def _show_running(self, is_running: bool) -> None:
        self.form.is_enabled = not is_running
        self.buttons.run.is_enabled = not is_running
        self.buttons.cancel.is_enabled = is_running

    def connect_model(self, model: PipeSweepModel) -> None:
        """Keep the views showing the database's runs, whichever thread writes them."""
        model.runs.changed.connect(self.show_runs, now=True)


def main() -> None:
    run(
        PipeSweepMainView,
        build_model=PipeSweepModel,
        setup_model=PipeSweepMainView.connect_model,
    )


if __name__ == "__main__":
    main()
