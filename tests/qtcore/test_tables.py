"""Tests of the Qt tables and their filter bars."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Optional

import pytest
from qtpy.QtCore import QModelIndex, QPoint, Qt
from qtpy.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QShortcut,
)
from qtpy.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QWidget,
)
from typing_extensions import override

from composeui.core._views.tables import SOURCE_TABLE_WINDOW
from composeui.core.application import _add_reference_to_signals
from composeui.core.registry import RendererType
from composeui.core.renderer import RendererContainer
from composeui.core.view import (
    SOURCE_TABLE_JOB_ROWS,
    CellStyle,
    CellWidget,
    EditRefusedError,
    HeaderGroup,
    ListSource,
    SelectionMode,
    SourceTableView,
    T,
    TableView,
    replace_cell,
)
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.renderers import RENDERERS as QT_RENDERERS
from composeui.qtcore.widgets.qfiltertable import QFilterTable
from composeui.qtcore.widgets.qformlabel import QFormLabel
from composeui.qtcore.widgets.qsourcetable import QDataFilterTable
from composeui.qtcore.widgets.qtexttable import QCheckHeader, QTextTableView
from examples.pipeform import PipeMainView
from examples.studyinputs import OUTPUT_FOLDER, PATH, StudyInputsMainView
from tests.horizontal import HorizontalMainView
from tests.studyfiles import StudyFilesTableMainView, StudyPathsMainView
from tests.tables import (
    CellWidgetsMainView,
    DataFilesTableMainView,
    EditableTableMainView,
    GatedMainView,
    GatedSource,
    MillionRowsMainView,
    MillionSource,
    Room,
    RoomsDataMainView,
    SortedRoomsMainView,
    StyledTablesMainView,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.core.view import Filter, Sort

from tests.qtcore.support import _field_widget, _late_pages_window, _table, _widget


def test_the_summary_table_shows_each_edit_and_cannot_be_edited(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    window.resize(900, 1100)
    window.show()
    qtbot.waitExposed(window)
    radius_widget = _field_widget(view.pages.inputs.pipe_form.main_pipe.radius)
    assert isinstance(radius_widget, QLineEdit)

    # typed before the results page is first shown: the table is built with the edit
    radius_widget.setFocus()
    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "35")
    qtbot.keyClick(radius_widget, Qt.Key.Key_Return)
    name_renderer = view.pages.inputs.pipe_form.name.renderer
    assert isinstance(name_renderer, RendererContainer)
    name_label = name_renderer.get_renderer("label")
    assert isinstance(name_label, QtWidgetRenderer)
    assert isinstance(name_label.qt_object, QFormLabel)
    label_left = name_label.qt_object.mapTo(window, QPoint(0, 0)).x()
    view.pages.navigate("results")
    table = _table(view.pages.results.summary)
    model = table.model()
    assert model.headerData(3, Qt.Orientation.Horizontal) == "Half Length"
    cells = [model.index(0, column).data() for column in range(model.columnCount())]
    assert cells == ["Main Pipe", "35", "20", "200"]

    qtbot.waitUntil(table.isVisible)
    # as tall as its rows in the window: no empty block under them
    rows_height = model.rowCount() * table.rowHeight(0)
    assert 0 <= table.viewport().height() - rows_height < table.rowHeight(0)
    # lined up with the form of the other page, whose labels start its rows
    assert table.mapTo(window, QPoint(0, 0)).x() == label_left
    table.setCurrentIndex(model.index(0, 1))
    table.setFocus()
    qtbot.keyClick(table, Qt.Key.Key_F2)  # the edit key
    assert table.state() is not QAbstractItemView.State.EditingState

    view.pages.navigate("inputs")
    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "40")
    qtbot.keyClick(radius_widget, Qt.Key.Key_Return)
    assert model.index(0, 1).data() == "40"  # built already: the table follows each edit


def test_tables_changed_before_their_page_is_built_show_their_order_and_selection(
    qtbot: QtBot,
) -> None:
    view, _ = _late_pages_window(qtbot)
    page = view.router.rooms
    assert page.renderer is None
    page.rooms.records = [Room("Hall", 18), Room("Kitchen", 20.5), Room("Attic", 9)]
    page.rooms.sort_column = 1  # temperature
    page.rooms.sort_descending = True
    page.rooms.search = "t"  # not the hall
    page.rooms.selected_rows = [2]  # the attic, second once ordered
    source = page.readings.source
    assert isinstance(source, GatedSource)
    page.readings.sort_column = "value"
    page.readings.sort_descending = True  # ordered in a job, with no table to show it
    qtbot.waitUntil(lambda: not page.readings.is_ordering)
    source.gate.clear()
    page.readings.sort_descending = False  # still ordering once the page is built

    view.router.navigate("rooms")
    rooms = _table(page.rooms)
    model = rooms.model()
    shown = [model.index(row, 0).data() for row in range(model.rowCount())]
    assert shown == ["Kitchen", "Attic"]
    assert rooms.horizontalHeader().sortIndicatorSection() == 1
    assert rooms.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    assert [index.row() for index in rooms.selectionModel().selectedRows()] == [1]
    box = _widget(page.readings)
    assert isinstance(box, QDataFilterTable)
    readings = box.table.model()
    assert readings.index(0, 0).data() == str(source.size - 1)  # the first job's order
    source.gate.set()
    qtbot.waitUntil(lambda: not page.readings.is_ordering)
    assert readings.index(0, 0).data() == "0"  # the job running as the page was built


def test_clicking_a_table_row_selects_it_and_emits_only_for_the_user(qtbot: QtBot) -> None:
    view = HorizontalMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.tables.narrow)
    emitted: list[list[int]] = []
    view.tables.narrow.selection_changed.connect(emitted.append)

    south = table.visualRect(table.model().index(1, 0)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=south)

    assert view.tables.narrow.selected_rows == [1]
    assert emitted == [[1]]

    # set from code: shown, but not the user's doing
    view.tables.narrow.selected_rows = [2]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [2]
    # new rows still holding it, at the same index then moved: it stays shown
    view.tables.narrow.rows = [["West"], ["South"], ["East"]]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [2]
    view.tables.narrow.rows = [["East"], ["West"]]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [0]
    view.tables.narrow.rows = [["West"]]
    assert table.selectionModel().selectedRows() == []
    assert emitted == [[1]]


def test_each_click_adds_or_removes_its_row_in_a_table_selecting_several(
    qtbot: QtBot,
) -> None:
    view = HorizontalMainView()
    view.tables.narrow.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.tables.narrow)
    emitted: list[list[int]] = []
    view.tables.narrow.selection_changed.connect(emitted.append)

    def click(row: int) -> None:
        center = table.visualRect(table.model().index(row, 0)).center()
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)

    click(2)
    click(0)
    click(2)
    assert view.tables.narrow.selected_rows == [0]
    assert emitted == [[2], [0, 2], [0]]

    # set from code: shown, but not the user's doing
    view.tables.narrow.selected_rows = [1, 2]
    assert sorted(index.row() for index in table.selectionModel().selectedRows()) == [1, 2]
    # back to a single row: a click replaces it
    view.tables.narrow.selection_mode = SelectionMode.SINGLE
    click(0)
    assert view.tables.narrow.selected_rows == [0]
    assert emitted == [[2], [0, 2], [0], [0]]


def test_double_clicking_an_editable_cell_edits_it_keeping_the_selection(qtbot: QtBot) -> None:
    view = EditableTableMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.places)
    model = table.model()
    edited: list[tuple[int, int, str, list[str]]] = []

    def record(row: int, column: int, text: str) -> None:
        # the row as it was: the edit is applied once the callbacks have run, then the row
        # as `cell_edit_applied` finds it
        edited.append((row, column, text, view.places.rows[row]))

    view.places.cell_edited.connect(record)
    view.places.cell_edit_applied.connect(record)

    def edit(row: int, column: int, text: str) -> None:
        center = table.visualRect(model.index(row, column)).center()
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
        qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
        editor = table.focusWidget()
        assert isinstance(editor, QLineEdit)
        editor.selectAll()
        qtbot.keyClicks(editor, text)
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        # Qt commits the text and closes the editor in a queued call
        qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)

    # the harbour's row is short of its note: the edit fills it
    edit(1, 1, "Busy")
    assert view.places.rows == [["Lake", "Calm"], ["Harbour", "Busy"]]
    assert edited == [(1, 1, "Busy", ["Harbour"]), (1, 1, "Busy", ["Harbour", "Busy"])]
    # its row moved nowhere: it stays selected
    assert view.places.selected_rows == [1]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [1]

    def answer(row: int, column: int, text: str) -> None:
        if text == "Windy":  # applied, the rows sorted by note: the lake moves last
            rows = replace_cell(view.places.rows, row, column, text)
            view.places.rows = sorted(rows, key=lambda cells: cells[1])
        elif text == "Foggy":
            raise EditRefusedError

    view.places.cell_edited.connect(answer)
    # the table shows the app's rows, its selection following the edited row
    edit(0, 1, "Windy")
    assert view.places.rows == [["Harbour", "Busy"], ["Lake", "Windy"]]
    assert model.index(1, 1).data() == "Windy"
    assert view.places.selected_rows == [1]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [1]
    # refused: the table shows the old text again, the row still selected
    edit(1, 1, "Foggy")
    assert view.places.rows == [["Harbour", "Busy"], ["Lake", "Windy"]]
    assert model.index(1, 1).data() == "Windy"
    assert [index.row() for index in table.selectionModel().selectedRows()] == [1]

    # the places themselves aren't editable
    center = table.visualRect(model.index(0, 0)).center()
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert table.state() is not QAbstractItemView.State.EditingState
    # each edit, and the one applied again once its row held it
    assert [edit[:3] for edit in edited] == [
        (1, 1, "Busy"),
        (1, 1, "Busy"),
        (0, 1, "Windy"),
        (1, 1, "Foggy"),
    ]


def test_a_double_click_or_enter_activates_a_table_row_unless_it_edits(qtbot: QtBot) -> None:
    view = EditableTableMainView()
    # sorted by place, the harbour shows first: the table emits its index in `rows`
    view.places.sortable_columns = [0]
    view.places.sort_column = 0
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.places)
    model = table.model()
    activated: list[int] = []
    view.places.row_activated.connect(activated.append)

    def double_click(row: int, column: int) -> None:
        # a double click's first press, which Qt's double click handler checks
        center = table.visualRect(model.index(row, column)).center()
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
        qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)

    double_click(0, 0)
    assert activated == [1]
    qtbot.keyClick(table, Qt.Key.Key_Down)
    qtbot.keyClick(table, Qt.Key.Key_Return)
    assert view.places.selected_rows == [0]
    assert activated == [1, 0]

    # a double click on a note edits it instead
    double_click(0, 1)
    assert table.state() is QAbstractItemView.State.EditingState
    assert activated == [1, 0]


def test_picking_a_combobox_cell_s_option_with_the_mouse_edits_it_once(qtbot: QtBot) -> None:
    headers = ["Name", "Role"]
    table = QTextTableView()
    qtbot.addWidget(table)
    table.set_editable_columns([1])
    table.set_cell_widgets({1: CellWidget.combobox(["Input", "Output"])})
    edited: list[tuple[int, int, str]] = []

    def edit(row: int, column: int, text: str) -> None:
        edited.append((row, column, text))
        # answering an edit with new rows, as a view does, resets the model
        table.set_table(headers, [["a", text]])

    table.cell_edited.connect(edit)
    table.set_table(headers, [["a", "Input"]])
    table.show()
    # a click opens the combobox; a click on its popup's option picks it. Qt only logs a
    # commit to a view that no longer has the editor, which fails the test as a warning
    qtbot.mouseClick(
        table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=table.visualRect(table.model().index(0, 1)).center(),
    )
    qtbot.waitUntil(lambda: table.state() is QAbstractItemView.State.EditingState)
    editor = table.viewport().findChild(QComboBox)
    assert editor is not None
    popup = editor.view()
    # shown once the event loop turns (`showPopup` is queued): a click before misses it
    qtbot.waitUntil(popup.isVisible)
    option = popup.visualRect(popup.model().index(1, 0)).center()
    qtbot.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton, pos=option)
    qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)
    assert edited == [(0, 1, "Output")]
    qtbot.waitUntil(lambda: table.viewport().findChild(QComboBox) is None)


def test_a_table_s_cell_widgets_edit_their_cells_or_report_their_clicks(qtbot: QtBot) -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.variables)
    model, header = table.model(), table.horizontalHeader()
    assert isinstance(header, QCheckHeader)
    events: list[tuple[int, ...] | tuple[int, int, str]] = []
    view.variables.cell_edited.connect(lambda row, column, text: events.append((row, column, text)))
    view.variables.cell_clicked.connect(lambda row, column: events.append((row, column)))

    def checks() -> list[Any]:
        return [model.index(row, 0).data(Qt.ItemDataRole.CheckStateRole) for row in range(2)]

    # a check box shows no text; the header's box shows the column's
    assert checks() == [Qt.CheckState.Checked, Qt.CheckState.Unchecked]
    assert model.index(0, 0).data() is None
    icon = model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DecorationRole)
    assert icon is not None
    # Space toggles the current row's box, the header's box following
    table.setCurrentIndex(model.index(1, 0))
    qtbot.keyClick(table, Qt.Key.Key_Space)
    assert view.variables.rows[1][0] == "True"
    assert checks() == [Qt.CheckState.Checked, Qt.CheckState.Checked]
    assert (
        model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DecorationRole) is not icon
    )
    # the header's box unchecks every row, sorting nothing
    box = QPoint(header.sectionViewportPosition(0) + header.box_width() // 2, header.height() // 2)
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=box)
    assert [row[0] for row in view.variables.rows] == ["False", "False"]
    assert checks() == [Qt.CheckState.Unchecked, Qt.CheckState.Unchecked]

    # a click on a role opens a combobox of the roles
    center = table.visualRect(model.index(0, 2)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    qtbot.waitUntil(lambda: table.state() is QAbstractItemView.State.EditingState)
    editor = table.viewport().findChild(QComboBox)
    assert isinstance(editor, QComboBox)
    assert [editor.itemText(item) for item in range(editor.count())] == ["Input", "Output"]
    editor.hidePopup()
    editor.setCurrentIndex(1)
    editor.activated.emit(1)
    qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)
    assert view.variables.rows[0][2] == "Output"

    # a click on a button reports it, not one on its cell's text; a click on a link too
    button = table.visualRect(model.index(1, 3))
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=button.center())
    qtbot.mouseClick(
        table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(button.right() - 4, button.center().y()),
    )
    link = table.visualRect(model.index(0, 4)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=link)
    assert events == [
        (1, 0, "True"),
        (0, 0, "False"),
        (1, 0, "False"),
        (0, 2, "Output"),
        (1, 3),
        (0, 4),
    ]
    # not editable, a role is shown only: no combobox opens
    view.variables.editable_columns = [0]
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert table.state() is not QAbstractItemView.State.EditingState
    # nor are the boxes, the header's checking none of them
    view.variables.editable_columns = []
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=box)
    assert [row[0] for row in view.variables.rows] == ["False", "False"]


def test_a_table_s_file_path_dialog_opens_in_its_first_server_root_and_can_leave_it(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = StudyFilesTableMainView()
    view.inputs.cell_widgets = {1: CellWidget.file_path(server_roots=(tmp_path / "studies",))}
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.inputs)
    asked: list[str] = []

    def ask(*args: object) -> tuple[str, str]:
        asked.append(str(args[2]))
        return str(tmp_path / "elsewhere.export"), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(ask))
    cell = table.visualRect(table.model().index(0, 1))

    qtbot.mouseClick(
        table.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(cell.right() - 4, cell.center().y())
    )

    assert asked == [str(tmp_path / "studies")]
    # the app's own machine: a file outside the roots is the cell's path too
    assert view.inputs.rows[0] == ["Mesh", str(tmp_path / "elsewhere.export")]


def test_a_table_s_path_by_kind_opens_the_dialog_of_each_row_s_kind_from_the_study(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    study = tmp_path / "study"
    view = StudyInputsMainView()
    view.show_study(study)
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.files)
    model = table.model()
    asked: list[tuple[str, str]] = []

    def ask(dialog: str, answer: str) -> Callable[..., object]:
        def answered(*args: object, **_options: object) -> object:
            asked.append((dialog, str(args[2])))
            return answer if dialog == "folder" else (answer, "")

        return answered

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(ask("file", str(study / "beam.med")))
    )
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(ask("folder", "")))
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(ask("save", str(study / "out")))
    )

    def click_button(row: int) -> None:
        cell = table.visualRect(model.index(row, PATH))
        position = QPoint(cell.right() - 4, cell.center().y())
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=position)

    for row in range(3):
        click_button(row)

    assert asked == [
        ("file", str(study / "inputs")),
        ("folder", str(study / "inputs" / "materials")),
        ("save", str(study / "report.txt")),
    ]
    # picked inside the study: relative to it; the save path's extension added
    paths = [cells[PATH] for cells in view.files.rows]
    assert paths[0::2] == ["beam.med", "out.txt"]
    # a kind changed: the cell's dialog follows, and a kind without a widget is typed only
    model.setData(model.index(0, 1), OUTPUT_FOLDER)
    click_button(0)
    assert asked[-1] == ("folder", str(study / "beam.med"))
    model.setData(model.index(1, 1), "Notes")
    click_button(1)
    assert len(asked) == 4
    assert model.flags(model.index(1, PATH)) & Qt.ItemFlag.ItemIsEditable
    assert view.files.rows[1][1:] == ["Notes", "inputs/materials"]


def test_a_table_s_cell_widget_of_each_row_opens_its_own_dialog(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = StudyPathsMainView()
    view.inputs.show_paths(view.inputs.rows, folders=[1], roots=[tmp_path])
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.inputs)
    asked: list[tuple[str, str]] = []

    def ask(dialog: str, answer: str) -> Callable[..., object]:
        def answered(*args: object, **_options: object) -> object:
            asked.append((dialog, str(args[2])))
            return answer if dialog == "folder" else (answer, "")

        return answered

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(ask("file", str(tmp_path / "beam.med")))
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(ask("folder", str(tmp_path / "mat")))
    )

    for row in range(2):
        cell = table.visualRect(table.model().index(row, 1))
        position = QPoint(cell.right() - 4, cell.center().y())
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=position)

    # the rows are named alike: only the table's `cell_widget` tells them apart
    assert asked == [("file", str(tmp_path)), ("folder", str(tmp_path))]
    assert view.inputs.rows == [
        ["Mesh", str(tmp_path / "beam.med")],
        ["Mesh", str(tmp_path / "mat")],
    ]


def test_a_table_s_file_path_is_picked_in_qt_s_dialog_or_typed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = DataFilesTableMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.inputs)
    model = table.model()
    edits: list[tuple[int, int, str]] = []
    view.inputs.cell_edited.connect(lambda row, column, text: edits.append((row, column, text)))
    asked: list[tuple[str, str, str]] = []
    answer = ("", "")

    def ask(*args: object) -> tuple[str, str]:
        asked.append((str(args[1]), str(args[2]), str(args[3])))
        return answer

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(ask))

    def click_button(row: int) -> None:
        cell = table.visualRect(model.index(row, 1))
        position = QPoint(cell.right() - 4, cell.center().y())
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=position)

    click_button(0)  # cancelled
    assert (asked, edits) == ([("Choose a file", "", "CSV (*.csv)")], [])
    answer = (str(tmp_path / "flows.csv"), "CSV (*.csv)")
    click_button(0)
    assert view.inputs.rows[0] == ["Flows", answer[0]]
    assert model.index(0, 1).data() == answer[0]
    # Space on the current cell opens the dialog too, in the directory of its path
    table.setCurrentIndex(model.index(0, 1))
    answer = (str(tmp_path / "levels.csv"), "CSV (*.csv)")
    qtbot.keyClick(table, Qt.Key.Key_Space)
    assert asked[-1][1] == str(tmp_path)
    # or the path is typed, after a double click on its text
    cell = table.visualRect(model.index(1, 1))
    text = QPoint(cell.left() + 4, cell.center().y())
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=text)
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=text)
    editor = table.focusWidget()
    assert isinstance(editor, QLineEdit)
    qtbot.keyClicks(editor, "/data/levels.csv")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    # Qt commits the text and closes the editor in a queued call
    qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)
    assert edits == [
        (0, 1, str(tmp_path / "flows.csv")),
        (0, 1, str(tmp_path / "levels.csv")),
        (1, 1, "/data/levels.csv"),
    ]
    # not editable, the button opens nothing
    view.inputs.editable_columns = []
    click_button(1)
    table.setCurrentIndex(model.index(1, 1))
    qtbot.keyClick(table, Qt.Key.Key_Space)
    assert len(asked) == 3


def test_a_table_s_cells_and_headers_look_as_the_view_says(qtbot: QtBot) -> None:
    view = StyledTablesMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.points)
    model = table.model()

    def data(row: int, column: int, role: Qt.ItemDataRole) -> Any:
        return model.index(row, column).data(role)

    # NaN on red, its text white; a warning on light yellow, its text black, marked
    assert data(1, 2, Qt.ItemDataRole.BackgroundRole) == QColor("#dc2626")
    assert data(1, 2, Qt.ItemDataRole.ForegroundRole) == QColor("#ffffff")
    assert data(2, 3, Qt.ItemDataRole.ForegroundRole) == QColor("#000000")
    assert data(2, 3, Qt.ItemDataRole.DecorationRole) is not None
    assert data(2, 3, Qt.ItemDataRole.ToolTipRole) == "Warning"
    view.points.warning_text = "Attention"
    assert data(2, 3, Qt.ItemDataRole.ToolTipRole) == "Attention"
    # the group covers its two points
    assert (table.rowSpan(0, 0), table.rowSpan(2, 0)) == (2, 1)

    # a disabled cell of an editable column is neither typed in nor checked
    point = table.visualRect(model.index(1, 1)).center()
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert table.state() is not QAbstractItemView.State.EditingState
    box = table.visualRect(model.index(1, 4)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=box)
    assert view.points.rows[1][4] == "False"

    # the group's row doubles the header, a click on it sorting nothing
    header = table.horizontalHeader()
    view.points.sortable_columns = [2]
    group = QPoint(header.sectionViewportPosition(2) + 4, header.height() // 4)
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=group)
    assert view.points.sort_column is None
    column = QPoint(group.x(), 3 * header.height() // 4)
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=column)
    assert view.points.sort_column == 2
    unsortable = QPoint(header.sectionViewportPosition(0) + 4, column.y())
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=unsortable)
    assert view.points.sort_column == 2
    height = header.sizeHint().height()
    view.points.header_groups = []
    assert 2 * header.sizeHint().height() == height

    # the key/value table's keys head its rows; the points have no row headers
    numbers = _table(view.numbers)
    assert numbers.verticalHeader().isVisible()
    assert numbers.model().headerData(0, Qt.Orientation.Vertical) == "Number of calls"
    assert not table.verticalHeader().isVisible()

    # new looks show at once, in place of the old ones
    view.points.cell_styles = {(0, 2): CellStyle(background="#dc2626")}
    assert data(0, 2, Qt.ItemDataRole.BackgroundRole) == QColor("#dc2626")
    assert data(1, 2, Qt.ItemDataRole.BackgroundRole) is None
    view.numbers.row_headers = ["Calls", "Time (s)"]
    assert numbers.model().headerData(0, Qt.Orientation.Vertical) == "Calls"


# Qt warned "commitData called with an editor that does not belong to this view"
@pytest.mark.qt_log_level_fail("WARNING")
@pytest.mark.qt_log_ignore("propagateSizeHints")
def test_an_edit_answered_with_new_rows_closes_its_editor(qtbot: QtBot) -> None:
    view = EditableTableMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    # active, for the editor to take the focus, and lose it once closed
    with qtbot.waitActive(window):
        window.activateWindow()
    table = _table(view.places)
    model = table.model()

    def answer(row: int, column: int, text: str) -> None:
        view.places.rows = replace_cell(view.places.rows, row, column, text)

    view.places.cell_edited.connect(answer)
    center = table.visualRect(model.index(0, 1)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    editor = QApplication.focusWidget()
    assert isinstance(editor, QLineEdit)
    editor.selectAll()
    qtbot.keyClicks(editor, "Windy")
    # Tab commits, then would edit the next cell: the new rows reset the table first
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert table.state() is not QAbstractItemView.State.EditingState
    assert view.places.rows[0] == ["Lake", "Windy"]
    assert model.index(0, 1).data() == "Windy"
    assert QApplication.focusWidget() is table


def _sorted_rooms(qtbot: QtBot, *, wide: bool = False) -> tuple[SortedRoomsMainView, QFilterTable]:
    view = SortedRoomsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    if wide:  # the filter bar on one row whatever the system's fonts: Windows' are wider
        window.resize(1600, window.height())
    window.show()
    qtbot.waitExposed(window)
    box = _widget(view.rooms)
    assert isinstance(box, QFilterTable)
    return view, box


def _shown_column(table: QTextTableView, column: int) -> list[str]:
    model = table.model()
    return [model.index(row, column).data() or "" for row in range(model.rowCount())]


def test_clicking_a_sortable_header_sorts_by_it_then_back_and_shows_the_order(
    qtbot: QtBot,
) -> None:
    view, box = _sorted_rooms(qtbot)
    table, header = box.table, box.table.horizontalHeader()

    def click_header(column: int) -> None:
        position = QPoint(header.sectionViewportPosition(column) + 5, header.height() // 2)
        qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=position)

    click_header(2)  # the occupants
    assert _shown_column(table, 2) == ["2", "9", "10", ""]
    assert header.isSortIndicatorShown()
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (
        2,
        Qt.SortOrder.AscendingOrder,
    )
    click_header(2)
    assert _shown_column(table, 2) == ["10", "9", "2", ""]
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    click_header(2)
    assert view.rooms.sort_column is None
    assert _shown_column(table, 0) == ["Hall", "kitchen", "Attic", "Bedroom"]
    assert not header.isSortIndicatorShown()

    # a table sorting by no column: its headers sort nothing, and it has no filter bar
    notes = _widget(view.notes)
    assert isinstance(notes, QFilterTable)
    assert not notes.table.horizontalHeader().sectionsClickable()
    assert not notes.bar.isVisible()
    assert box.bar.isVisible()


def test_the_filter_bar_searches_and_adds_filters_shown_as_chips(qtbot: QtBot) -> None:
    view, box = _sorted_rooms(qtbot, wide=True)
    bar, table = box.bar, box.table

    qtbot.keyClicks(bar.search, "ROOM")
    # Enter searches at once: a wait for the typing's delay fails on a busy runner
    qtbot.keyClick(bar.search, Qt.Key.Key_Return)
    assert (view.rooms.search, _shown_column(table, 0)) == ("ROOM", ["Bedroom"])
    assert bar.count.text() == "1 of 4"
    bar.search.selectAll()
    qtbot.keyClick(bar.search, Qt.Key.Key_Backspace)
    assert _shown_column(table, 0) == ["Hall", "kitchen", "Attic", "Bedroom"]
    assert not bar.count.isVisible()

    def add(column: str, text: str) -> None:
        if not bar.is_editing():
            qtbot.mouseClick(bar.add_filter, Qt.MouseButton.LeftButton)
        bar.column.setCurrentIndex(bar.column.findText(column))
        bar.value.selectAll()
        qtbot.keyClicks(bar.value, text)
        qtbot.keyClick(bar.value, Qt.Key.Key_Return)

    # a value that doesn't parse isn't added: the field says why, the editor stays
    add("Temperature", "warm")
    assert bar.is_editing()
    assert (bar.value.property("invalid"), bar.value.toolTip()) == (
        True,
        '"warm" isn\'t a number',
    )
    assert view.rooms.filters == {}
    assert bar.value.placeholderText() == ">=20, 18..24"
    add("Temperature", ">=20")
    assert not bar.is_editing()
    assert _shown_column(table, 0) == ["kitchen", "Bedroom"]
    (chip,) = bar.chips
    # laid out in the bar after "+ Filter", the count apart at the bar's right end
    QApplication.processEvents()  # the layout's pass
    assert (parent := chip.parentWidget()) is not None
    assert parent.rect().contains(chip.geometry())
    assert bar.add_filter.geometry().right() < chip.x()
    assert bar.count.geometry().right() == bar.rect().right()
    assert chip.open_button.accessibleName() == "Temperature: >=20"
    assert chip.open_button.toolTip() == "Edit the filter on Temperature"
    # its chip has the focus: Enter opens it again, to replace the filter on its column;
    # another column's combines
    qtbot.waitUntil(chip.open_button.hasFocus)
    qtbot.keyClick(chip.open_button, Qt.Key.Key_Return)
    assert bar.value.text() == ">=20"
    add("Temperature", ">=21")
    add("Heated", "true")
    assert view.rooms.filters == {1: ">=21", 3: "true"}
    assert _shown_column(table, 0) == ["Bedroom"]
    assert bar.clear.isVisible()

    qtbot.mouseClick(bar.chips[0].remove_button, Qt.MouseButton.LeftButton)
    assert view.rooms.filters == {3: "true"}
    add("Occupants", ">100")
    assert table.model().rowCount() == 0
    assert box.empty.isVisible()
    assert box.empty.text() == "No rows match the filters"
    qtbot.mouseClick(bar.clear, Qt.MouseButton.LeftButton)
    assert table.model().rowCount() == 4
    assert bar.chips == []


def test_escape_empties_the_search_then_goes_on_to_the_window(qtbot: QtBot) -> None:
    view, box = _sorted_rooms(qtbot)
    bar, table = box.bar, box.table
    escaped: list[bool] = []
    QShortcut(QKeySequence("Escape"), box.window()).activated.connect(lambda: escaped.append(True))
    bar.search.setFocus()
    qtbot.waitUntil(bar.search.hasFocus)  # the window's shortcuts work once it's active
    qtbot.keyClicks(bar.search, "ROOM")
    # Enter searches at once: a wait for the typing's delay fails on a busy runner
    qtbot.keyClick(bar.search, Qt.Key.Key_Return)
    assert view.rooms.search == "ROOM"

    # the search is empty at once, not after the delay of typing; the shortcut waits
    qtbot.keyClick(bar.search, Qt.Key.Key_Escape)
    assert (bar.search.text(), view.rooms.search, escaped) == ("", "", [])
    assert _shown_column(table, 0) == ["Hall", "kitchen", "Attic", "Bedroom"]
    qtbot.keyClick(bar.search, Qt.Key.Key_Escape)
    assert escaped == [True]


def test_the_filter_editor_s_toggle_makes_the_value_a_regular_expression(qtbot: QtBot) -> None:
    view, box = _sorted_rooms(qtbot)
    bar = box.bar

    qtbot.mouseClick(bar.add_filter, Qt.MouseButton.LeftButton)
    # only for text: a number column takes comparisons
    bar.column.setCurrentIndex(bar.column.findText("Temperature"))
    assert not bar.pattern.isVisible()
    bar.column.setCurrentIndex(bar.column.findText("Room"))
    assert bar.pattern.isVisible()
    qtbot.mouseClick(bar.pattern, Qt.MouseButton.LeftButton)
    assert bar.value.placeholderText() == "a regular expression, as Room [1-3]"
    qtbot.keyClicks(bar.value, "^(hall|attic)$")
    qtbot.keyClick(bar.value, Qt.Key.Key_Return)
    assert _shown_column(box.table, 0) == ["Hall", "Attic"]
    (chip,) = bar.chips
    assert chip.open_button.accessibleName() == "Room matches ^(hall|attic)$"

    # reopened, the toggle is on and the value the pattern as typed
    qtbot.mouseClick(chip.open_button, Qt.MouseButton.LeftButton)
    assert bar.pattern.isChecked()
    assert bar.value.text() == "^(hall|attic)$"
    bar.value.selectAll()
    qtbot.keyClicks(bar.value, "(hall")
    qtbot.keyClick(bar.value, Qt.Key.Key_Return)
    assert bar.value.toolTip() == '"(hall" isn\'t a valid regular expression'
    assert view.rooms.filters == {0: "/^(hall|attic)$/"}


def test_a_click_and_an_edit_on_a_sorted_filtered_table_reach_their_rows(qtbot: QtBot) -> None:
    view, box = _sorted_rooms(qtbot)
    rooms, table = view.rooms, box.table
    rooms.filters = {3: "true"}
    rooms.sort_by(0)
    rooms.sort_by(0)  # descending: the kitchen, then the bedroom
    emitted: list[list[int]] = []
    rooms.selection_changed.connect(emitted.append)

    center = table.visualRect(table.model().index(1, 0)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert rooms.selected_records == [Room("Bedroom", 21, 9, is_heated=True)]
    assert emitted == [[3]]

    edited: list[tuple[Room, Room]] = []
    rooms.record_edited.connect(lambda old, new: edited.append((old, new)))
    # renamed, the bedroom sorts first and stays selected
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    editor = table.focusWidget()
    assert isinstance(editor, QLineEdit)
    editor.selectAll()
    qtbot.keyClicks(editor, "Study")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)
    assert edited == [
        (Room("Bedroom", 21, 9, is_heated=True), Room("Study", 21, 9, is_heated=True))
    ]
    assert _shown_column(table, 0) == ["Study", "kitchen"]
    assert rooms.selected_rows == [3]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [0]


def test_a_large_table_draws_the_rows_on_screen_reading_only_their_windows(
    qtbot: QtBot,
) -> None:
    view = MillionRowsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)
    container = _widget(view.table)
    assert isinstance(container, QDataFilterTable)
    table = container.table
    model = table.model()
    source = view.table.source
    assert isinstance(source, MillionSource)

    assert model.rowCount() == 1_000_000
    assert [model.headerData(column, Qt.Orientation.Horizontal) for column in range(2)] == [
        "Value",
        "Half",
    ]
    assert (model.index(1, 0).data(), model.index(1, 1).data()) == ("2", "0.5")
    table.scrollTo(model.index(500_000, 0), QAbstractItemView.ScrollHint.PositionAtTop)
    qtbot.waitUntil(lambda: 500_000 in source.read)
    assert model.headerData(500_000, Qt.Orientation.Vertical) == "500,001"
    # the rows drawn, by windows: never the million
    assert len(source.read) < 10 * SOURCE_TABLE_WINDOW

    source.size = 3
    source.changed.emit()
    assert model.rowCount() == 3


def test_a_large_table_s_header_clicks_sort_by_its_column_showing_the_order(
    qtbot: QtBot,
) -> None:
    view = MillionRowsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    container = _widget(view.table)
    assert isinstance(container, QDataFilterTable)
    table = container.table
    header = table.horizontalHeader()

    def click(column: int) -> None:
        position = QPoint(header.sectionViewportPosition(column) + 5, header.height() // 2)
        qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=position)

    assert not header.isSortIndicatorShown()
    click(1)
    assert (view.table.sort_column, view.table.sort_descending) == ("half", False)
    assert header.isSortIndicatorShown()
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (
        1,
        Qt.SortOrder.AscendingOrder,
    )
    click(1)
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    click(1)
    assert view.table.sort_column is None
    assert not header.isSortIndicatorShown()


def test_a_large_table_s_clicks_select_its_rows_and_a_double_click_activates_one(
    qtbot: QtBot,
) -> None:
    view = MillionRowsMainView()
    view.table.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    container = _widget(view.table)
    assert isinstance(container, QDataFilterTable)
    table = container.table
    model = table.model()
    activated: list[Any] = []
    view.table.row_activated.connect(activated.append)

    def click(row: int, modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
        center = table.visualRect(model.index(row, 0)).center()
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, modifier, center)

    click(1)
    click(4, Qt.KeyboardModifier.ShiftModifier)
    assert view.table.selected_ids == [1, 2, 3, 4]
    assert model.index(2, 1).data(Qt.ItemDataRole.BackgroundRole) is not None
    assert model.index(5, 1).data(Qt.ItemDataRole.BackgroundRole) is None
    click(2)  # selected: unselected
    assert view.table.selected_ids == [1, 3, 4]

    table.setCurrentIndex(model.index(6, 0))
    qtbot.keyClick(table, Qt.Key.Key_Space)
    qtbot.keyClick(table, Qt.Key.Key_Return)
    # a double click: a click, which selects the row, then the double click
    click(0)
    center = table.visualRect(model.index(0, 0)).center()
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert view.table.selected_ids == [1, 3, 4, 6, 0]
    assert activated == [6, 0]


def test_a_large_table_s_bar_searches_and_filters_its_columns_by_name(qtbot: QtBot) -> None:
    view = RoomsDataMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    box = _widget(view.rooms)
    assert isinstance(box, QDataFilterTable)
    bar, model = box.bar, box.table.model()

    def names() -> list[str]:
        return [model.index(row, 0).data() for row in range(model.rowCount())]

    assert bar.isVisible()
    assert [bar.column.itemText(i) for i in range(bar.column.count())] == ["Room", "Temperature"]
    qtbot.keyClicks(bar.search, "room")
    assert view.rooms.search == ""  # once the user stops typing: one search, not four
    qtbot.keyClick(bar.search, Qt.Key.Key_Return)  # or at once
    assert (view.rooms.search, names(), bar.count.text()) == ("room", ["Bedroom"], "1 of 3")
    bar.search.selectAll()
    qtbot.keyClick(bar.search, Qt.Key.Key_Backspace)
    assert (view.rooms.search, len(names()), bar.count.isVisible()) == ("", 3, False)

    qtbot.mouseClick(bar.add_filter, Qt.MouseButton.LeftButton)
    bar.column.setCurrentIndex(bar.column.findText("Temperature"))
    qtbot.keyClicks(bar.value, "warm")
    qtbot.keyClick(bar.value, Qt.Key.Key_Return)
    assert bar.value.toolTip() == '"warm" isn\'t a number'  # by the column's name
    bar.value.selectAll()
    qtbot.keyClicks(bar.value, ">19")
    qtbot.keyClick(bar.value, Qt.Key.Key_Return)
    assert view.rooms.filters == {"temperature": ">19"}
    assert names() == ["Kitchen", "Bedroom"]
    assert [chip.open_button.accessibleName() for chip in bar.chips] == ["Temperature: >19"]

    view.rooms.filters = {"temperature": ">30"}
    assert box.empty.isVisible()
    redrawn: list[object] = []
    model.dataChanged.connect(lambda *_args: redrawn.append(None))
    view.rooms.selected_ids = [0]  # a row the filter hides: nothing to redraw
    assert redrawn == []
    qtbot.mouseClick(bar.chips[0].remove_button, Qt.MouseButton.LeftButton)
    assert (view.rooms.filters, names(), box.empty.isVisible()) == (
        {},
        ["Kitchen", "Hall", "Bedroom"],
        False,
    )


def test_ctrl_c_copies_a_large_table_s_selected_rows_to_the_clipboard(qtbot: QtBot) -> None:
    view = MillionRowsMainView()
    view.table.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    container = _widget(view.table)
    assert isinstance(container, QDataFilterTable)
    table, model = container.table, container.table.model()
    for row in (3, 1):
        center = table.visualRect(model.index(row, 0)).center()
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)

    qtbot.keyClick(table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)

    # in the table's order: the value, then its half
    assert QApplication.clipboard().text() == "2\t0.5\n6\t1.5"


def test_a_large_source_s_rows_are_ordered_in_a_job_the_old_order_shown_meanwhile(
    qtbot: QtBot,
) -> None:
    view = GatedMainView()
    view.render(RendererType.QT)
    _add_reference_to_signals(view, None)  # as the app does: the table finds the jobs
    qtbot.addWidget(_widget(view))
    box = _widget(view.table)
    assert isinstance(box, QDataFilterTable)
    model, rows = box.table.model(), box.table.viewport()
    source = view.table.source
    assert isinstance(source, GatedSource)

    def first() -> str:
        return str(model.index(0, 0).data())

    source.gate.clear()
    view.table.sort_column = "value"
    view.table.sort_descending = True  # while the job orders: one more job, once over

    assert view.table.is_ordering
    assert first() == "0"  # the old order, the window responsive
    assert rows.cursor().shape() == Qt.CursorShape.BusyCursor
    source.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    assert first() == str(source.size - 1)
    assert [sort.descending for sort in source.orders if sort is not None] == [False, True]
    assert rows.cursor().shape() != Qt.CursorShape.BusyCursor

    # New or Open drops the jobs, the ordering's too: it orders again
    source.gate.clear()
    view.table.sort_descending = False
    view.jobs.drop()
    assert view.table.is_ordering
    source.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    assert first() == "0"

    # the source changes while a job orders: counted and ordered in the next job, the
    # running job's order dropped
    source.gate.clear()
    view.table.sort_descending = True
    source.size = SOURCE_TABLE_JOB_ROWS - 1
    source.counted_on_main.clear()
    source.changed.emit()
    assert view.table.row_count == SOURCE_TABLE_JOB_ROWS  # the old order meanwhile
    source.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    assert (model.rowCount(), view.table.total) == (source.size, source.size)
    assert source.counted_on_main == [False]

    # a new source: neither a count nor "no rows match" before its rows' first order
    other = GatedSource()
    other.gate.clear()
    view.table.source = other
    assert view.table.is_ordering
    assert (view.table.row_count, view.table.count_text) == (0, "")
    assert box.empty.isHidden()
    other.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    assert model.rowCount() == other.size


def test_a_job_s_order_keeps_the_selected_rows_it_shows_those_selected_meanwhile_too(
    qtbot: QtBot,
) -> None:
    view = GatedMainView()
    view.render(RendererType.QT)
    _add_reference_to_signals(view, None)  # as the app does: the table finds the jobs
    qtbot.addWidget(_widget(view))
    table = view.table
    source = table.source
    assert isinstance(source, GatedSource)
    table.selection_mode = SelectionMode.MULTIPLE
    last = source.size - 1
    table.selected_ids = [3, last]

    # the last two rows gone while a job orders the others, two rows clicked meanwhile, in
    # the old order shown
    source.gate.clear()
    source.size -= 2
    source.changed.emit()
    assert table.is_ordering
    table.select_at(last - 1)
    table.select_at(5)
    assert table.selected_ids == [3, last, last - 1, 5]
    emitted: list[list[Any]] = []
    table.selection_changed.connect(emitted.append)
    source.gate.set()
    qtbot.waitUntil(lambda: not table.is_ordering)

    assert table.selected_ids == [3, 5]
    assert emitted == [[3, 5]]


class _PositionalGatedSource(GatedSource):
    """Rows known by their positions, whose order fails once `fails` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.row_ids_scope = object()
        self.fails = False

    def new_rows(self, size: int) -> None:
        self.size = size
        self.row_ids_scope = object()
        self.changed.emit()

    @override
    def ordered_ids(
        self, sort: Optional[Sort], search: str, filters: Mapping[str, Filter]
    ) -> range:
        ids = super().ordered_ids(sort, search, filters)
        if self.fails and threading.current_thread() is not threading.main_thread():
            msg = "the rows can't be read"
            raise RuntimeError(msg)
        return ids


