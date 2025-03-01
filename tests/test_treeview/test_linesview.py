from composeui.items.tree.treeview import ExportTreeOptions, TreeView
from examples.treeview.app import Model, TreeViewApp
from examples.treeview.example import ExampleMainView
from examples.treeview.lines import LinesItems

import pytest
from typing_extensions import OrderedDict

import sys
from pathlib import Path
from typing import Tuple

DATA_DIRPATH = Path("tests", "test_treeview", "data")


@pytest.fixture()
def app_lines(
    app: TreeViewApp,
) -> Tuple[TreeView[LinesItems], ExampleMainView, Model]:
    return (app.main_view.lines_view, app.main_view, app.model)


def test_add_remove(app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model]) -> None:
    view, _, model = app_lines
    assert view.items is not None
    view.add_clicked()
    # clear the selection otherwise the next item is a point of the current line created
    view.items.clear_selection()
    view.add_clicked()
    view.items.clear_selection()
    view.add_clicked()
    view.items.clear_selection()
    view.add_clicked()
    assert model.lines_query.count_lines() == 4
    view.items.set_selected_positions([(0,), (3,)])
    view.remove_clicked()
    assert model.lines_query.count_lines() == 2
    assert view.items.get_selected_positions() == [(0,)]


def test_add_point(app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model]) -> None:
    view, _, model = app_lines
    assert view.items is not None
    view.add_clicked()
    view.items.clear_selection()
    view.add_clicked()
    view.items.set_selected_positions([(1,)])  # select the second line
    # add 3 points to the second line
    view.add_clicked()
    view.add_clicked()
    view.add_clicked()
    assert view.items.get_nb_rows((1,)) == 3
    assert view.items.get_data(0, 0, (1,)) == "point 1"
    assert view.items.get_data(1, 0, (1,)) == "point 2"
    assert view.items.get_data(2, 0, (1,)) == "point 3"
    # add a point after the point 2
    view.items.set_selected_positions([(1, 0)])
    view.add_clicked()
    assert view.items.get_nb_rows((1,)) == 4
    assert view.items.get_data(0, 0, (1,)) == "point 1"
    assert view.items.get_data(1, 0, (1,)) == "point 4"
    assert view.items.get_data(2, 0, (1,)) == "point 2"
    assert view.items.get_data(3, 0, (1,)) == "point 3"


def test_import(app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model]) -> None:
    view, main_view, _ = app_lines
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
    assert view.items.get_nb_rows() == 2
    assert view.items.get_nb_rows((0,)) == 7
    assert view.items.get_nb_rows((1,)) == 7
    for i in range(2):
        assert view.items.get_edit_data(i, 0) == f"line {i+1}"
        for j in range(7):
            assert view.items.get_edit_data(j, 0, (i,)) == f"point {i * 7 + j + 1}"


def test_import_without_cleaning(
    app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    view, main_view, _ = app_lines
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
    assert view.items.get_nb_rows() == 4
    assert view.items.get_nb_rows((0,)) == 0
    assert view.items.get_nb_rows((1,)) == 0
    assert view.items.get_nb_rows((2,)) == 7
    assert view.items.get_nb_rows((3,)) == 7
    for k, i in enumerate(range(2, 4)):
        assert view.items.get_edit_data(i, 0) == f"line {k+1}"
        for j in range(7):
            assert view.items.get_edit_data(j, 0, (i,)) == f"point {k * 7 + j + 1}"


def test_import_missing_column(
    app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    view, main_view, _ = app_lines
    csv_filepath = Path(DATA_DIRPATH, "test_missing_column.csv")
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
    assert main_view.progress_popup_view.tasks[0].error_message != ""
    assert view.items.get_nb_rows() == 2


def test_export(
    app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model],
    tmp_path: Path,
) -> None:
    view, main_view, _ = app_lines
    assert view.items is not None
    # Add the datas same as the file test_correct.csv
    for i in range(2):
        view.items.insert(i)
        for j in range(7):
            view.items.insert(j, (i,))
    # export in the tmp dir
    filepath = Path(tmp_path, "test_export.csv")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    view.export_clicked()
    main_view.progress_popup_view.finished()
    # check if the files are the same
    assert main_view.progress_popup_view.tasks is not None
    assert main_view.progress_popup_view.tasks[0].error_message == ""
    filepath_ref = Path(DATA_DIRPATH, "test_correct.csv")
    assert filepath.read_text() == filepath_ref.read_text()


@pytest.mark.parametrize(
    ("extension", "use_parent_sheet_names"),
    [(".xlsx", True), (".xlsx", False), (".xls", True), (".xls", False), (".json", False)],
)
def test_import_export_excel_json(
    app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model],
    tmp_path: Path,
    extension: str,
    use_parent_sheet_names: bool,
) -> None:
    view, main_view, _ = app_lines
    assert view.items is not None
    if not use_parent_sheet_names:
        # remove the option
        view.export_options ^= ExportTreeOptions.USE_PARENT_SHEET_NAMES
    # Add the datas same as the file test_correct.csv
    for i in range(2):
        view.items.insert(i)
        for j in range(7):
            view.items.insert(j, (i,))
    # export in the tmp dir
    filepath = Path(tmp_path, f"test_export{extension}")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    view.export_clicked()
    main_view.progress_popup_view.finished()
    if sys.version_info[:2] <= (3, 8) and extension == ".json":
        assert "version of pandas" in main_view.message_view.message
    else:
        assert main_view.message_view.message == ""
        # clean the tree
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
            assert view.items.get_nb_rows() == 2
            assert view.items.get_nb_rows((0,)) == 7
            for i in range(2):
                for j in range(7):
                    assert view.items.get_data(j, 0, (i,)) == f"point {7*i + j + 1}"


