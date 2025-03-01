from examples.simpletableview.app import Model, SimpleTableViewApp
from examples.simpletableview.example import ExampleMainView, PointsTableView

import pytest

from collections import OrderedDict
from pathlib import Path
from typing import Tuple

DATA_DIRPATH = Path(Path(__file__).parent, "data")


@pytest.fixture()
def app_points(
    app: SimpleTableViewApp,
) -> Tuple[PointsTableView, ExampleMainView, Model]:
    points_view = app.main_view.points_view
    assert points_view.items is not None
    points_view.items.clear_selection()
    return (points_view, app.main_view, app.model)


def test_import_empty(app_points: Tuple[PointsTableView, ExampleMainView, Model]) -> None:
    view, main_view, _ = app_points
    csv_empty_filepath = Path(DATA_DIRPATH, "test_empty.csv")
    assert csv_empty_filepath.exists() is True
    assert view.items is not None
    assert main_view.progress_popup_view.tasks is None
    assert view.items.get_nb_rows() == 0
    main_view.file_view.open_file = lambda: str(  # type:ignore[method-assign]
        csv_empty_filepath
    )
    view.import_clicked()
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks[0].error_message != ""
    assert view.items.get_nb_rows() == 0


def test_import_unknown(app_points: Tuple[PointsTableView, ExampleMainView, Model]) -> None:
    view, main_view, _ = app_points
    csv_unknown_filepath = Path(DATA_DIRPATH, "test_unknown.csv")
    assert csv_unknown_filepath.exists() is True
    assert view.items is not None
    assert main_view.progress_popup_view.tasks is None
    assert view.items.get_nb_rows() == 0
    main_view.file_view.open_file = lambda: str(  # type:ignore[method-assign]
        csv_unknown_filepath
    )
    view.import_clicked()
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks[0].error_message != ""
    assert "Id" in main_view.progress_popup_view.tasks[0].error_message
    assert view.items.get_nb_rows() == 0


def test_import(app_points: Tuple[PointsTableView, ExampleMainView, Model]) -> None:
    view, main_view, _ = app_points
    csv_filepath = Path(DATA_DIRPATH, "test_correct.csv")
    assert csv_filepath.exists() is True
    assert view.items is not None
    assert main_view.progress_popup_view.tasks is None
    assert view.items.get_nb_rows() == 0
    # add rows
    view.items.insert(0)
    view.items.insert(1)
    assert view.items.get_nb_rows() == 2
    main_view.file_view.open_file = lambda: str(csv_filepath)  # type:ignore[method-assign]
    view.import_clicked()
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks[0].error_message == ""
    # The table is cleaned and then the values of the csv are added
    assert view.items.get_nb_rows() == 4
    for j in range(4):
        assert view.items.get_edit_data(j, 0) == f"point {j+1}"
        assert view.items.get_edit_data(j, 1) == float(3 * j + 1)
        assert view.items.get_edit_data(j, 2) == float(3 * j + 2)
        assert view.items.get_edit_data(j, 3) == float(3 * j + 3)


def test_import_without_cleaning(
    app_points: Tuple[PointsTableView, ExampleMainView, Model],
) -> None:
    view, main_view, _ = app_points
    csv_filepath = Path(DATA_DIRPATH, "test_correct.csv")
    assert csv_filepath.exists() is True
    assert view.items is not None
    assert main_view.progress_popup_view.tasks is None
    assert view.items.get_nb_rows() == 0
    # add rows
    view.items.insert(0)
    view.items.insert(1)
    assert view.items.get_nb_rows() == 2
    main_view.file_view.open_file = lambda: str(csv_filepath)  # type:ignore[method-assign]
    # answer no the question do you want to clean
    main_view.message_view.run = lambda: False  # type:ignore[method-assign]
    view.import_clicked()
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks[0].error_message == ""
    # The table is not cleaned
    assert view.items.get_nb_rows() == 6
    for k, i in enumerate(range(2, 6)):
        assert view.items.get_edit_data(i, 0) == f"point {k+1}"


