from composeui.core.tasks.abstracttask import TaskStatus
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.menu import FileMenu
from composeui.mainview.views.toolbar import FileToolBar
from composeui.model.basemodel import BaseModel
from examples.mainview.app import MainViewApp

import pytest

from pathlib import Path
from typing import Tuple, Union


def test_title(app: MainViewApp) -> None:
    assert app.main_view.title == "Example"


def test_extension_study(app: MainViewApp) -> None:
    assert app.main_view.extension_study == "example"


def test_message_before_closing(app: MainViewApp) -> None:
    assert app.main_view.message_before_closing != ""


def test_save_before_exit(app: MainViewApp, tmp_path: Path) -> None:
    main_view, model = app.main_view, app.model
    assert model.filepath is None
    assert main_view.force_close is False
    mysave_path = Path(tmp_path, "mysave.example")
    assert mysave_path.exists() is False
    # Set the filepath to return
    main_view.file_view.save_file = lambda: str(mysave_path)  # type: ignore[method-assign]
    assert main_view.progress_popup_view.is_visible is False
    # save
    main_view.save_before_exit()
    # check if the task is a success
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks.join_error_messages() == ""
    assert main_view.progress_popup_view.tasks.status == TaskStatus.SUCCESS
    assert mysave_path.exists() is True
    assert model.filepath == mysave_path
    # call the slots that should be called after the tasks are finished
    main_view.progress_popup_view.finished()
    # No message and the main view is forced to close
    assert main_view.message_view.message == ""
    assert main_view.force_close is True


@pytest.fixture()
def app_menu_toolbar_view(
    app: MainViewApp, is_menu: bool = True
) -> Tuple[MainView, Union[FileMenu, FileToolBar], BaseModel]:
    """Fixture to test the file menu and toolbar with the same tests."""
    if is_menu:
        return (app.main_view, app.main_view.menu.file, app.model)
    return (app.main_view, app.main_view.toolbar.file, app.model)


@pytest.mark.parametrize("app_menu_toolbar_view", [True, False], indirect=True)
def test_file_menu_new(app_menu_toolbar_view: Tuple[MainView, FileMenu, BaseModel]) -> None:
    main_view, view, model = app_menu_toolbar_view
    model.filepath = Path("test.example")
    # confirm that we want to create a new study
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    # the new study clear the filepath
    view.new.triggered()
    assert model.filepath is None


@pytest.mark.parametrize("app_menu_toolbar_view", [True, False], indirect=True)
def test_file_menu_open(
    app_menu_toolbar_view: Tuple[MainView, FileMenu, BaseModel],
    tmp_path: Path,
) -> None:
    main_view, view, model = app_menu_toolbar_view
    assert model.filepath is None
    mysave_path = Path(tmp_path, "mysave.example")
    # set the filepath to return when the file view is displayed
    main_view.file_view.open_file = lambda: str(mysave_path)  # type: ignore[method-assign]
    # the new study clear the filepath
    view.open_file.triggered()
    # Failed because the file doesn't exists
    assert model.filepath is None
    # Retry with an existing file
    mysave_path.write_text("my file")
    view.open_file.triggered()
    # The file is not a .example study
    assert model.filepath is None
    # Retry with saving the study in the file
    model.save(mysave_path)
    view.open_file.triggered()
    assert model.filepath == mysave_path


@pytest.mark.parametrize("app_menu_toolbar_view", [True, False], indirect=True)
def test_file_menu_save(
    app_menu_toolbar_view: Tuple[MainView, FileMenu, BaseModel],
    tmp_path: Path,
) -> None:
    main_view, view, model = app_menu_toolbar_view
    assert model.filepath is None
    mysave_path = Path(tmp_path, "mysave.example")
    # Try to save without specifying a path to save to
    main_view.file_view.save_file = lambda: ""  # type: ignore[method-assign]
    view.save.triggered()
    assert model.filepath is None
    # set the filepath to return when the file view is displayed
    main_view.file_view.save_file = lambda: str(mysave_path)  # type: ignore[method-assign]
    view.save.triggered()
    assert model.filepath == mysave_path
    # Resaving doesn't ask for the path to save
    main_view.file_view.save_file = lambda: ""  # type: ignore[method-assign]
    view.save.triggered()
    assert model.filepath == mysave_path


@pytest.mark.parametrize("app_menu_toolbar_view", [True, False], indirect=True)
def test_file_menu_save_as(
    app_menu_toolbar_view: Tuple[MainView, FileMenu, BaseModel],
    tmp_path: Path,
) -> None:
    main_view, view, model = app_menu_toolbar_view
    assert model.filepath is None
    mysave_path_1 = Path(tmp_path, "mysave.example")
    mysave_path_2 = Path(tmp_path, "mysave.example")
    # Try to save without specifying a path to save to
    main_view.file_view.save_file = lambda: ""  # type: ignore[method-assign]
    view.save_as.triggered()
    assert model.filepath is None
    # set the filepath to return when the file view is displayed
    main_view.file_view.save_file = lambda: str(mysave_path_1)  # type: ignore[method-assign]
    view.save_as.triggered()
    assert model.filepath == mysave_path_1
    # Resaving with a new path
    main_view.file_view.save_file = lambda: str(mysave_path_2)  # type: ignore[method-assign]
    view.save_as.triggered()
    assert model.filepath == mysave_path_2


def test_file_menu_exit_app(app: MainViewApp) -> None:
    assert app.main_view.closed is False
    app.main_view.menu.file.exit_app.triggered()
    assert app.main_view.closed is True