@pytest.mark.parametrize("extension", [".md", ".html"])
def test_export_markdown_html(
    app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model],
    tmp_path: Path,
    extension: str,
) -> None:
    view, main_view, _ = app_lines
    assert view.items is not None
    # Add the datas same as the file test_correct.csv
    for i in range(2):
        view.items.insert(i)
        for j in range(7):
            view.items.insert(j, (i,))
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


def test_copy_paste_with_failed_insertion(
    app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, main_view, model = app_lines
    assert main_view.message_view.message == ""
    assert view.items is not None
    model.lines_query.insert_line(0, "line 1")
    model.lines_query.insert_point(0, 0, "point 1", 1.0, 2.0, 3.0)
    # copy
    view.selected_items = OrderedDict({(0, 0): [1, 2]})
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict()
    view.shortcut_paste()
    # check: fail because insertion is impossible with a tree
    assert main_view.message_view.message != ""
    assert model.lines_query.count_lines() == 1


def test_copy_paste_with_failed_insertion2(
    app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, main_view, model = app_lines
    assert main_view.message_view.message == ""
    assert view.items is not None
    model.lines_query.insert_line(0, "line 1")
    model.lines_query.insert_point(0, 0, "point 1", 1.0, 2.0, 3.0)
    model.lines_query.insert_point(0, 1, "point 2", 4.0, 5.0, 6.0)
    model.lines_query.insert_point(0, 2, "point 3", 7.0, 8.0, 9.0)
    # copy
    view.selected_items = OrderedDict({(0, 0): [1, 2], (0, 1): [1, 2]})
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict()
    view.shortcut_paste()
    # check: fail because insertion is impossible with a tree
    assert main_view.message_view.message != ""
    assert model.lines_query.count_lines() == 1
    main_view.message_view.message = ""


@pytest.fixture()
def app_lines_with_data(
    app_lines: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> Tuple[TreeView[LinesItems], ExampleMainView, Model]:
    """Add data to the app."""
    view, main_view, model = app_lines
    model.lines_query.insert_line(0, "line 1")
    model.lines_query.insert_point(0, 0, "point 1", 1.0, 2.0, 3.0)
    model.lines_query.insert_point(0, 1, "point 2", 4.0, 5.0, 6.0)
    model.lines_query.insert_point(0, 2, "point 3", 7.0, 8.0, 9.0)
    model.lines_query.insert_point(0, 3, "point 4", 10.0, 11.0, 12.0)
    model.lines_query.insert_line(1, "line 2")
    model.lines_query.insert_point(1, 0, "point 5", 13.0, 14.0, 15.0)
    model.lines_query.insert_point(1, 1, "point 6", 16.0, 17.0, 18.0)
    model.lines_query.insert_point(1, 2, "point 7", 19.0, 20.0, 21.0)
    model.lines_query.insert_point(1, 3, "point 8", 22.0, 23.0, 24.0)
    return view, main_view, model


def test_copy_from_one_parent_to_another(
    app_lines_with_data: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, _, model = app_lines_with_data
    # copy
    view.selected_items = OrderedDict(
        {
            (1, 0): [0, 1, 2, 3],
            (1, 1): [0, 1, 2, 3],
            (1, 2): [0, 1, 2, 3],
            (1, 3): [0, 1, 2, 3],
        }
    )
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict(
        {
            (0, 0): [0, 1, 2, 3],
            (0, 1): [0, 1, 2, 3],
            (0, 2): [0, 1, 2, 3],
            (0, 3): [0, 1, 2, 3],
        }
    )
    view.shortcut_paste()
    # check
    assert model.lines_query.count_lines() == 2
    assert model.lines_query.count_points(0) == 4
    assert model.lines_query.count_points(1) == 4
    assert model.lines_query.get_point(0, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(0, 1) == ("point 6", 16.0, 17.0, 18.0)
    assert model.lines_query.get_point(0, 2) == ("point 7", 19.0, 20.0, 21.0)
    assert model.lines_query.get_point(0, 3) == ("point 8", 22.0, 23.0, 24.0)
    assert model.lines_query.get_point(1, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(1, 1) == ("point 6", 16.0, 17.0, 18.0)
    assert model.lines_query.get_point(1, 2) == ("point 7", 19.0, 20.0, 21.0)
    assert model.lines_query.get_point(1, 3) == ("point 8", 22.0, 23.0, 24.0)


def test_copy_paste_with_insertion(
    app_lines_with_data: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, _, model = app_lines_with_data
    # copy
    view.selected_items = OrderedDict(
        {
            (1,): [0],
            (1, 0): [0, 1],
            (1, 1): [0, 1],
            (1, 2): [0, 1],
            (1, 3): [0, 1],
        }
    )
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict(
        {
            (0, 0): [1, 2],
            (0, 1): [1, 2],
            (0, 2): [1, 2],
            (0, 3): [1, 2],
        }
    )
    view.shortcut_paste()
    # check
    assert model.lines_query.count_lines() == 2
    assert model.lines_query.count_points(0) == 5
    assert model.lines_query.count_points(1) == 4
    assert model.lines_query.get_point(0, 0) == ("point 1", 1.0, 2.0, 3.0)
    assert model.lines_query.get_point(0, 1) == ("point 2", 4.0, 13.0, 6.0)
    assert model.lines_query.get_point(0, 2) == ("point 3", 7.0, 16.0, 9.0)
    assert model.lines_query.get_point(0, 3) == ("point 4", 10.0, 19.0, 12.0)
    assert model.lines_query.get_point(0, 4) == ("point 9", 0.0, 22.0, 0.0)
    assert model.lines_query.get_point(1, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(1, 1) == ("point 6", 16.0, 17.0, 18.0)
    assert model.lines_query.get_point(1, 2) == ("point 7", 19.0, 20.0, 21.0)
    assert model.lines_query.get_point(1, 3) == ("point 8", 22.0, 23.0, 24.0)


def test_copy_one_item_paste_one_item(
    app_lines_with_data: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, _, model = app_lines_with_data
    # copy
    view.selected_items = OrderedDict({(0, 1): [1]})
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict({(1, 3): [3]})
    view.shortcut_paste()
    # check
    assert model.lines_query.count_lines() == 2
    assert model.lines_query.count_points(0) == 4
    assert model.lines_query.count_points(1) == 4
    assert model.lines_query.get_point(0, 0) == ("point 1", 1.0, 2.0, 3.0)
    assert model.lines_query.get_point(0, 1) == ("point 2", 4.0, 5.0, 6.0)
    assert model.lines_query.get_point(0, 2) == ("point 3", 7.0, 8.0, 9.0)
    assert model.lines_query.get_point(0, 3) == ("point 4", 10.0, 11.0, 12.0)
    assert model.lines_query.get_point(1, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(1, 1) == ("point 6", 16.0, 17.0, 18.0)
    assert model.lines_query.get_point(1, 2) == ("point 7", 19.0, 20.0, 21.0)
    assert model.lines_query.get_point(1, 3) == ("point 8", 22.0, 23.0, 4.0)


def test_copy_one_row_paste_one_row(
    app_lines_with_data: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, _, model = app_lines_with_data
    # copy
    view.selected_items = OrderedDict({(0, 1): [0, 1, 2]})
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict({(1, 3): [1, 2, 3]})
    view.shortcut_paste()
    # check
    assert model.lines_query.count_lines() == 2
    assert model.lines_query.count_points(0) == 4
    assert model.lines_query.count_points(1) == 4
    assert model.lines_query.get_point(0, 0) == ("point 1", 1.0, 2.0, 3.0)
    assert model.lines_query.get_point(0, 1) == ("point 2", 4.0, 5.0, 6.0)
    assert model.lines_query.get_point(0, 2) == ("point 3", 7.0, 8.0, 9.0)
    assert model.lines_query.get_point(0, 3) == ("point 4", 10.0, 11.0, 12.0)
    assert model.lines_query.get_point(1, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(1, 1) == ("point 6", 16.0, 17.0, 18.0)
    assert model.lines_query.get_point(1, 2) == ("point 7", 19.0, 20.0, 21.0)
    assert model.lines_query.get_point(1, 3) == ("point 8", 22.0, 4.0, 5.0)


def test_copy_one_row_paste_multiple_rows(
    app_lines_with_data: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, _, model = app_lines_with_data
    # copy
    view.selected_items = OrderedDict({(0, 1): [0, 1]})
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict({(1, 1): [1, 2, 3], (1, 3): [1, 2, 3]})
    view.shortcut_paste()
    # check
    assert model.lines_query.count_lines() == 2
    assert model.lines_query.count_points(0) == 4
    assert model.lines_query.count_points(1) == 4
    assert model.lines_query.get_point(0, 0) == ("point 1", 1.0, 2.0, 3.0)
    assert model.lines_query.get_point(0, 1) == ("point 2", 4.0, 5.0, 6.0)
    assert model.lines_query.get_point(0, 2) == ("point 3", 7.0, 8.0, 9.0)
    assert model.lines_query.get_point(0, 3) == ("point 4", 10.0, 11.0, 12.0)
    assert model.lines_query.get_point(1, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(1, 1) == ("point 6", 16.0, 4.0, 18.0)
    assert model.lines_query.get_point(1, 2) == ("point 7", 19.0, 20.0, 21.0)
    assert model.lines_query.get_point(1, 3) == ("point 8", 22.0, 4.0, 24.0)


def test_copy_one_row_paste_unstructured_selection(
    app_lines_with_data: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, _, model = app_lines_with_data
    # copy
    view.selected_items = OrderedDict({(0, 1): [1, 2, 3]})
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict({(1, 2): [1], (1, 3): [2, 3]})
    view.shortcut_paste()
    # check
    assert model.lines_query.count_lines() == 2
    assert model.lines_query.count_points(0) == 4
    assert model.lines_query.count_points(1) == 4
    assert model.lines_query.get_point(0, 0) == ("point 1", 1.0, 2.0, 3.0)
    assert model.lines_query.get_point(0, 1) == ("point 2", 4.0, 5.0, 6.0)
    assert model.lines_query.get_point(0, 2) == ("point 3", 7.0, 8.0, 9.0)
    assert model.lines_query.get_point(0, 3) == ("point 4", 10.0, 11.0, 12.0)
    assert model.lines_query.get_point(1, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(1, 1) == ("point 6", 16.0, 17.0, 18.0)
    assert model.lines_query.get_point(1, 2) == ("point 7", 4.0, 20.0, 21.0)
    assert model.lines_query.get_point(1, 3) == ("point 8", 22.0, 4.0, 4.0)


def test_copy_one_row_paste_unstructured_selection_same_shape(
    app_lines_with_data: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, _, model = app_lines_with_data
    # copy
    view.selected_items = OrderedDict({(0, 1): [0, 2]})
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict({(1, 3): [1, 3]})
    view.shortcut_paste()
    # check
    assert model.lines_query.count_lines() == 2
    assert model.lines_query.count_points(0) == 4
    assert model.lines_query.count_points(1) == 4
    assert model.lines_query.get_point(0, 0) == ("point 1", 1.0, 2.0, 3.0)
    assert model.lines_query.get_point(0, 1) == ("point 2", 4.0, 5.0, 6.0)
    assert model.lines_query.get_point(0, 2) == ("point 3", 7.0, 8.0, 9.0)
    assert model.lines_query.get_point(0, 3) == ("point 4", 10.0, 11.0, 12.0)
    assert model.lines_query.get_point(1, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(1, 1) == ("point 6", 16.0, 17.0, 18.0)
    assert model.lines_query.get_point(1, 2) == ("point 7", 19.0, 20.0, 21.0)
    assert model.lines_query.get_point(1, 3) == ("point 8", 22.0, 23.0, 5.0)


def test_copy_block_to_one_item_selected(
    app_lines_with_data: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, _, model = app_lines_with_data
    # copy
    view.selected_items = OrderedDict(
        {
            (0, 1): [0, 1, 2],
            (0, 2): [0, 1, 2],
            (0, 3): [0, 1, 2],
        }
    )
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict({(1, 2): [1]})
    view.shortcut_paste()
    # check
    assert model.lines_query.count_lines() == 2
    assert model.lines_query.count_points(0) == 4
    assert model.lines_query.count_points(1) == 5
    assert model.lines_query.get_point(0, 0) == ("point 1", 1.0, 2.0, 3.0)
    assert model.lines_query.get_point(0, 1) == ("point 2", 4.0, 5.0, 6.0)
    assert model.lines_query.get_point(0, 2) == ("point 3", 7.0, 8.0, 9.0)
    assert model.lines_query.get_point(0, 3) == ("point 4", 10.0, 11.0, 12.0)
    assert model.lines_query.get_point(1, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(1, 1) == ("point 6", 16.0, 17.0, 18.0)
    assert model.lines_query.get_point(1, 2) == ("point 7", 19.0, 4.0, 5.0)
    assert model.lines_query.get_point(1, 3) == ("point 8", 22.0, 7.0, 8.0)
    assert model.lines_query.get_point(1, 4) == ("point 9", 0.0, 10.0, 11.0)


def test_copy_unstructured_data_to_structured_selection(
    app_lines_with_data: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, _, model = app_lines_with_data
    # copy
    view.selected_items = OrderedDict(
        {
            (0, 1): [1],
            (0, 2): [1, 2],
        }
    )
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict({(1, 2): [1, 3], (1, 3): [1, 3]})
    view.shortcut_paste()
    # check
    assert model.lines_query.count_lines() == 2
    assert model.lines_query.count_points(0) == 4
    assert model.lines_query.count_points(1) == 4
    assert model.lines_query.get_point(0, 0) == ("point 1", 1.0, 2.0, 3.0)
    assert model.lines_query.get_point(0, 1) == ("point 2", 4.0, 5.0, 6.0)
    assert model.lines_query.get_point(0, 2) == ("point 3", 7.0, 8.0, 9.0)
    assert model.lines_query.get_point(0, 3) == ("point 4", 10.0, 11.0, 12.0)
    assert model.lines_query.get_point(1, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(1, 1) == ("point 6", 16.0, 17.0, 18.0)
    assert model.lines_query.get_point(1, 2) == ("point 7", 4.0, 20.0, 4.0)
    assert model.lines_query.get_point(1, 3) == ("point 8", 4.0, 23.0, 4.0)


def test_copy_unstructured_data_to_unstructured_selection_with_same_shape(
    app_lines_with_data: Tuple[TreeView[LinesItems], ExampleMainView, Model],
) -> None:
    # set up
    view, _, model = app_lines_with_data
    # copy
    view.selected_items = OrderedDict(
        {
            (0, 1): [1],
            (0, 2): [1, 2],
        }
    )
    view.shortcut_copy()
    # paste
    view.selected_items = OrderedDict(
        {
            (1, 2): [1],
            (1, 3): [1, 2],
        }
    )
    view.shortcut_paste()
    # check
    assert model.lines_query.count_lines() == 2
    assert model.lines_query.count_points(0) == 4
    assert model.lines_query.count_points(1) == 4
    assert model.lines_query.get_point(0, 0) == ("point 1", 1.0, 2.0, 3.0)
    assert model.lines_query.get_point(0, 1) == ("point 2", 4.0, 5.0, 6.0)
    assert model.lines_query.get_point(0, 2) == ("point 3", 7.0, 8.0, 9.0)
    assert model.lines_query.get_point(0, 3) == ("point 4", 10.0, 11.0, 12.0)
    assert model.lines_query.get_point(1, 0) == ("point 5", 13.0, 14.0, 15.0)
    assert model.lines_query.get_point(1, 1) == ("point 6", 16.0, 17.0, 18.0)
    assert model.lines_query.get_point(1, 2) == ("point 7", 4.0, 20.0, 21.0)
    assert model.lines_query.get_point(1, 3) == ("point 8", 7.0, 8.0, 24.0)