def _positional_rows(
    qtbot: QtBot,
) -> tuple[GatedMainView, _PositionalGatedSource, list[tuple[list[Any], int]]]:
    """Get a table ordering in a job, a row selected, and what each emission of it could read."""
    view = GatedMainView()
    view.render(RendererType.QT)
    _add_reference_to_signals(view, None)  # as the app does: the table finds the jobs
    qtbot.addWidget(_widget(view))
    source = _PositionalGatedSource()
    view.table.source = source
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    view.table.selected_ids = [3]
    emitted: list[tuple[list[Any], int]] = []

    def record(selected: list[Any]) -> None:
        emitted.append((selected, view.table.total))

    view.table.selection_changed.connect(record)
    source.gate.clear()
    return view, source, emitted


def test_a_selection_cleared_by_new_rows_is_emitted_once_a_job_ordered_them(
    qtbot: QtBot,
) -> None:
    view, source, emitted = _positional_rows(qtbot)
    new_size = SOURCE_TABLE_JOB_ROWS + 5

    source.new_rows(new_size)
    assert (view.table.selected_ids, emitted) == ([], [])

    source.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    assert emitted == [([], new_size)]


def test_a_selection_cleared_by_new_rows_is_emitted_when_their_order_fails(qtbot: QtBot) -> None:
    view, source, emitted = _positional_rows(qtbot)

    source.fails = True
    source.new_rows(SOURCE_TABLE_JOB_ROWS)
    source.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)

    assert [selected for selected, _ in emitted] == [[]]


