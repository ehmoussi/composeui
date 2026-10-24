"""Tests of the example taskview: tasks run in worker threads, shown by the Qt widgets."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("qtpy")
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QMainWindow, QProgressBar, QPushButton

from composeui.core.application import Application
from composeui.core.registry import RendererType
from composeui.core.renderer import RendererContainer
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qchart import QChart
from composeui.qtcore.widgets.qvalueslider import QValueSlider
from examples.taskview import TASK_COUNT, TaskMainView, TaskStatus

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from composeui.core.view import View


def _widget(view: View) -> object:
    assert isinstance(view.renderer, QtWidgetRenderer)
    return view.renderer.qt_object


@pytest.fixture
def main_view(qtbot: QtBot) -> TaskMainView:
    main_view = Application(build_main_view=TaskMainView).main_view
    main_view.status_bar.timeout = 0
    main_view.render(RendererType.QT)
    window = _widget(main_view)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    return main_view


def _configure(main_view: TaskMainView, duration: int, failure_percentage: int) -> None:
    config = main_view.config
    config.min_duration.value = config.max_duration.value = duration
    config.failure_percentage.value = failure_percentage


def _statuses(main_view: TaskMainView) -> set[str]:
    return {status for _, _, status, _ in main_view.details.tasks.rows}


@pytest.mark.parametrize(
    ("failure_percentage", "status"), [(0, TaskStatus.SUCCEEDED), (100, TaskStatus.FAILED)]
)
def test_a_run_shows_every_task_s_outcome_then_can_run_again(
    qtbot: QtBot, main_view: TaskMainView, failure_percentage: int, status: TaskStatus
) -> None:
    _configure(main_view, 0, failure_percentage)
    run, bar = _widget(main_view.buttons.run), _widget(main_view.progress)
    assert isinstance(run, QPushButton)
    assert isinstance(bar, QProgressBar)

    run.click()
    qtbot.waitUntil(run.isEnabled)

    assert len(main_view.details.tasks.rows) == TASK_COUNT
    assert _statuses(main_view) == {status.value}
    errors = {error != "" for _, _, _, error in main_view.details.tasks.rows}
    assert errors == {status is TaskStatus.FAILED}
    assert bar.value() == bar.maximum() == TASK_COUNT
    chart = _widget(main_view.running)
    assert isinstance(chart, QChart)
    (curve,) = chart.getPlotItem().listDataItems()
    seconds, running = curve.getData()
    # every task running from the start, held until one ends; none at the end
    assert (running[0], running[-1]) == (TASK_COUNT, 0)
    assert list(seconds) == sorted(seconds)
    assert running[1] == running[0]  # a step: held, not sloping to the next count
    assert main_view.config.is_enabled
    assert not main_view.buttons.cancel.is_enabled


def test_the_metrics_count_a_run_s_tasks_and_compare_them_with_the_last_run(
    qtbot: QtBot, main_view: TaskMainView
) -> None:
    metrics = main_view.metrics
    run = _widget(main_view.buttons.run)
    assert isinstance(run, QPushButton)

    _configure(main_view, 0, 0)
    run.click()
    qtbot.waitUntil(run.isEnabled)
    assert (metrics.succeeded.value, metrics.failed.value) == (str(TASK_COUNT), "0")
    assert metrics.succeeded.delta is None  # no run before to compare with

    _configure(main_view, 60, 100)  # longer than the test: running until canceled
    run.click()
    qtbot.waitUntil(lambda: metrics.running.value == str(TASK_COUNT))
    assert metrics.succeeded.delta is None  # counts still moving
    main_view.jobs.cancel()
    qtbot.waitUntil(run.isEnabled)

    assert (metrics.running.value, metrics.canceled.value) == ("0", str(TASK_COUNT))
    assert (metrics.succeeded.delta, metrics.failed.delta) == (-TASK_COUNT, 0)
    assert metrics.canceled.delta == TASK_COUNT


def test_cancel_stops_the_tasks_still_running(qtbot: QtBot, main_view: TaskMainView) -> None:
    _configure(main_view, 60, 0)  # longer than the test: only canceling ends them
    run, cancel = _widget(main_view.buttons.run), _widget(main_view.buttons.cancel)
    assert isinstance(run, QPushButton)
    assert isinstance(cancel, QPushButton)

    run.click()
    qtbot.waitUntil(lambda: _statuses(main_view) == {TaskStatus.RUNNING.value})
    assert not run.isEnabled()
    assert not main_view.config.is_enabled
    cancel.click()
    qtbot.waitUntil(run.isEnabled)

    assert _statuses(main_view) == {TaskStatus.CANCELED.value}
    assert not cancel.isEnabled()


def test_a_task_s_retry_button_runs_it_again_and_its_error_link_opens_a_dialog(
    qtbot: QtBot, main_view: TaskMainView
) -> None:
    tasks = main_view.details.tasks
    _configure(main_view, 0, 100)
    main_view.buttons.run.clicked.emit()
    qtbot.waitUntil(lambda: main_view.buttons.run.is_enabled)

    tasks.cell_clicked.emit(1, 3)
    assert main_view.error_dialog.is_visible
    assert main_view.error_dialog.text == (
        "Task 2 worked 0.0 s, then failed: Random error: task 2 failed"
    )
    main_view.error_dialog.accept()

    main_view.config.failure_percentage.value = 0
    tasks.cell_clicked.emit(1, 0)
    qtbot.waitUntil(lambda: tasks.rows[1][2] == TaskStatus.SUCCEEDED.value)
    assert tasks.rows[1][3] == ""
    assert tasks.rows[0][2] == TaskStatus.FAILED.value
    assert main_view.metrics.succeeded.value == "1"
    # a succeeded task has no error to show
    tasks.cell_clicked.emit(1, 3)
    assert not main_view.error_dialog.is_visible


def test_a_task_still_running_isn_t_run_again(qtbot: QtBot, main_view: TaskMainView) -> None:
    _configure(main_view, 60, 0)  # longer than the test: only canceling ends them
    main_view.buttons.run.clicked.emit()

    main_view.details.tasks.cell_clicked.emit(0, 0)
    main_view.start()  # e.g. Ctrl+Enter, the button disabled: no second run

    assert main_view.status_bar.message == "Task 1 is still running"
    assert main_view.metrics.running.value == str(TASK_COUNT)
    main_view.jobs.cancel()
    qtbot.waitUntil(lambda: main_view.buttons.run.is_enabled)


def test_a_run_waits_for_a_valid_configuration(main_view: TaskMainView) -> None:
    main_view.config.min_duration.value = 5
    main_view.config.max_duration.value = 2

    main_view.buttons.run.clicked.emit()

    assert main_view.details.tasks.rows == []
    assert main_view.buttons.run.is_enabled
    assert "greater than the maximum" in main_view.config.log_view.log_message
    assert main_view.status_bar.message == "Fix the configuration first"


def test_a_run_waits_for_every_duration(main_view: TaskMainView) -> None:
    main_view.config.min_duration.value = None

    main_view.buttons.run.clicked.emit()

    assert main_view.details.tasks.rows == []
    assert "Every value is needed" in main_view.config.log_view.log_message


def test_a_task_of_a_run_loaded_from_a_study_runs_nothing(main_view: TaskMainView) -> None:
    rows = [["1", "2.0", str(TaskStatus.SUCCEEDED.value), ""]]
    main_view.details.tasks.rows = rows  # as a study opens: its tasks' jobs are gone

    main_view.details.tasks.cell_clicked.emit(0, 0)

    assert not main_view.jobs.is_running
    assert main_view.details.tasks.rows == rows


def test_the_failure_percentage_is_a_slider_of_whole_percents(
    qtbot: QtBot, main_view: TaskMainView
) -> None:
    percentage = main_view.config.failure_percentage
    assert isinstance(percentage.renderer, RendererContainer)
    field = percentage.renderer.get_renderer("field")
    assert isinstance(field, QtWidgetRenderer)
    slider = field.qt_object
    assert isinstance(slider, QValueSlider)
    assert slider.shown_value() == 20

    slider.show()
    slider.setFocus()
    qtbot.keyClick(slider, Qt.Key.Key_Right)
    assert percentage.value == 21
    qtbot.keyClick(slider, Qt.Key.Key_End)
    assert percentage.value == 100