def test_import_incomplete(
    app_points: Tuple[PointsTableView, ExampleMainView, Model],
) -> None:
    view, main_view, _ = app_points
    csv_incomplete_path = Path(DATA_DIRPATH, "test_incomplete.csv")
    assert csv_incomplete_path.exists() is True
    assert view.items is not None
    assert main_view.progress_popup_view.tasks is None
    assert view.items.get_nb_rows() == 0
    main_view.file_view.open_file = lambda: str(  # type:ignore[method-assign]
        csv_incomplete_path
    )
    view.import_clicked()
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks[0].error_message == ""
    assert main_view.progress_popup_view.tasks[0].warning_message != ""
    assert view.items.get_nb_rows() == 4
    for j in range(4):
        assert view.items.get_edit_data(j, 0) == f"point {j+1}"
        assert view.items.get_edit_data(j, 1) == float(3 * j + 1)
        assert view.items.get_edit_data(j, 2) == float(3 * j + 2)
        assert view.items.get_edit_data(j, 3) == float(3 * j + 3)


def test_export(
    app_points: Tuple[PointsTableView, ExampleMainView, Model],
    tmp_path: Path,
) -> None:
    view, main_view, _ = app_points
    assert view.items is not None
    # Add the datas same as the file test_correct.csv
    for j in range(4):
        view.items.insert(j)
    for j in range(4):
        assert view.items.set_data(j, 1, str(3.0 * j + 1)) is True
        assert view.items.set_data(j, 2, str(3.0 * j + 2)) is True
        assert view.items.set_data(j, 3, str(3.0 * j + 3)) is True
    # export in the tmp dir
    filepath = Path(tmp_path, "test_export.csv")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    view.export_clicked()
    # check if the files are the same
    filepath_ref = Path(DATA_DIRPATH, "test_correct.csv")
    assert filepath.read_text() == filepath_ref.read_text()


def test_add(app_points: Tuple[PointsTableView, ExampleMainView, Model]) -> None:
    view, _, _ = app_points
    assert view.items is not None
    view.add_clicked()
    assert view.items.get_nb_rows() == 1
    assert view.items.get_data(0, 0) == "point 1"
    assert view.items.get_data(0, 1) == "0.00"
    assert view.items.get_data(0, 2) == "0.00"
    assert view.items.get_data(0, 3) == "0.00"


def test_remove(app_points: Tuple[PointsTableView, ExampleMainView, Model]) -> None:
    view, _, _ = app_points
    assert view.items is not None
    assert view.items.get_nb_rows() == 0
    view.add_clicked()
    assert view.items.get_nb_rows() == 1
    view.items.set_selected_rows([0])
    assert view.items.get_confirmation_message() == ""
    view.remove_clicked()
    assert view.items.get_nb_rows() == 0


def test_shortcut_clear(app_points: Tuple[PointsTableView, ExampleMainView, Model]) -> None:
    view, _, _ = app_points
    assert view.items is not None
    assert view.items.get_nb_rows() == 0
    view.items.insert(0)
    assert view.items.set_data(0, 0, "point 1") is True
    assert view.items.set_data(0, 1, "1.0") is True
    assert view.items.set_data(0, 2, "2.0") is True
    assert view.items.set_data(0, 3, "3.0") is True
    assert view.items.get_nb_rows() == 1
    view.items.set_selected_rows([0])
    view.shortcut_clear()
    assert view.items.get_data(0, 0) == ""
    assert view.items.get_data(0, 1) == "0.00"
    assert view.items.get_data(0, 2) == "0.00"
    assert view.items.get_data(0, 3) == "0.00"


def test_shortcut_add(app_points: Tuple[PointsTableView, ExampleMainView, Model]) -> None:
    view, _, _ = app_points
    assert view.items is not None
    assert view.items.get_nb_rows() == 0
    view.shortcut_add()
    view.shortcut_add()
    view.shortcut_add()
    assert view.items.get_nb_rows() == 3


def test_shortcut_delete(app_points: Tuple[PointsTableView, ExampleMainView, Model]) -> None:
    view, _, _ = app_points
    assert view.items is not None
    view.items.insert(0)
    assert view.items.get_nb_rows() == 1
    view.items.set_selected_rows([0])
    view.shortcut_delete()
    assert view.items.get_nb_rows() == 0


