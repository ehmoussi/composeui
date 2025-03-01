from composeui.items.linkedtable.ilinkedtableview import LinkedTableView
from composeui.items.tree.itreeview import ExportTreeOptions
from examples.linkedtableview.sqlite.app import LinkedTableViewApp, Model
from examples.linkedtableview.sqlite.example import ExampleMainView
from examples.linkedtableview.sqlite.lines import LinesItems, PointsItems

import pytest

import sys
from pathlib import Path
from typing import Tuple
from unittest.mock import patch


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


@pytest.fixture()
def model(
    app_lines: Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model],
) -> Model:
    return app_lines[2]


@pytest.fixture()
def main_view(
    app_lines: Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model],
) -> ExampleMainView:
    return app_lines[1]


@pytest.fixture()
def linked_table(
    app_lines: Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model],
) -> LinkedTableView[LinesItems, PointsItems]:
    return app_lines[0]


@pytest.fixture()
def lines_items(
    app_lines: Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model],
) -> LinesItems:
    assert app_lines[0].master_table.items is not None
    return app_lines[0].master_table.items


@pytest.fixture()
def points_items(
    app_lines: Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model],
) -> PointsItems:
    assert app_lines[0].detail_table.items is not None
    return app_lines[0].detail_table.items


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


def test_remove_point(
    app_lines: Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model],
) -> None:
    linked_table, *_ = app_lines
    assert linked_table.master_table.items is not None
    assert linked_table.detail_table.items is not None
    linked_table.master_table.items.set_selected_rows([1])
    assert linked_table.detail_table.items.get_data(0, 0) == "point 1"
    assert linked_table.detail_table.items.get_data(1, 0) == "point 2"
    assert linked_table.detail_table.items.get_data(2, 0) == "point 3"
    assert linked_table.detail_table.items.get_data(3, 0) == "point 4"
    linked_table.detail_table.items.set_selected_rows([1, 3])
    linked_table.detail_table.remove_clicked()
    assert linked_table.detail_table.items.get_nb_rows() == 2
    assert linked_table.detail_table.items.get_data(0, 0) == "point 1"
    assert linked_table.detail_table.items.get_data(1, 0) == "point 3"


def test_add_point(
    app_lines: Tuple[LinkedTableView[LinesItems, PointsItems], ExampleMainView, Model],
) -> None:
    linked_table, *_ = app_lines
    assert linked_table.master_table.items is not None
    assert linked_table.detail_table.items is not None
    linked_table.master_table.items.set_selected_rows([1])
    assert linked_table.detail_table.items.get_data(0, 0) == "point 1"
    assert linked_table.detail_table.items.get_data(1, 0) == "point 2"
    assert linked_table.detail_table.items.get_data(2, 0) == "point 3"
    assert linked_table.detail_table.items.get_data(3, 0) == "point 4"
    linked_table.detail_table.items.set_selected_rows([1])
    linked_table.detail_table.add_clicked()
    assert linked_table.detail_table.items.get_nb_rows() == 5
    assert linked_table.detail_table.items.get_data(0, 0) == "point 1"
    assert linked_table.detail_table.items.get_data(1, 0) == "point 2"
    assert linked_table.detail_table.items.get_data(2, 0) == "point 5"
    assert linked_table.detail_table.items.get_data(3, 0) == "point 3"
    assert linked_table.detail_table.items.get_data(4, 0) == "point 4"


def test_import_empty_file(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    tmpdir: Path,
    main_view: ExampleMainView,
) -> None:
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    filepath = Path(tmpdir, "bad_file.csv")
    filepath.write_text("")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    linked_table.import_clicked()
    main_view.progress_popup_view.finished()
    assert "Unable to read" in str(main_view.message_view.message)


def test_import_bad_file(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    tmpdir: Path,
    main_view: ExampleMainView,
) -> None:
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    filepath = Path(tmpdir, "bad_file.csv")
    filepath.write_text("bad data")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    linked_table.import_clicked()
    main_view.progress_popup_view.finished()
    assert "The parsing of the file failed" in str(main_view.message_view.message)


def test_bad_implementation_items_exported_column_indices_empty(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    lines_items: LinesItems,
    main_view: ExampleMainView,
) -> None:
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    filepath = Path("tests/test_linkedtableview_sqlite/data/lines.csv")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    # change the method to return an empty list to emulate the error
    lines_items.get_exported_column_indices = list  # type: ignore[method-assign]
    linked_table.import_clicked()
    main_view.progress_popup_view.finished()
    assert (
        main_view.message_view.message
        == "The exported column indices of the master table is empty"
    )