def test_a_selection_made_while_new_rows_are_ordered_is_not_reported_as_cleared(
    qtbot: QtBot,
) -> None:
    view, source, emitted = _positional_rows(qtbot)

    source.new_rows(SOURCE_TABLE_JOB_ROWS)
    view.table.selected_ids = [7]
    source.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)

    assert emitted == []
    assert view.table.selected_ids == [7]


def test_a_large_table_s_new_source_shows_its_columns_in_the_bar(qtbot: QtBot) -> None:
    view = RoomsDataMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    box = _widget(view.rooms)
    assert isinstance(box, QDataFilterTable)
    view.rooms.filters = {"name": "Hall"}

    # as an app swapping its rows: the bar shows the new source's columns, filtering by name
    view.rooms.source = ListSource(Room, {"name": T("Room")}, [Room("Hall", 18.0)])

    columns = [box.bar.column.itemText(index) for index in range(box.bar.column.count())]
    assert columns == ["Room"]
    assert [chip.open_button.text() for chip in box.bar.chips] == ["Room: Hall ✎"]


def test_a_large_table_draws_each_row_with_one_read_of_its_cells(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    read: list[int] = []
    rows = SourceTableView.rows

    def counted(table: SourceTableView, start: int, stop: int) -> list[tuple[Any, list[str]]]:
        read.append(start)
        return rows(table, start, stop)

    monkeypatch.setattr(SourceTableView, "rows", counted)
    view = MillionRowsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    box = _widget(view.table)
    assert isinstance(box, QDataFilterTable)
    read.clear()

    box.table.viewport().grab()

    # Qt asks each cell's text and colors apart: the row's cells are formatted once
    assert 0 < len(read) == len(set(read))
    last = read[-1]  # the row the model keeps
    view.table.column_formats = {"half": ".3f"}  # the same rows, formatted again
    assert box.table.model().index(last, 1).data() == f"{last / 2:.3f}"


@pytest.mark.parametrize(
    ("picked", "written"),
    [("rooms", ["rooms.csv"]), ("rooms.CSV", ["rooms.CSV"]), ("", [])],
    ids=["named", "with-extension", "cancelled"],
)
def test_a_large_table_s_button_exports_its_rows_as_csv(
    picked: str,
    written: list[str],
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = RoomsDataMainView()
    view.render(RendererType.QT)
    box = _widget(view.rooms)
    assert isinstance(box, QDataFilterTable)
    qtbot.addWidget(_widget(view))
    view.rooms.filters = {"temperature": ">19"}
    asked: list[tuple[str, str, str]] = []

    def get_save_file_name(
        _parent: QWidget, caption: str, name: str, filters: str
    ) -> tuple[str, str]:
        asked.append((caption, name, filters))
        return (str(tmp_path / picked) if picked else ""), filters

    monkeypatch.setattr(QFileDialog, "getSaveFileName", get_save_file_name)
    # a button above the rows, and the table's context menu, share the action
    (action,) = (action for action in box.table.actions() if action.text() == "Export CSV…")
    assert box.export.defaultAction() is action
    window = _widget(view)
    window.show()
    qtbot.waitExposed(window)
    assert box.export.isVisible()

    qtbot.mouseClick(box.export, Qt.MouseButton.LeftButton)

    assert asked == [("Export CSV", "table.csv", "CSV (*.csv)")]
    assert [path.name for path in tmp_path.iterdir()] == written
    for name in written:
        assert (tmp_path / name).read_text(encoding="utf-8").splitlines() == [
            "Room,Temperature,Occupants",
            "Kitchen,21.5,2",
            "Bedroom,19.5,1",
        ]


def test_a_large_table_without_an_export_filename_offers_no_export_csv(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = RoomsDataMainView()
    view.rooms.export_filename = None
    view.render(RendererType.QT)
    box = _widget(view.rooms)
    assert isinstance(box, QDataFilterTable)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    action = box.table.export_action

    # an invisible action stays out of the context menu, and hides its button
    assert (action.isVisible(), box.export.isVisible()) == (False, False)
    view.rooms.export_filename = "rooms.csv"
    assert (action.isVisible(), box.export.isVisible()) == (True, True)

    def get_save_file_name(*_args: object) -> tuple[str, str]:
        view.rooms.export_filename = None  # e.g. a job's callback, while the dialog is open
        return str(tmp_path / "rooms.csv"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", get_save_file_name)
    qtbot.mouseClick(box.export, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not view.jobs.is_running)  # an export writes in a job
    assert list(tmp_path.iterdir()) == []


def test_a_check_all_box_follows_its_column_turning_read_only_or_plain(qtbot: QtBot) -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    model = _table(view.variables).model()

    def box() -> QImage | None:
        icon = model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DecorationRole)
        return None if icon is None else icon.pixmap(16, 16).toImage()

    enabled = box()
    view.variables.editable_columns = [2]
    disabled = box()
    view.variables.cell_widgets = {2: CellWidget.combobox(["Input", "Output"])}

    assert enabled is not None
    assert disabled is not None
    assert disabled != enabled  # drawn disabled
    assert box() is None  # a plain column again


def test_a_table_s_keys_and_edits_report_only_what_changes(qtbot: QtBot) -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.variables)
    model, header = table.model(), table.horizontalHeader()
    assert isinstance(header, QCheckHeader)
    clicks: list[tuple[int, int]] = []
    edits: list[tuple[int, int, str]] = []
    view.variables.cell_clicked.connect(lambda row, column: clicks.append((row, column)))
    view.variables.cell_edited.connect(lambda row, column, text: edits.append((row, column, text)))

    # Space on a link's cell clicks it
    table.setFocus()
    table.setCurrentIndex(model.index(0, 4))
    qtbot.keyClick(table, Qt.Key.Key_Space)
    # a button's or a link's column has no editor, even editable
    view.variables.editable_columns = [0, 1, 2, 3, 4]
    link_flags = model.flags(model.index(0, 4))
    # Escape, or Enter on the text as it was, edits nothing
    cell = table.visualRect(model.index(0, 1)).center()
    for key in (Qt.Key.Key_Escape, Qt.Key.Key_Return):
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=cell)
        qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=cell)
        editor = table.focusWidget()
        assert isinstance(editor, QLineEdit)
        qtbot.keyClick(editor, key)
        qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)
    # the right button on the header's box checks nothing
    box = QPoint(header.sectionViewportPosition(0) + header.box_width() // 2, header.height() // 2)
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.RightButton, pos=box)

    assert clicks == [(0, 4)]
    assert not link_flags & Qt.ItemFlag.ItemIsEditable
    assert edits == []
    assert [row[0] for row in view.variables.rows] == ["True", "false"]
    # as a Qt model: nothing for no cell, and only an edit changes one
    assert model.data(QModelIndex()) is None
    assert model.setData(model.index(0, 1), "Width", Qt.ItemDataRole.DisplayRole) is False