def test_copy_paste(app_points: Tuple[PointsTableView, ExampleMainView, Model]) -> None:
    """Test copy/paste."""
    view, _, _ = app_points
    assert view.items is not None
    view.items.insert(0)
    for column, value in enumerate(("point 1", 1.0, 2.0, 3.0)):
        view.items.set_data(0, column, str(value))
    view.items.insert(1)
    for column, value in enumerate(("point 2", 4.0, 5.0, 6.0)):
        view.items.set_data(1, column, str(value))
    view.items.insert(2)
    for column, value in enumerate(("point 3", 7.0, 8.0, 9.0)):
        view.items.set_data(2, column, str(value))
    assert view.items.get_nb_rows() == 3
    view.items.set_selected_rows([0, 2])
    view.shortcut_copy()
    # Paste with the selection of the first item (first row and column)
    # - clean all the table
    view.items.set_selected_rows([0, 1, 2])
    view.remove_clicked()
    assert view.items.get_nb_rows() == 0
    # - add two points
    view.items.insert(0)
    for column, value in enumerate(("point 3", 10.0, 11.0, 12.0)):
        view.items.set_data(0, column, str(value))
    view.items.insert(1)
    for column, value in enumerate(("point 4", 13.0, 14.0, 15.0)):
        view.items.set_data(1, column, str(value))
    # select the first item
    view.selected_items = OrderedDict({(0,): [0]})
    # paste
    view.shortcut_paste()
    # check if the paste is successfull
    assert view.items.get_edit_data(0, 0) == "point 1"
    assert view.items.get_edit_data(0, 1) == 1.0
    assert view.items.get_edit_data(0, 2) == 2.0
    assert view.items.get_edit_data(0, 3) == 3.0
    assert view.items.get_edit_data(1, 0) == "point 3"
    assert view.items.get_edit_data(1, 1) == 7.0
    assert view.items.get_edit_data(1, 2) == 8.0
    assert view.items.get_edit_data(1, 3) == 9.0
    # Paste with the selection of the first row
    # - clean
    view.items.set_selected_rows([0, 1])
    view.remove_clicked()
    # - add dummy data
    view.items.insert(0)
    for column, value in enumerate(("point 5", 16.0, 17.0, 18.0)):
        view.items.set_data(0, column, str(value))
    view.items.insert(1)
    for column, value in enumerate(("point 6", 19.0, 20.0, 21.0)):
        view.items.set_data(1, column, str(value))
    # - select the first row
    view.items.set_selected_rows([0])
    # - paste
    view.shortcut_paste()
    # - check
    assert view.items.get_edit_data(0, 0) == "point 1"
    assert view.items.get_edit_data(0, 1) == 1.0
    assert view.items.get_edit_data(0, 2) == 2.0
    assert view.items.get_edit_data(0, 3) == 3.0
    assert view.items.get_edit_data(1, 0) == "point 6"
    assert view.items.get_edit_data(1, 1) == 19.0
    assert view.items.get_edit_data(1, 2) == 20.0
    assert view.items.get_edit_data(1, 3) == 21.0