def test_bad_implementation_items_exported_column_indices_bad_index_negative(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    lines_items: LinesItems,
    main_view: ExampleMainView,
) -> None:
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    filepath = Path("tests/test_linkedtableview_sqlite/data/lines.csv")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    # change the method to return an empty list to emulate the error
    lines_items.get_exported_column_indices = lambda: [-1]  # type: ignore[method-assign]
    linked_table.import_clicked()
    main_view.progress_popup_view.finished()
    assert "has an index < 0" in main_view.message_view.message


def test_bad_implementation_items_exported_column_indices_bad_index_too_big(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    lines_items: LinesItems,
    main_view: ExampleMainView,
) -> None:
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    filepath = Path("tests/test_linkedtableview_sqlite/data/lines.csv")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    # change the method to return an empty list to emulate the error
    lines_items.get_exported_column_indices = lambda: [100]  # type: ignore[method-assign]
    linked_table.import_clicked()
    main_view.progress_popup_view.finished()
    assert "has an index greater" in main_view.message_view.message


def test_import(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    lines_items: LinesItems,
    points_items: PointsItems,
    main_view: ExampleMainView,
) -> None:
    # set up
    main_view.message_view.run = lambda: False  # type: ignore[method-assign]
    filepath = Path("tests/test_linkedtableview_sqlite/data/lines.csv")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    # import file
    linked_table.import_clicked()
    main_view.progress_popup_view.finished()
    # check the import data
    assert lines_items.get_nb_rows() == 4
    assert lines_items.get_data(0, 0) == "line 1"
    assert lines_items.get_data(1, 0) == "line 2"
    assert lines_items.get_data(2, 0) == "line 2"
    assert lines_items.get_data(3, 0) == "line 3"
    lines_items.set_selected_rows([0])
    assert points_items.get_nb_rows() == 0
    lines_items.set_selected_rows([1])
    assert points_items.get_nb_rows() == 4
    lines_items.set_selected_rows([2])
    assert points_items.get_nb_rows() == 3
    lines_items.set_selected_rows([3])
    assert points_items.get_nb_rows() == 1


def test_import_and_remove_all(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    lines_items: LinesItems,
    points_items: PointsItems,
    main_view: ExampleMainView,
) -> None:
    # set up
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    filepath = Path("tests/test_linkedtableview_sqlite/data/lines.csv")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    # import file
    linked_table.import_clicked()
    main_view.progress_popup_view.finished()
    # check the import data
    assert lines_items.get_nb_rows() == 2
    assert lines_items.get_data(0, 0) == "line 2"
    assert lines_items.get_data(1, 0) == "line 3"
    lines_items.set_selected_rows([0])
    assert points_items.get_nb_rows() == 3
    lines_items.set_selected_rows([1])
    assert points_items.get_nb_rows() == 1


def test_import_and_remove_all_with_two_columns_for_master(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    lines_items: LinesItems,
    points_items: PointsItems,
    main_view: ExampleMainView,
) -> None:
    # set up
    lines_items.get_exported_column_indices = lambda: [0, 1]  # type: ignore[method-assign]
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    filepath = Path("tests/test_linkedtableview_sqlite/data/lines_id.csv")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    # import file
    linked_table.import_clicked()
    main_view.progress_popup_view.finished()
    # check the import data
    assert lines_items.get_nb_rows() == 2
    assert lines_items.get_data(0, 0) == "line 2"
    assert lines_items.get_data(1, 0) == "line 3"
    lines_items.set_selected_rows([0])
    assert points_items.get_nb_rows() == 3
    lines_items.set_selected_rows([1])
    assert points_items.get_nb_rows() == 1
    assert "Failed to set" in main_view.message_view.message


def test_import_and_remove_all_with_missing_detail_columns(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    lines_items: LinesItems,
    points_items: PointsItems,
    main_view: ExampleMainView,
) -> None:
    # set up
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    filepath = Path("tests/test_linkedtableview_sqlite/data/lines_missing_columns.csv")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    # import file
    linked_table.import_clicked()
    main_view.progress_popup_view.finished()
    # check the import data
    assert lines_items.get_nb_rows() == 2
    assert lines_items.get_data(0, 0) == "line 2"
    assert lines_items.get_data(1, 0) == "line 3"
    lines_items.set_selected_rows([0])
    assert points_items.get_nb_rows() == 3
    lines_items.set_selected_rows([1])
    assert points_items.get_nb_rows() == 1
    assert "Missing 1 column(s)" in main_view.message_view.message


