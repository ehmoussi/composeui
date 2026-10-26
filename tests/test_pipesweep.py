"""Tests of the example pipesweep: a worker thread writing its runs to a SQLite model."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

import pytest

from composeui.core.application import ModelApplication
from composeui.core.registry import RendererType
from examples import pipesweep
from examples.pipesweep import PipeSweepMainView, PipeSweepModel, SweepRun

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.qtcore.qtrenderer import QtWidgetRenderer

App = ModelApplication[PipeSweepMainView, PipeSweepModel]


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Iterator[App]:
    monkeypatch.setattr(pipesweep, "SOLVE_SECONDS", 0)
    app = App(
        build_main_view=PipeSweepMainView,
        build_model=PipeSweepModel,
        setup_model=PipeSweepMainView.connect_model,
    )
    app.main_view.status_bar.timeout = 0
    form = app.main_view.form
    form.pressure.value, form.thickness.value = 2.0, 5.0
    form.min_radius.value, form.max_radius.value, form.steps.value = 20.0, 40.0, 3
    yield app
    app.model.close()


def test_a_sweep_s_runs_are_shown_on_the_main_thread_as_the_worker_writes_them(
    app: App,
) -> None:
    main_view = app.main_view
    threads: list[threading.Thread] = []
    app.model.runs.changed.connect(lambda: threads.append(threading.current_thread()))

    main_view.buttons.run.clicked.emit()
    assert not main_view.buttons.run.is_enabled
    assert main_view.buttons.cancel.is_enabled
    main_view.jobs.wait()

    assert app.model.runs.all() == [SweepRun(20, 6), SweepRun(30, 10), SweepRun(40, 14)]
    assert main_view.runs.rows == [["20", "6"], ["30", "10"], ["40", "14"]]
    assert [(series.x, series.y) for series in main_view.chart.series] == [
        ([20, 30, 40], [6, 10, 14])
    ]
    assert (main_view.progress.value, main_view.progress.maximum) == (3, 3)
    # each run written told on the main thread, never the worker's
    assert threads == [threading.current_thread()] * 3
    assert main_view.status_bar.message == "Swept 3 of 3 radii"
    assert main_view.buttons.run.is_enabled
    assert not main_view.buttons.cancel.is_enabled


def test_a_sweep_runs_again_from_none(app: App) -> None:
    app.main_view.buttons.run.clicked.emit()
    app.main_view.jobs.wait()
    app.main_view.form.steps.value = 2

    app.main_view.buttons.run.clicked.emit()
    app.main_view.jobs.wait()

    assert app.main_view.runs.rows == [["20", "6"], ["40", "14"]]


def test_a_canceled_sweep_keeps_the_runs_written(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipesweep, "SOLVE_SECONDS", 60)

    app.main_view.buttons.run.clicked.emit()
    app.main_view.buttons.cancel.clicked.emit()
    app.main_view.jobs.wait(timeout=5)

    assert app.main_view.runs.rows == []
    assert app.main_view.status_bar.message == "Swept 0 of 3 radii"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("min_radius", 50.0, "The minimum radius must be smaller than the maximum radius"),
        ("pressure", 0.0, "Every value must be greater than 0"),
        ("steps", 1, "A sweep takes at least 2 radii"),
        ("thickness", 25.0, "The wall must be thinner than the minimum radius"),
    ],
)
def test_a_sweep_that_does_not_fit_starts_nothing(
    app: App, field: str, value: float, reason: str
) -> None:
    getattr(app.main_view.form, field).value = value

    app.main_view.buttons.run.clicked.emit()

    assert not app.main_view.jobs.is_running
    assert app.main_view.status_bar.message == "Fix the sweep first"
    assert reason in app.main_view.form.log_view.log_message


def test_a_sweep_running_isn_t_started_again(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipesweep, "SOLVE_SECONDS", 60)
    app.main_view.buttons.run.clicked.emit()
    jobs = app.main_view.jobs

    app.main_view.start(app.model)  # e.g. Ctrl+Enter, the button disabled

    assert jobs.is_running
    jobs.cancel()
    jobs.wait(timeout=5)


def test_a_sweep_canceled_while_solving_writes_none_of_its_run(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    solving, resumed = threading.Event(), threading.Event()
    solve = pipesweep.hoop_stress

    def slow_solve(pressure: float, radius: float, thickness: float) -> float:
        solving.set()
        resumed.wait(5)
        return solve(pressure, radius, thickness)

    monkeypatch.setattr(pipesweep, "hoop_stress", slow_solve)
    app.main_view.buttons.run.clicked.emit()
    assert solving.wait(5)

    app.main_view.jobs.cancel()  # after the wait, before the run lands in the database
    resumed.set()
    app.main_view.jobs.wait(timeout=5)

    assert app.model.runs.all() == []


def test_a_saved_sweep_opens_with_its_runs(app: App, tmp_path: Path) -> None:
    app.main_view.buttons.run.clicked.emit()
    app.main_view.jobs.wait()
    path = tmp_path / "study.sweep"
    app.main_view.file_view.filepath = path
    app.main_view.file_menu.save.triggered.emit()
    app.main_view.file_menu.new.triggered.emit()
    assert app.main_view.runs.rows == []

    app.main_view.file_menu.open_file.triggered.emit()

    assert app.main_view.runs.rows == [["20", "6"], ["30", "10"], ["40", "14"]]
    assert (app.main_view.progress.value, app.main_view.progress.maximum) == (3, 3)


def test_a_sweep_shows_its_runs_in_the_qt_widgets(app: App, qtbot: QtBot) -> None:
    pytest.importorskip("qtpy")
    renderer_type: type[QtWidgetRenderer] = pytest.importorskip(
        "composeui.qtcore.qtrenderer"
    ).QtWidgetRenderer
    main_view = app.main_view
    main_view.render(RendererType.QT)
    threads: list[threading.Thread] = []
    app.model.runs.changed.connect(lambda: threads.append(threading.current_thread()))

    main_view.buttons.run.clicked.emit()
    qtbot.waitUntil(lambda: not main_view.jobs.is_running)

    assert main_view.runs.rows == [["20", "6"], ["30", "10"], ["40", "14"]]
    renderer = main_view.progress.renderer
    assert isinstance(renderer, renderer_type)
    progress_bar = cast("QtWidgetRenderer", renderer).qt_object
    assert progress_bar is not None
    assert progress_bar.value() == 3
    assert set(threads) == {threading.main_thread()}


def test_a_sweep_shows_in_french(app: App) -> None:
    main_view = app.main_view
    main_view.set_language("fr")

    main_view.buttons.run.clicked.emit()
    main_view.jobs.wait()

    assert main_view.title == "Balayage de conduite"
    assert [tab.title for tab in main_view.results.tabs] == ["Graphique", "Calculs"]
    assert main_view.runs.headers == ["Rayon extérieur (mm)", "Contrainte circonférentielle (MPa)"]
    assert main_view.buttons.cancel.text == "Annuler"
    assert [series.name for series in main_view.chart.series] == ["Contrainte circonférentielle"]
    assert main_view.status_bar.message == "3 rayons balayés sur 3"
