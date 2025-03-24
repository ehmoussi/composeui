from composeui.items.table.tableview import TableView
from composeui.mainview.views.messageview import MessageViewType
from examples.tableview.app import Model, TableViewApp
from examples.tableview.example import ExampleMainView
from examples.tableview.points import PointsItems

import pytest

import sys
from collections import OrderedDict
from pathlib import Path
from typing import Tuple

DATA_DIRPATH = Path("tests", "test_tableview", "data")


@pytest.fixture()
def app_points(
    app: TableViewApp,
) -> Tuple[TableView[PointsItems], ExampleMainView, Model]:
    return (app.main_view.points_view, app.main_view, app.model)


def test_import_empty(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    view, main_view, _ = app_points
    csv_empty_filepath = Path(DATA_DIRPATH, "test_empty.csv")
    assert csv_empty_filepath.exists() is True
    assert view.items is not None
    assert main_view.progress_popup_view.tasks is None
    assert view.items.get_nb_rows() == 0
    main_view.file_view.open_file = lambda: str(csv_empty_filepath)  # type: ignore[method-assign]
    view.import_clicked()
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks[0].error_message != ""
    assert view.items.get_nb_rows() == 0


def test_import_unknown(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    view, main_view, _ = app_points
    csv_unknown_filepath = Path(DATA_DIRPATH, "test_unknown.csv")
    assert csv_unknown_filepath.exists() is True
    assert view.items is not None
    assert main_view.progress_popup_view.tasks is None
    assert view.items.get_nb_rows() == 0
    main_view.file_view.open_file = lambda: str(csv_unknown_filepath)  # type: ignore[method-assign]
    view.import_clicked()
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks[0].error_message != ""
    assert "Id" in main_view.progress_popup_view.tasks[0].error_message
    assert view.items.get_nb_rows() == 0


def test_import(app_points: Tuple[TableView[PointsItems], ExampleMainView, Model]) -> None:
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
    main_view.file_view.open_file = lambda: str(csv_filepath)  # type: ignore[method-assign]
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
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
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
    main_view.file_view.open_file = lambda: str(csv_filepath)  # type: ignore[method-assign]
    # answer no the question do you want to clean
    main_view.message_view.run = lambda: False  # type: ignore[method-assign]
    view.import_clicked()
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks[0].error_message == ""
    # The table is not cleaned
    assert view.items.get_nb_rows() == 6
    for k, i in enumerate(range(2, 6)):
        assert view.items.get_edit_data(i, 0) == f"point {k+1}"


def test_import_incomplete(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    view, main_view, _ = app_points
    csv_incomplete_path = Path(DATA_DIRPATH, "test_incomplete.csv")
    assert csv_incomplete_path.exists() is True
    assert view.items is not None
    assert main_view.progress_popup_view.tasks is None
    assert view.items.get_nb_rows() == 0
    main_view.file_view.open_file = lambda: str(csv_incomplete_path)  # type: ignore[method-assign]
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
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
    tmp_path: Path,
) -> None:
    view, main_view, _ = app_points
    assert view.items is not None
    # Add the datas same as the file test_correct.csv
    for j in range(4):
        view.items.insert(j)
    for j in range(4):
        view.items.set_data(j, 1, str(3.0 * j + 1))
        view.items.set_data(j, 2, str(3.0 * j + 2))
        view.items.set_data(j, 3, str(3.0 * j + 3))
    # export in the tmp dir
    filepath = Path(tmp_path, "test_export.csv")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    view.export_clicked()
    assert filepath.exists()
    # check if the files are the same
    filepath_ref = Path(DATA_DIRPATH, "test_correct.csv")
    assert filepath.read_text() == filepath_ref.read_text()


@pytest.mark.parametrize("extension", [".xlsx", ".xls", ".json"])
def test_import_export_excel_json(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
    tmp_path: Path,
    extension: str,
) -> None:
    view, main_view, model = app_points
    model.is_debug = True
    assert view.items is not None
    # set up the table
    for j in range(4):
        view.items.insert(j)
    for j in range(4):
        view.items.set_data(j, 1, str(3.0 * j + 1))
        view.items.set_data(j, 2, str(3.0 * j + 2))
        view.items.set_data(j, 3, str(3.0 * j + 3))
    # export in the tmp dir
    filepath = Path(tmp_path, f"test_export{extension}")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    view.export_clicked()
    main_view.progress_popup_view.finished()
    if sys.version_info[:2] <= (3, 8) and extension == ".json":
        assert "version of pandas" in main_view.message_view.message
    else:
        assert main_view.message_view.message == ""
        assert filepath.exists()
        # clean the table
        view.items.remove_all()
        # import the exported file
        main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
        view.import_clicked()
        main_view.progress_popup_view.finished()
        if sys.version_info[:2] == (3, 6) and extension == ".xls":
            # the export is always to .xlsx format
            # old version of pandas don't manage the mismatch between the extension and
            # the format
            assert (
                main_view.message_view.message == "Change the extension of the file to .xlsx"
            )
        else:
            assert main_view.message_view.message == ""
            # check if the table as the set up table of the beginning
            assert view.items.get_nb_rows() == 4
            for j in range(4):
                assert view.items.get_edit_data(j, 1) == (3.0 * j + 1)
                assert view.items.get_edit_data(j, 2) == (3.0 * j + 2)
                assert view.items.get_edit_data(j, 3) == (3.0 * j + 3)


@pytest.mark.parametrize("extension", [".md", ".html"])
def test_export_markdown_html(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
    tmp_path: Path,
    extension: str,
) -> None:
    view, main_view, _ = app_points
    assert view.items is not None
    # set up the table
    for j in range(4):
        view.items.insert(j)
    for j in range(4):
        view.items.set_data(j, 1, str(3.0 * j + 1))
        view.items.set_data(j, 2, str(3.0 * j + 2))
        view.items.set_data(j, 3, str(3.0 * j + 3))
    # export in the tmp dir
    filepath = Path(tmp_path, f"test_export{extension}")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    view.export_clicked()
    main_view.progress_popup_view.finished()
    assert main_view.message_view.message == ""
    assert filepath.exists()
    # check if the files are the same
    filepath_ref = Path(DATA_DIRPATH, f"test_correct{extension}")
    assert filepath.read_text() == filepath_ref.read_text()


def test_add(app_points: Tuple[TableView[PointsItems], ExampleMainView, Model]) -> None:
    view, _, _ = app_points
    assert view.items is not None
    view.add_clicked()
    assert view.items.get_nb_rows() == 1
    assert view.items.get_data(0, 0) == "point 1"
    assert view.items.get_data(0, 1) == "0.00"
    assert view.items.get_data(0, 2) == "0.00"
    assert view.items.get_data(0, 3) == "0.00"


def test_remove(app_points: Tuple[TableView[PointsItems], ExampleMainView, Model]) -> None:
    view, _, _ = app_points
    assert view.items is not None
    view.add_clicked()
    assert view.items.get_nb_rows() == 1
    view.items.set_selected_rows([0])
    view.remove_clicked()
    assert view.items.get_nb_rows() == 0


def test_shortcut_clear(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    view, _, model = app_points
    assert view.items is not None
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    assert view.items.get_nb_rows() == 1
    assert view.items.get_data(0, 0) == "point 1"
    assert view.items.get_data(0, 1) == "1.00"
    assert view.items.get_data(0, 2) == "2.00"
    assert view.items.get_data(0, 3) == "3.00"
    view.items.set_selected_rows([0])
    view.shortcut_clear()
    assert view.items.get_data(0, 0) == ""
    assert view.items.get_data(0, 1) == "0.00"
    assert view.items.get_data(0, 2) == "0.00"
    assert view.items.get_data(0, 3) == "0.00"


def test_shortcut_add(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    view, _, _ = app_points
    assert view.items is not None
    assert view.items.get_nb_rows() == 0
    view.shortcut_add()
    view.shortcut_add()
    view.shortcut_add()
    assert view.items.get_nb_rows() == 3


def test_shortcut_delete(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    view, _, model = app_points
    assert view.items is not None
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    assert view.items.get_nb_rows() == 1
    view.items.set_selected_rows([0])
    view.shortcut_delete()
    assert view.items.get_nb_rows() == 0


def test_undo_redo(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test the undo/redo mechanism."""
    view, main_view, _ = app_points
    assert view.items is not None
    # set up add rows
    view.add_clicked()
    view.items.set_data_with_history(0, 0, "P1")
    view.add_clicked()
    view.items.set_data_with_history(1, 0, "P2")
    view.add_clicked()
    view.items.set_data_with_history(2, 0, "P3")
    view.add_clicked()
    assert view.items.get_data(3, 0) == "point 4"
    view.items.set_data_with_history(3, 0, "P4")
    assert view.items.get_nb_rows() == 4
    # undo
    main_view.toolbar.file.undo.triggered()
    assert view.items.get_data(3, 0) == "point 4"
    main_view.toolbar.file.undo.triggered()
    assert view.items.get_nb_rows() == 3
    main_view.toolbar.file.undo.triggered()
    assert view.items.get_data(2, 0) == "point 3"
    main_view.toolbar.file.undo.triggered()
    assert view.items.get_nb_rows() == 2
    # redo
    main_view.toolbar.file.redo.triggered()
    assert view.items.get_nb_rows() == 3
    main_view.toolbar.file.redo.triggered()
    assert view.items.get_data(2, 0) == "P3"
    main_view.toolbar.file.redo.triggered()
    assert view.items.get_nb_rows() == 4
    main_view.toolbar.file.redo.triggered()
    assert view.items.get_data(3, 0) == "P4"


def test_undo_redo_open_save(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model], tmpdir: Path
) -> None:
    """Test the undo/redo mechanism and its persistence after saving and opening a study."""
    view, main_view, _ = app_points
    assert view.items is not None
    # set up add rows
    view.add_clicked()
    view.items.set_data_with_history(0, 0, "P1")
    view.add_clicked()
    view.items.set_data_with_history(1, 0, "P2")
    assert view.items.get_nb_rows() == 2
    # undo
    main_view.toolbar.file.undo.triggered()
    main_view.toolbar.file.undo.triggered()
    main_view.toolbar.file.undo.triggered()
    main_view.toolbar.file.undo.triggered()
    assert view.items.get_nb_rows() == 0
    # save
    main_view.file_view.save_file = (  # type: ignore[method-assign]
        lambda: str(Path(tmpdir, "study.example"))
    )
    main_view.toolbar.file.save.triggered()
    # new
    main_view.toolbar.file.new.triggered()
    main_view.toolbar.file.redo.triggered()
    assert view.items.get_nb_rows() == 0  # the history and the state is lost when doing new
    # open
    main_view.file_view.open_file = (  # type: ignore[method-assign]
        lambda: str(Path(tmpdir, "study.example"))
    )
    main_view.toolbar.file.open_file.triggered()
    # redo
    main_view.toolbar.file.redo.triggered()
    main_view.toolbar.file.redo.triggered()
    main_view.toolbar.file.redo.triggered()
    main_view.toolbar.file.redo.triggered()
    assert view.items.get_nb_rows() == 2
    assert view.items.get_data(0, 0) == "P1"
    assert view.items.get_data(1, 0) == "P2"


def test_copy_paste(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    assert view.items.get_nb_rows() == 3
    view.items.set_selected_rows([0, 2])
    view.shortcut_copy()
    # Paste with the selection of the first item (first row and column)
    # - clean all the table
    view.items.set_selected_rows([0, 1, 2])
    view.remove_clicked()
    assert view.items.get_nb_rows() == 0
    # - add two points
    model.points_query.insert(0, "point 3", 10.0, 11.0, 12.0)
    model.points_query.insert(1, "point 4", 13.0, 14.0, 15.0)
    # select the first item
    view.items.set_selected_row_items(OrderedDict({0: [0]}))
    # paste
    view.shortcut_paste()
    # check if the paste is successfull
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 3"
    assert model.points_query.get_x(1) == 7.0
    assert model.points_query.get_y(1) == 8.0
    assert model.points_query.get_z(1) == 9.0
    # Paste with the selection of the first row
    # - clean
    view.items.set_selected_rows([0, 1])
    view.remove_clicked()
    # - add dummy data
    model.points_query.insert(0, "point 5", 16.0, 17.0, 18.0)
    model.points_query.insert(1, "point 6", 19.0, 20.0, 21.0)
    # - select the first row
    view.items.set_selected_rows([0])
    # - paste
    view.shortcut_paste()
    # - check
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 6"
    assert model.points_query.get_x(1) == 19.0
    assert model.points_query.get_y(1) == 20.0
    assert model.points_query.get_z(1) == 21.0


def test_copy_paste_by_items(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    assert view.items.get_nb_rows() == 3
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [0, 2], 2: [0, 2]}))
    view.shortcut_copy()
    # clean
    view.items.set_selected_rows([0, 1, 2])
    view.remove_clicked()
    # add dummy data
    model.points_query.insert(0, "point 3", 10.0, 11.0, 12.0)
    model.points_query.insert(1, "point 4", 13.0, 14.0, 15.0)
    # select items
    view.items.set_selected_row_items(OrderedDict({0: [0, 3], 1: [0, 3]}))
    # paste
    view.shortcut_paste()
    # check
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 10.0
    assert model.points_query.get_y(0) == 11.0
    assert model.points_query.get_z(0) == 2.0
    assert model.points_query.get_name(1) == "point 3"
    assert model.points_query.get_x(1) == 13.0
    assert model.points_query.get_y(1) == 14.0
    assert model.points_query.get_z(1) == 8.0


def test_copy_paste_one_data(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [3]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({0: [1, 2], 1: [1, 2], 2: [1, 2]}))
    view.shortcut_paste()
    # check
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 3.0
    assert model.points_query.get_y(0) == 3.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 3.0
    assert model.points_query.get_y(1) == 3.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 3.0
    assert model.points_query.get_y(2) == 3.0
    assert model.points_query.get_z(2) == 9.0


def test_copy_paste_one_row(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2, 3]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({i: [1, 2, 3] for i in range(3)}))
    view.shortcut_paste()
    # check
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 1.0
    assert model.points_query.get_y(1) == 2.0
    assert model.points_query.get_z(1) == 3.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 1.0
    assert model.points_query.get_y(2) == 2.0
    assert model.points_query.get_z(2) == 3.0


def test_copy_paste_with_insertion(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2, 3], 1: [1, 2, 3]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({2: [1]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 4
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 1.0
    assert model.points_query.get_y(2) == 2.0
    assert model.points_query.get_z(2) == 3.0
    assert model.points_query.get_name(3) == "point 4"
    assert model.points_query.get_x(3) == 4.0
    assert model.points_query.get_y(3) == 5.0
    assert model.points_query.get_z(3) == 6.0


def test_copy_paste_with_insertion_with_multiple_selected_rows(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2, 3], 1: [1, 2, 3], 2: [1, 2, 3]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({1: [2], 2: [2]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 4
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 1.0
    assert model.points_query.get_z(1) == 2.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 4.0
    assert model.points_query.get_z(2) == 5.0
    assert model.points_query.get_name(3) == "point 4"
    assert model.points_query.get_x(3) == 0.0
    assert model.points_query.get_y(3) == 7.0
    assert model.points_query.get_z(3) == 8.0


def test_copy_paste_with_insertion_and_no_selection(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [0, 1], 1: [0, 1]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 5
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0
    assert model.points_query.get_name(3) == "point 1"
    assert model.points_query.get_x(3) == 1.0
    assert model.points_query.get_y(3) == 0.0
    assert model.points_query.get_z(3) == 0.0
    assert model.points_query.get_name(4) == "point 2"
    assert model.points_query.get_x(4) == 4.0
    assert model.points_query.get_y(4) == 0.0
    assert model.points_query.get_z(4) == 0.0


def test_copy_paste_with_scattered_copy(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    model.points_query.insert(3, "point 4", 10.0, 11.0, 12.0)
    model.points_query.insert(4, "point 5", 13.0, 14.0, 15.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({1: [1, 3], 2: [1]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({3: [1]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 5
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0
    assert model.points_query.get_name(3) == "point 4"
    assert model.points_query.get_x(3) == 4.0
    assert model.points_query.get_y(3) == 6.0
    assert model.points_query.get_z(3) == 12.0
    assert model.points_query.get_name(4) == "point 5"
    assert model.points_query.get_x(4) == 7.0
    assert model.points_query.get_y(4) == 14.0
    assert model.points_query.get_z(4) == 15.0


def test_copy_paste_more_columns(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2, 3]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({2: [1, 2]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 1.0
    assert model.points_query.get_y(2) == 2.0
    assert model.points_query.get_z(2) == 9.0


def test_copy_paste_more_columns2(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2, 3], 1: [1, 2, 3]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({0: [2], 1: [2]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 1.0
    assert model.points_query.get_z(0) == 2.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 4.0
    assert model.points_query.get_z(1) == 5.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0


def test_copy_paste_with_one_item_and_insertion(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2, 3], 1: [1, 2, 3], 2: [1, 2, 3]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({1: [2]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 4
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 1.0
    assert model.points_query.get_z(1) == 2.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 4.0
    assert model.points_query.get_z(2) == 5.0
    assert model.points_query.get_name(3) == "point 4"
    assert model.points_query.get_x(3) == 0.0
    assert model.points_query.get_y(3) == 7.0
    assert model.points_query.get_z(3) == 8.0


def test_copy_one_column_to_another(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [0], 1: [0], 2: [0]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({0: [1], 1: [1], 2: [1]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0


def test_copy_two_partial_column_no_selection(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    model.points_query.insert(3, "point 4", 10.0, 11.0, 12.0)
    model.points_query.insert(4, "point 5", 13.0, 14.0, 15.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [0, 1], 1: [0, 1], 2: [0, 1]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict())
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 8
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0
    assert model.points_query.get_name(3) == "point 4"
    assert model.points_query.get_x(3) == 10.0
    assert model.points_query.get_y(3) == 11.0
    assert model.points_query.get_z(3) == 12.0
    assert model.points_query.get_name(4) == "point 5"
    assert model.points_query.get_x(4) == 13.0
    assert model.points_query.get_y(4) == 14.0
    assert model.points_query.get_z(4) == 15.0
    assert model.points_query.get_name(5) == "point 1"
    assert model.points_query.get_x(5) == 1.0
    assert model.points_query.get_y(5) == 0.0
    assert model.points_query.get_z(5) == 0.0
    assert model.points_query.get_name(6) == "point 2"
    assert model.points_query.get_x(6) == 4.0
    assert model.points_query.get_y(6) == 0.0
    assert model.points_query.get_z(6) == 0.0
    assert model.points_query.get_name(7) == "point 3"
    assert model.points_query.get_x(7) == 7.0
    assert model.points_query.get_y(7) == 0.0
    assert model.points_query.get_z(7) == 0.0


def test_copy_rectangular_selection_paste_to_non_rectangular(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2], 1: [1, 2]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({0: [1], 1: [2], 2: [3]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 1.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 1.0


def test_copy_non_contiguous_selection_paste_to_contiguous(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, main_view, model = app_points
    assert main_view.message_view.message == ""
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [0, 2], 2: [0, 2]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({1: [0, 1, 2]}))
    view.shortcut_paste()
    # check
    assert main_view.message_view.message != ""
    assert main_view.message_view.message_type == MessageViewType.critical
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0


def test_copy_single_column_paste_multiple_non_adjacent_columns(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    model.points_query.insert(3, "point 4", 10.0, 11.0, 12.0)
    model.points_query.insert(4, "point 5", 13.0, 14.0, 15.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({1: [1, 2, 3]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({0: [1], 2: [1], 4: [1]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 5
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 4.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 4.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0
    assert model.points_query.get_name(3) == "point 4"
    assert model.points_query.get_x(3) == 10.0
    assert model.points_query.get_y(3) == 11.0
    assert model.points_query.get_z(3) == 12.0
    assert model.points_query.get_name(4) == "point 5"
    assert model.points_query.get_x(4) == 4.0
    assert model.points_query.get_y(4) == 14.0
    assert model.points_query.get_z(4) == 15.0


def test_copy_single_column_paste_multiple_non_adjacent_columns2(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    model.points_query.insert(3, "point 4", 10.0, 11.0, 12.0)
    model.points_query.insert(4, "point 5", 13.0, 14.0, 15.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({1: [0, 1, 2]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({0: [1], 2: [1], 4: [1]}))
    view.shortcut_paste()
    # check
    # failed because paste only the first item which is a string into float fields
    assert model.points_query.count() == 5
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0
    assert model.points_query.get_name(3) == "point 4"
    assert model.points_query.get_x(3) == 10.0
    assert model.points_query.get_y(3) == 11.0
    assert model.points_query.get_z(3) == 12.0
    assert model.points_query.get_name(4) == "point 5"
    assert model.points_query.get_x(4) == 13.0
    assert model.points_query.get_y(4) == 14.0
    assert model.points_query.get_z(4) == 15.0


def test_copy_multiple_non_adjacent_rows_paste_single_contiguous_block(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, main_view, model = app_points
    assert view.items is not None
    assert main_view.message_view.message == ""
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    model.points_query.insert(3, "point 4", 10.0, 11.0, 12.0)
    model.points_query.insert(4, "point 5", 13.0, 14.0, 15.0)
    model.points_query.insert(5, "point 6", 16.0, 17.0, 18.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({1: [0, 1, 2], 3: [0, 1, 2], 5: [0, 1, 2]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({2: [0, 1, 2, 3, 4, 5]}))
    view.shortcut_paste()
    # check
    # failed because paste only the first item which is a string into float fields
    assert main_view.message_view.message != ""
    assert model.points_query.count() == 6
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0
    assert model.points_query.get_name(3) == "point 4"
    assert model.points_query.get_x(3) == 10.0
    assert model.points_query.get_y(3) == 11.0
    assert model.points_query.get_z(3) == 12.0
    assert model.points_query.get_name(4) == "point 5"
    assert model.points_query.get_x(4) == 13.0
    assert model.points_query.get_y(4) == 14.0
    assert model.points_query.get_z(4) == 15.0
    assert model.points_query.get_name(5) == "point 6"
    assert model.points_query.get_x(5) == 16.0
    assert model.points_query.get_y(5) == 17.0
    assert model.points_query.get_z(5) == 18.0


def test_copy_one_item_paste_no_selection(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, main_view, model = app_points
    assert main_view.message_view.message == ""
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict())
    view.shortcut_paste()
    # check
    assert main_view.message_view.message != ""
    assert main_view.message_view.message_type == MessageViewType.critical
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0


def test_copy_one_row_paste_no_selection(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [0, 1]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict())
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 4
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 4.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0
    assert model.points_query.get_name(3) == "point 1"
    assert model.points_query.get_x(3) == 1.0
    assert model.points_query.get_y(3) == 0.0
    assert model.points_query.get_z(3) == 0.0


def test_copy_unstructured_data_paste_coincident(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2], 1: [1]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({1: [1, 2], 2: [1, 2]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 1.0
    assert model.points_query.get_y(1) == 2.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 4.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0


def test_copy_unstructured_data_paste_not_coincident(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2], 1: [1]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({1: [1], 2: [1, 2]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 1.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 1.0
    assert model.points_query.get_y(2) == 1.0
    assert model.points_query.get_z(2) == 9.0


def test_copy_one_row_paste_one_greater_selected_row(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({1: [1, 2, 3]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 1.0
    assert model.points_query.get_y(1) == 2.0
    assert model.points_query.get_z(1) == 6.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0


def test_copy_one_row_paste_one_selected_unstructured_row_same_size(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({1: [1, 3]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 1.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 2.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0


def test_copy_one_row_paste_one_selected_unstructured_row_not_same_size(
    app_points: Tuple[TableView[PointsItems], ExampleMainView, Model],
) -> None:
    """Test copy/paste."""
    view, _, model = app_points
    assert view.items is not None
    # set up
    model.points_query.insert(0, "point 1", 1.0, 2.0, 3.0)
    model.points_query.insert(1, "point 2", 4.0, 5.0, 6.0)
    model.points_query.insert(2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.items.set_selected_row_items(OrderedDict({0: [1, 2, 3]}))
    view.shortcut_copy()
    # paste
    view.items.set_selected_row_items(OrderedDict({1: [1, 3]}))
    view.shortcut_paste()
    # check
    assert model.points_query.count() == 3
    assert model.points_query.get_name(0) == "point 1"
    assert model.points_query.get_x(0) == 1.0
    assert model.points_query.get_y(0) == 2.0
    assert model.points_query.get_z(0) == 3.0
    assert model.points_query.get_name(1) == "point 2"
    assert model.points_query.get_x(1) == 1.0
    assert model.points_query.get_y(1) == 5.0
    assert model.points_query.get_z(1) == 1.0
    assert model.points_query.get_name(2) == "point 3"
    assert model.points_query.get_x(2) == 7.0
    assert model.points_query.get_y(2) == 8.0
    assert model.points_query.get_z(2) == 9.0
