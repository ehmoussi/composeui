from composeui.core.tasks.abstracttask import TaskStatus
from composeui.items.linkedtable.linkedtableview import LinkedTableView
from examples.linkedtableview.sqlalchemy.app import LinkedTableViewApp, Model
from examples.linkedtableview.sqlalchemy.example import ExampleMainView
from examples.linkedtableview.sqlalchemy.lines import LinesItems, PointsItems

import pytest

from pathlib import Path
from typing import Tuple


@pytest.fixture()
def app_lines(
    app: LinkedTableViewApp,
) -> Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model]:
    app.model.lines_query.add_line()
    app.model.lines_query.add_line()
    app.model.lines_query.add_point(1)
    app.model.lines_query.add_point(1)
    app.model.lines_query.add_point(1)
    app.model.lines_query.add_point(1)
    assert app.model.lines_query.count_lines() == 2
    assert app.model.lines_query.count_points(0) == 0
    assert app.model.lines_query.count_points(1) == 4
    return (app.main_view.lines, app.main_view, app.model)


def test_update_detail_table(
    app_lines: Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model],
) -> None:
    linked_table, *_ = app_lines
    assert linked_table.master_table.items is not None
    assert linked_table.detail_table.items is not None
    assert linked_table.detail_table.is_enabled is False
    # select first row with no points
    linked_table.master_table.items.set_selected_rows([0])
    linked_table.master_table.selection_changed()
    assert linked_table.detail_table.is_enabled is True
    assert linked_table.detail_table.items.get_nb_rows() == 0
    assert linked_table.detail_table.title == "line 1"
    # select second row with 4 points
    linked_table.master_table.items.set_selected_rows([1])
    linked_table.master_table.selection_changed()
    assert linked_table.detail_table.is_enabled is True
    assert linked_table.detail_table.items.get_nb_rows() == 4
    assert linked_table.detail_table.title == "line 2"


def test_open_save_study(
    app_lines: Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model],
    tmp_path: Path,
) -> None:
    linked_table, main_view, _ = app_lines
    filepath = Path(tmp_path, "linkedtableview.example")
    assert filepath.exists() is False
    # save file
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    main_view.menu.file.save.triggered()
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks.status == TaskStatus.SUCCESS
    # check the file exists
    assert filepath.exists() is True
    # update the view
    assert linked_table.master_table.items is not None
    linked_table.master_table.items.set_selected_rows([0, 1])
    linked_table.master_table.selection_changed()
    linked_table.master_table.remove_clicked()
    assert linked_table.master_table.items.get_nb_rows() == 0
    # open file
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    main_view.menu.file.open_file.triggered()
    # check if the opening is a success
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks[0].error_message == ""
    assert main_view.progress_popup_view.tasks.status == TaskStatus.SUCCESS
    main_view.progress_popup_view.finished()
    # check if the view come back to initial state
    assert linked_table.master_table.items.get_nb_rows() == 2
    assert linked_table.detail_table.items is not None
    linked_table.master_table.items.set_selected_rows([0])
    linked_table.master_table.selection_changed()
    assert linked_table.detail_table.items.get_nb_rows() == 0
    linked_table.master_table.items.set_selected_rows([1])
    linked_table.master_table.selection_changed()
    assert linked_table.detail_table.items.get_nb_rows() == 4


def test_new(
    app_lines: Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model],
) -> None:
    """Test the new file menu action."""
    linked_table, main_view, _ = app_lines
    # trigger new action
    main_view.message_view.run.return_value = True  # type: ignore[attr-defined]
    main_view.menu.file.new.triggered()
    # check that the values are back to the initial state
    assert linked_table.master_table.items is not None
    assert linked_table.master_table.items.get_nb_rows() == 0