def test_copy_paste_by_items(
    app_points: Tuple[PointsTableView, ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, _ = app_points
    assert view.items is not None
    # set up
    view.items.insert(0)
    for column, value in enumerate(("point 1", 1.0, 2.0, 3.0)):
        view.items.set_data(0, column, str(value))
    view.items.insert(1)
    for column, value in enumerate(("point 2", 4.0, 5.0, 6.0)):
        view.items.set_data(1, column, str(value))
    view.items.insert(2)
    for column, value in enumerate(("point 3", 7.0, 8.0, 9.0)):
        view.items.set_data(2, column, str(value))
    assert view.items.get_nb_rows() == 3
    # copy
    view.selected_items = OrderedDict({(0,): [0, 2], (2,): [0, 2]})
    view.shortcut_copy()
    # clean
    view.items.set_selected_rows([0, 1, 2])
    view.remove_clicked()
    # add dummy data
    view.items.insert(0)
    for column, value in enumerate(("point 3", 10.0, 11.0, 12.0)):
        view.items.set_data(0, column, str(value))
    view.items.insert(1)
    for column, value in enumerate(("point 4", 13.0, 14.0, 15.0)):
        view.items.set_data(1, column, str(value))
    # select items
    view.selected_items = OrderedDict({(0,): [0, 3], (1,): [0, 3]})
    # paste
    view.shortcut_paste()
    # check
    assert view.items.get_edit_data(0, 0) == "point 1"
    assert view.items.get_edit_data(0, 1) == 10.0
    assert view.items.get_edit_data(0, 2) == 11.0
    assert view.items.get_edit_data(0, 3) == 2.0
    assert view.items.get_edit_data(1, 0) == "point 3"
    assert view.items.get_edit_data(1, 1) == 13.0
    assert view.items.get_edit_data(1, 2) == 14.0
    assert view.items.get_edit_data(1, 3) == 8.0


def test_copy_paste_one_data(
    app_points: Tuple[PointsTableView, ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, _ = app_points
    assert view.items is not None
    # set up
    view.items.insert(0)
    for column, value in enumerate(("point 1", 1.0, 2.0, 3.0)):
        view.items.set_data(0, column, str(value))
    view.items.insert(1)
    for column, value in enumerate(("point 2", 4.0, 5.0, 6.0)):
        view.items.set_data(1, column, str(value))
    view.items.insert(2)
    for column, value in enumerate(("point 3", 7.0, 8.0, 9.0)):
        view.items.set_data(2, column, str(value))
    # copy
    view.selected_items = OrderedDict({(0,): [3]})
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict({(0,): [1, 2], (1,): [1, 2], (2,): [1, 2]})
    view.shortcut_paste()
    # check
    assert view.items.get_edit_data(0, 0) == "point 1"
    assert view.items.get_edit_data(0, 1) == 3.0
    assert view.items.get_edit_data(0, 2) == 3.0
    assert view.items.get_edit_data(0, 3) == 3.0
    assert view.items.get_edit_data(1, 0) == "point 2"
    assert view.items.get_edit_data(1, 1) == 3.0
    assert view.items.get_edit_data(1, 2) == 3.0
    assert view.items.get_edit_data(1, 3) == 6.0
    assert view.items.get_edit_data(2, 0) == "point 3"
    assert view.items.get_edit_data(2, 1) == 3.0
    assert view.items.get_edit_data(2, 2) == 3.0
    assert view.items.get_edit_data(2, 3) == 9.0


def test_copy_paste_one_row(
    app_points: Tuple[PointsTableView, ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    view.items.insert(0)
    for column, value in enumerate(("point 1", 1.0, 2.0, 3.0)):
        view.items.set_data(0, column, str(value))
    view.items.insert(1)
    for column, value in enumerate(("point 2", 4.0, 5.0, 6.0)):
        view.items.set_data(1, column, str(value))
    view.items.insert(2)
    for column, value in enumerate(("point 3", 7.0, 8.0, 9.0)):
        view.items.set_data(2, column, str(value))
    # copy
    view.selected_items = OrderedDict({(0,): [1, 2, 3]})
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict({(i,): [1, 2, 3] for i in range(3)})
    view.shortcut_paste()
    # check
    assert view.items.get_edit_data(0, 0) == "point 1"
    assert view.items.get_edit_data(0, 1) == 1.0
    assert view.items.get_edit_data(0, 2) == 2.0
    assert view.items.get_edit_data(0, 3) == 3.0
    assert view.items.get_edit_data(1, 0) == "point 2"
    assert view.items.get_edit_data(1, 1) == 1.0
    assert view.items.get_edit_data(1, 2) == 2.0
    assert view.items.get_edit_data(1, 3) == 3.0
    assert view.items.get_edit_data(2, 0) == "point 3"
    assert view.items.get_edit_data(2, 1) == 1.0
    assert view.items.get_edit_data(2, 2) == 2.0
    assert view.items.get_edit_data(2, 3) == 3.0