def test_import_and_remove_all_with_bad_data_detail_column(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    lines_items: LinesItems,
    points_items: PointsItems,
    main_view: ExampleMainView,
) -> None:
    # set up
    main_view.message_view.run = lambda: True  # type: ignore[method-assign]
    filepath = Path("tests/test_linkedtableview_sqlite/data/lines_bad_data_detail_table.csv")
    main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
    # import file
    linked_table.import_clicked()
    main_view.progress_popup_view.finished()
    # check the import data
    assert lines_items.get_nb_rows() == 2
    assert lines_items.get_data(0, 0) == "line 2"
    assert lines_items.get_data(1, 0) == "line 3"
    lines_items.set_selected_rows([0])
    assert points_items.get_nb_rows() == 3
    lines_items.set_selected_rows([1])
    assert points_items.get_nb_rows() == 1
    assert "Failed to set 'zzz'" in main_view.message_view.message


def test_export(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    main_view: ExampleMainView,
    tmpdir: Path,
) -> None:
    # set up: choose the filepath
    filepath = Path(tmpdir, "test.csv")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    assert filepath.exists() is False
    # choose to not export only the selection
    main_view.message_view.run = lambda: False  # type: ignore[method-assign]
    # export
    linked_table.export_clicked()
    main_view.progress_popup_view.finished()
    assert filepath.exists() is True
    assert filepath.read_text() == (
        "Name;Name.1;X;Y;Z\n"
        "line 2;point 1;0.0;0.0;0.0\n"
        "line 2;point 2;0.0;0.0;0.0\n"
        "line 2;point 3;0.0;0.0;0.0\n"
        "line 2;point 4;0.0;0.0;0.0\n"
    )


def test_export_empty_table(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    lines_items: LinesItems,
    main_view: ExampleMainView,
    tmpdir: Path,
) -> None:
    # set up:
    # - clean the table
    lines_items.remove_all()
    assert lines_items.get_nb_rows() == 0
    # - choose the filepath
    filepath = Path(tmpdir, "test.csv")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    assert filepath.exists() is False
    # export
    linked_table.export_clicked()
    main_view.progress_popup_view.finished()
    # check error message
    assert main_view.message_view.message == "Can't export empty tables"


def test_export_permission_error(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    main_view: ExampleMainView,
    tmpdir: Path,
) -> None:
    # set up: choose the filepath
    filepath = Path(tmpdir, "test.csv")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    assert filepath.exists() is False
    # change to export all to avoid the asking if exporting only the selection
    linked_table.export_options = ExportTreeOptions.EXPORT_ALL
    # export
    with patch("builtins.open", side_effect=PermissionError("Permission Denied")):
        linked_table.export_clicked()
        main_view.progress_popup_view.finished()
    assert filepath.exists() is False
    # check error message
    assert "already open elsewhere" in main_view.message_view.message


@pytest.mark.parametrize(
    ("extension", "use_parent_sheet_names"),
    [(".xlsx", True), (".xlsx", False), (".xls", True), (".xls", False), (".json", False)],
)
def test_import_export_excel_json(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    lines_items: LinesItems,
    points_items: PointsItems,
    main_view: ExampleMainView,
    tmp_path: Path,
    extension: str,
    use_parent_sheet_names: bool,
) -> None:
    assert lines_items.get_nb_rows() == 2
    if not use_parent_sheet_names:
        # remove the option
        linked_table.export_options ^= ExportTreeOptions.USE_PARENT_SHEET_NAMES
    # export in the tmp dir
    filepath = Path(tmp_path, f"test_export{extension}")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    linked_table.export_clicked()
    main_view.progress_popup_view.finished()
    if sys.version_info[:2] <= (3, 8) and extension == ".json":
        assert "version of pandas" in main_view.message_view.message
    else:
        assert main_view.message_view.message == ""
        # clean the tree
        lines_items.remove_all()
        assert lines_items.get_nb_rows() == 0
        # import the exported file
        main_view.file_view.open_file = lambda: str(filepath)  # type: ignore[method-assign]
        linked_table.import_clicked()
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
            assert lines_items.get_nb_rows() == 1
            lines_items.set_selected_rows([0])
            assert points_items.get_nb_rows() == 4
            for i in range(4):
                assert points_items.get_data(i, 0) == f"point {i + 1}"


@pytest.mark.parametrize("extension", [".md", ".html"])
def test_export_markdown_html(
    linked_table: LinkedTableView[LinesItems, PointsItems],
    main_view: ExampleMainView,
    tmp_path: Path,
    extension: str,
) -> None:
    # export in the tmp dir
    filepath = Path(tmp_path, f"test_export{extension}")
    main_view.file_view.save_file = lambda: str(filepath)  # type: ignore[method-assign]
    linked_table.export_clicked()
    main_view.progress_popup_view.finished()
    assert main_view.message_view.message == ""
    assert filepath.exists()
    # check if the files are the same
    filepath_ref = Path("tests/test_linkedtableview_sqlite/data", f"test_correct{extension}")
    assert filepath.read_text() == filepath_ref.read_text()