def test_a_disabled_cell_is_drawn_disabled(qtbot: QtBot) -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.variables)
    button = table.visualRect(table.model().index(0, 3))

    def drawn() -> QImage:
        QApplication.processEvents()
        return table.viewport().grab(button).toImage()

    enabled = drawn()
    view.variables.cell_styles = {(0, 3): CellStyle(is_enabled=False)}

    assert drawn() != enabled


def test_a_header_group_s_name_is_drawn_over_its_columns(qtbot: QtBot) -> None:
    view = StyledTablesMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    header = _table(view.points).horizontalHeader()

    def drawn() -> QImage:
        QApplication.processEvents()
        return header.grab().toImage()

    named = drawn()
    view.points.header_groups = [HeaderGroup("", 2, 2)]

    assert drawn() != named


def test_a_table_without_headers_has_no_columns(qtbot: QtBot) -> None:
    view = TableView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))

    model = _table(view).model()

    assert (model.rowCount(), model.columnCount()) == (0, 0)


def test_a_filter_s_chip_opens_on_space_and_its_editor_closes_on_escape(qtbot: QtBot) -> None:
    view, box = _sorted_rooms(qtbot)
    bar = box.bar
    view.rooms.filters = {3: "true"}
    (chip,) = bar.chips

    qtbot.keyClick(chip.open_button, Qt.Key.Key_Space)
    opened = (bar.is_editing(), bar.value.text())
    qtbot.keyClick(bar.value, Qt.Key.Key_Escape)
    view.rooms.search = "kit"  # set in code: shown in the field

    assert opened == (True, "true")
    assert not bar.is_editing()
    assert view.rooms.filters == {3: "true"}
    assert bar.search.text() == "kit"


