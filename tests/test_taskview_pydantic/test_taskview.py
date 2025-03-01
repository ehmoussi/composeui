from composeui.core.tasks.abstracttask import TaskStatus
from examples.taskview.pydantic.app import IExampleMainView, Model, PydanticTaskViewApp
from examples.taskview.pydantic.task import ITaskView

import pytest

from pathlib import Path
from typing import Tuple


@pytest.fixture()
def app_task(
    app: PydanticTaskViewApp,
) -> Tuple[ITaskView, IExampleMainView, Model]:
    return (app.main_view.task, app.main_view, app.model)


def test_initialize(app_task: Tuple[ITaskView, IExampleMainView, Model]) -> None:
    view, _, _ = app_task
    assert view.progress.is_percentage_visible is False
    assert view.progress.minimum == 0
    assert view.progress.maximum == 100
    assert view.progress.value == 0
    assert view.progress.run_text == "Run"
    assert view.progress.cancel_text == "Cancel"
    assert view.progress.button_enabled is True
    assert view.progress.button_text == "Run"
    assert view.status_tasks == [""] * 25
    assert view.progress.tasks is not None
    assert len(view.progress.tasks) == 25


def test_run(app_task: Tuple[ITaskView, IExampleMainView, Model]) -> None:
    view, _, model = app_task
    assert view.progress.tasks is not None
    view.config.min_duration.field_view.value = 0
    view.config.min_duration.field_view.value_changed()
    assert model.root.min_duration == 0
    view.config.max_duration.field_view.value = 1
    view.config.max_duration.field_view.value_changed()
    assert model.root.max_duration == 1
    view.config.percentage_failure.field_view.value = 0
    view.config.percentage_failure.field_view.value_changed()
    assert model.root.percentage_failure == 0
    view.progress.button_clicked()
    while view.progress.tasks.is_running:
        pass
    view.progress.finished()
    assert view.status_tasks == ["Success"] * 25
    #
    # test cancel
    #
    model.root.max_duration = 5
    view.progress.button_clicked()
    # second click is to cancel
    view.progress.button_clicked()
    while view.progress.tasks.is_running:
        pass
    view.progress.finished()
    assert set(view.status_tasks) == {"Success", "Canceled"}


def test_open_save_study(
    app_task: Tuple[ITaskView, IExampleMainView, Model], tmp_path: Path
) -> None:
    view, main_view, model = app_task
    # set up
    filepath = Path(tmp_path, "task.example")
    assert filepath.exists() is False
    view.config.min_duration.field_view.value = 5
    view.config.min_duration.field_view.value_changed()
    view.config.max_duration.field_view.value = 20
    view.config.max_duration.field_view.value_changed()
    view.config.percentage_failure.field_view.value = 50
    view.config.percentage_failure.field_view.value_changed()
    # save file
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    main_view.menu.file.save.triggered()
    # check the file exists
    assert filepath.exists() is True
    # update the view
    view.config.min_duration.field_view.value = 1
    view.config.max_duration.field_view.value = 1
    view.config.percentage_failure.field_view.value = 1
    # open file
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    main_view.menu.file.open_file.triggered()
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks.status == TaskStatus.SUCCESS
    main_view.progress_popup_view.finished()
    assert view.config.min_duration.field_view.value == 5
    assert view.config.max_duration.field_view.value == 20
    assert view.config.percentage_failure.field_view.value == 50


def test_new(app_task: Tuple[ITaskView, IExampleMainView, Model]) -> None:
    """Test the new file menu action."""
    view, main_view, model = app_task
    # initial state
    assert view.config.min_duration.field_view.value == 3
    assert view.config.max_duration.field_view.value == 10
    assert view.config.percentage_failure.field_view.value == 20
    # set up
    view.config.min_duration.field_view.value = 5
    view.config.min_duration.field_view.value_changed()
    view.config.max_duration.field_view.value = 20
    view.config.max_duration.field_view.value_changed()
    view.config.percentage_failure.field_view.value = 50
    view.config.percentage_failure.field_view.value_changed()
    # new action
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    main_view.menu.file.new.triggered()
    # assert main_view.progress_popup_view.tasks is not None
    # assert main_view.progress_popup_view.tasks.status == TaskStatus.SUCCESS
    # main_view.progress_popup_view.finished()
    # check that the values are back to the initial state
    assert view.config.min_duration.field_view.value == 3
    assert view.config.max_duration.field_view.value == 10
    assert view.config.percentage_failure.field_view.value == 20