class _FailingGatedSource(GatedSource):
    """A large source whose order, asked in a job, fails: e.g. its database gone."""

    @override
    def ordered_ids(self, sort: Sort | None, search: str, filters: Mapping[str, Filter]) -> range:
        if threading.current_thread() is not threading.main_thread():
            msg = "the database is gone"
            raise OSError(msg)
        return super().ordered_ids(sort, search, filters)


def test_a_large_table_keeps_its_order_when_a_job_fails_or_was_overtaken(
    qtbot: QtBot,
) -> None:
    view = GatedMainView()
    view.render(RendererType.QT)
    _add_reference_to_signals(view, None)  # as the app does: the table finds the jobs
    qtbot.addWidget(_widget(view))
    shown = view.table.row_count

    view.table.source = _FailingGatedSource()  # its first order fails, in its job
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    failed = view.table.row_count
    source = GatedSource()
    view.table.source = source
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    source.gate.clear()
    view.table.sort_descending = True  # a job, then a small source answered at once
    view.table.source = ListSource(Room, {"name": T("Room")}, [Room("Hall", 18.0)])
    source.gate.set()
    qtbot.waitUntil(lambda: not view.jobs.is_running)  # the job's answer, come late

    assert shown > 0
    assert failed == 0  # no order to show yet, its failure logged
    assert view.table.row_count == 1  # the overtaken job's order dropped


def test_a_large_table_s_bar_clears_its_filters(qtbot: QtBot) -> None:
    view = RoomsDataMainView()
    view.rooms.filters = {"name": "Hall", "temperature": ">10"}  # two: the bar clears them
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    box = _widget(view.rooms)
    assert isinstance(box, QDataFilterTable)

    qtbot.mouseClick(box.bar.clear, Qt.MouseButton.LeftButton)

    assert view.rooms.filters == {}


def test_a_large_table_qt_doesn_t_render_still_orders_its_rows_in_a_job(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(QT_RENDERERS, "source_table")  # e.g. a backend lacking it
    view = GatedMainView()
    view.render(RendererType.QT)
    _add_reference_to_signals(view, None)  # as the app does: the table finds the jobs
    qtbot.addWidget(_widget(view))

    view.table.sort_descending = True
    ordering = view.table.is_ordering
    qtbot.waitUntil(lambda: not view.table.is_ordering)

    assert view.table.renderer is None
    assert ordering  # in a job, as in a table shown
