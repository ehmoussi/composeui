"""Tests of the Textual tables and their filter bars."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from attrs import Factory
from textual.coordinate import Coordinate
from textual.widgets import (
    Input,
)
from textual_fspicker.parts import DirectoryNavigation

from composeui.core._views.tables import SOURCE_TABLE_WINDOW
from composeui.core.application import _add_reference_to_signals
from composeui.core.registry import RendererType
from composeui.core.view import (
    SEARCH_DELAY_MS,
    CellStyle,
    CellWidget,
    EditRefusedError,
    ListSource,
    MainView,
    SelectionMode,
    SourceTableView,
    T,
    define_view,
    replace_cell,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composefilepathinput import (
    ReplaceFileScreen,
)
from composeui.textualcore.widgets.composefiltertable import (
    ComposeFilterBar,
    ComposeFilterChip,
    ComposeFilterTable,
)
from composeui.textualcore.widgets.composesourcetable import (
    ComposeDataFilterTable,
    ComposeSourceTable,
)
from composeui.textualcore.widgets.composetable import (
    ComposeOptionPicker,
    ComposeRowEditor,
    ComposeTable,
)
from examples.pipeform import PipeMainView
from examples.studyinputs import KIND, PATH, StudyInputsMainView
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
    RequiredOptionsMainView,
    Room,
    RoomsDataMainView,
    SortedRoomsMainView,
    StyledTablesMainView,
)

if TYPE_CHECKING:
    from textual.app import App
    from textual.pilot import Pilot
    from textual.screen import Screen

    from composeui.core.view import TableView

from tests.textualcore.support import _app_of, _click_laid_out, _field_widget, _names, _widget


@pytest.mark.asyncio
async def test_the_summary_table_shows_each_edit_as_plain_text() -> None:
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(100, 60)) as pilot:
        await pilot.pause()
        assert isinstance(view.pages.results.summary.renderer, TextualWidgetRenderer)
        box = view.pages.results.summary.renderer.widget
        assert isinstance(box, ComposeFilterTable)
        table = box.table

        def lines() -> list[str]:
            return [table.render_line(y).text.strip() for y in range(table.size.height)]

        radius = _field_widget(view.pages.inputs.pipe_form.main_pipe.radius.renderer)
        radius.focus()
        await pilot.press("end", *["backspace"] * 10, *"35", "tab")
        view.pages.navigate("results")
        await pilot.pause()
        assert lines()[1].split() == ["Main", "Pipe", "35", "20", "200"]

        # shown as typed, not read as Rich markup (which would drop "[red]")
        view.pages.results.summary.rows = [["[red]", "1", "2", "3"]]
        await pilot.pause()
        assert lines()[1].split() == ["[red]", "1", "2", "3"]


@pytest.mark.asyncio
async def test_clicking_a_table_row_selects_it_and_emits_only_for_the_user() -> None:
    view = HorizontalMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.tables.narrow.renderer, TextualWidgetRenderer)
    box = view.tables.narrow.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    emitted: list[list[int]] = []
    view.tables.narrow.selection_changed.connect(emitted.append)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert not table.show_cursor  # nothing selected yet

        # the header, then the rows: South is the second
        await pilot.click(table, offset=(2, 2))
        await pilot.pause()
        assert table.show_cursor
        assert view.tables.narrow.selected_rows == [1]
        assert emitted == [[1]]

        await pilot.press("down")
        await pilot.pause()
        assert view.tables.narrow.selected_rows == [2]
        assert emitted == [[1], [2]]

        # set from code: shown, but not the user's doing
        view.tables.narrow.selected_rows = [0]
        await pilot.pause()
        assert table.cursor_row == 0
        # new rows still holding it, moved: the cursor follows it
        view.tables.narrow.rows = [["West"], ["North"]]
        await pilot.pause()
        assert (table.show_cursor, table.cursor_row) == (True, 1)
        view.tables.narrow.rows = [["West"]]
        await pilot.pause()
        assert not table.show_cursor
        assert emitted == [[1], [2]]


@pytest.mark.asyncio
async def test_enter_or_a_double_click_activates_a_table_row_unless_it_edits() -> None:
    view = EditableTableMainView()
    # sorted by place, the harbour shows first: the table emits its index in `rows`
    view.places.sortable_columns = [0]
    view.places.sort_column = 0
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.places.renderer, TextualWidgetRenderer)
    box = view.places.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    emitted: list[tuple[str, object]] = []
    view.places.selection_changed.connect(lambda rows: emitted.append(("selected", rows)))
    view.places.row_activated.connect(lambda row: emitted.append(("activated", row)))

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # nothing selected yet: Enter selects the cursor's row, then activates it
        table.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert emitted == [("selected", [1]), ("activated", 1)]

        # the header, then the rows: the lake's is the second
        await pilot.double_click(table, offset=(2, 2))
        await pilot.pause()
        assert emitted[-1] == ("activated", 0)
        count = len(emitted)
        # a double click on a note edits it instead
        place = next(iter(table.columns.values()))
        await pilot.double_click(table, offset=(place.get_render_width(table) + 1, 2))
        await pilot.pause()
        assert isinstance(app.screen, ComposeRowEditor)
        assert len(emitted) == count


@pytest.mark.asyncio
async def test_a_click_or_enter_adds_or_removes_its_row_in_a_table_selecting_several() -> None:
    view = HorizontalMainView()
    table_view = view.tables.narrow
    table_view.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(table_view.renderer, TextualWidgetRenderer)
    box = table_view.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    emitted: list[list[int]] = []
    table_view.selection_changed.connect(emitted.append)

    def checked() -> list[str]:
        return [str(table.get_cell_at(Coordinate(row, 0))) for row in range(table.row_count)]

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # the header, then the rows: South is the second
        await pilot.click(table, offset=(2, 2))
        await pilot.pause()
        # the cursor only moves: Enter adds its row
        await pilot.press("down", "enter")
        await pilot.pause()
        assert table_view.selected_rows == [1, 2]
        assert checked() == ["", "✓", "✓"]
        await pilot.click(table, offset=(2, 2))
        await pilot.pause()
        assert table_view.selected_rows == [2]
        assert emitted == [[1], [1, 2], [2]]

        # set from code: shown, but not the user's doing
        table_view.selected_rows = [0, 1]
        await pilot.pause()
        assert checked() == ["✓", "✓", ""]
        # new rows still holding one of them, moved: its check follows it
        table_view.rows = [["West"], ["North"]]
        await pilot.pause()
        assert checked() == ["", "✓"]
        assert emitted == [[1], [1, 2], [2]]


@pytest.mark.asyncio
async def test_f2_or_a_double_click_edits_a_row_s_editable_cells_keeping_the_selection() -> None:
    view = EditableTableMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.places.renderer, TextualWidgetRenderer)
    box = view.places.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    edited: list[tuple[int, int, str, list[str]]] = []

    def record(row: int, column: int, text: str) -> None:
        # the row as it was: the edit is applied once the callbacks have run, then the row
        # as `cell_edit_applied` finds it
        edited.append((row, column, text, view.places.rows[row]))

    view.places.cell_edited.connect(record)
    view.places.cell_edit_applied.connect(record)

    def cells() -> list[list[str]]:
        return [[str(cell) for cell in table.get_row_at(row)] for row in range(table.row_count)]

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # the header, then the rows: the harbour's, short of its note, is the second
        await pilot.click(table, offset=(2, 2))
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, ComposeRowEditor)
        assert app.focused is app.screen.inputs[1]  # the only editable cell, the note
        await pilot.press(*"Busy", "enter")
        await pilot.pause()
        assert view.places.rows == [["Lake", "Calm"], ["Harbour", "Busy"]]
        assert cells() == [["Lake", "Calm"], ["Harbour", "Busy"]]
        assert edited == [(1, 1, "Busy", ["Harbour"]), (1, 1, "Busy", ["Harbour", "Busy"])]
        # its row moved nowhere: it stays selected
        assert view.places.selected_rows == [1]

        # the lake's note: past the place's cell, whose own double click edits nothing
        await pilot.double_click(table, offset=(2, 1))
        await pilot.pause()
        assert not isinstance(app.screen, ComposeRowEditor)
        place = next(iter(table.columns.values()))
        note = place.get_render_width(table) + 1
        await pilot.double_click(table, offset=(note, 1))
        await pilot.pause()
        assert isinstance(app.screen, ComposeRowEditor)
        # Escape leaves the row as it was
        await pilot.press("ctrl+a", *"Windy", "escape")
        await pilot.pause()
        assert not isinstance(app.screen, ComposeRowEditor)
        assert (view.places.rows, len(edited)) == ([["Lake", "Calm"], ["Harbour", "Busy"]], 2)

        # the app answers with its rows sorted by note: the cursor follows the lake
        def answer(row: int, column: int, text: str) -> None:
            rows = replace_cell(view.places.rows, row, column, text)
            view.places.rows = sorted(rows, key=lambda cells: cells[1])

        view.places.cell_edited.connect(answer)
        await pilot.double_click(table, offset=(note, 1))
        await pilot.press("end", *["backspace"] * len("Calm"), *"Windy", "enter")
        await pilot.pause()
        assert cells() == [["Harbour", "Busy"], ["Lake", "Windy"]]
        assert view.places.selected_rows == [1]
        assert table.cursor_row == 1


@pytest.mark.asyncio
async def test_a_table_s_cells_and_headers_look_as_the_view_says() -> None:
    view = StyledTablesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    def table_of(table_view: TableView) -> ComposeTable:
        assert isinstance(table_view.renderer, TextualWidgetRenderer)
        box = table_view.renderer.widget
        assert isinstance(box, ComposeFilterTable)
        return box.table

    table, numbers = table_of(view.points), table_of(view.numbers)

    def x(column: int) -> int:
        return sum(each.get_render_width(table) for each in list(table.columns.values())[:column])

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # the group's text over its first column's header
        labels = [str(column.label) for column in table.columns.values()]
        assert labels[1:4] == ["\nPoint", "Coordinates\nStandard space", "\nPhysical space"]
        assert table.header_height == 2
        # the group's cell shows its text once, in its first row
        rows = [table.get_row_at(row) for row in range(3)]
        assert [str(cells[0]) for cells in rows] == ["A", "", "B"]
        # NaN on red, its text white; a warning marked before its text; a disabled cell dim
        assert [str(span.style) for span in rows[1][2].spans] == ["#ffffff on #dc2626"]
        assert str(rows[2][3]) == "! 40.0"
        assert any("dim" in str(span.style) for span in rows[1][1].spans)
        # a click on a box toggles it, unless disabled
        await pilot.click(table, offset=(x(4) + 1, 2))
        await pilot.click(table, offset=(x(4) + 1, 3))
        await pilot.pause()
        assert [row[4] for row in view.points.rows] == ["False", "False", "True"]
        # the key/value table's keys head its rows
        assert [str(row.label) for row in numbers.rows.values()] == ["Number of calls", "Time (s)"]

        # new looks show at once, in place of the old ones
        view.points.cell_styles = {(0, 2): CellStyle(background="#dc2626")}
        view.numbers.row_headers = ["Calls", "Time (s)"]
        await pilot.pause()
        assert [str(span.style) for span in table.get_row_at(0)[2].spans] == ["#ffffff on #dc2626"]
        assert table.get_row_at(1)[2].spans == []
        assert [str(row.label) for row in numbers.rows.values()] == ["Calls", "Time (s)"]


@pytest.mark.asyncio
async def test_a_table_s_cell_widgets_edit_their_cells_or_report_their_clicks() -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.variables.renderer, TextualWidgetRenderer)
    box = view.variables.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    events: list[tuple[int, ...] | tuple[int, int, str]] = []
    view.variables.cell_edited.connect(lambda row, column, text: events.append((row, column, text)))
    view.variables.cell_clicked.connect(lambda row, column: events.append((row, column)))
    view.variables.row_activated.connect(lambda row: events.append((row,)))

    def x(column: int) -> int:
        """Get the offset of a column's first character."""
        return sum(each.get_render_width(table) for each in list(table.columns.values())[:column])

    def cells(row: int) -> list[str]:
        return [str(cell) for cell in table.get_row_at(row)]

    def header() -> str:
        return str(next(iter(table.columns.values())).label)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert cells(0) == ["\u2611", "Length", "Input \u25be", "Normal [\u2026]", "doc"]
        assert header() == "\u25a3 Keep"  # some rows checked

        # a click toggles a box: the header's follows
        await pilot.click(table, offset=(x(0) + 1, 2))
        await pilot.pause()
        assert view.variables.rows[1][0] == "True"
        assert (cells(1)[0], header()) == ("\u2611", "\u2611 Keep")
        # the header's box unchecks every row, each an edit
        await pilot.click(table, offset=(x(0) + 1, 0))
        await pilot.pause()
        assert [row[0] for row in view.variables.rows] == ["False", "False"]
        assert header() == "\u2610 Keep"
        # Space toggles the cursor row's box
        await pilot.press("space")
        await pilot.pause()
        assert [row[0] for row in view.variables.rows] == ["False", "True"]

        # a combobox's click picks among its options
        await pilot.click(table, offset=(x(2) + 1, 1))
        await pilot.pause()
        assert isinstance(app.screen, ComposeOptionPicker)
        await pilot.press("down", "enter")
        await pilot.pause()
        assert view.variables.rows[0][2] == "Output"

        # a button and a link report their clicks, editing nothing; a double click, once,
        # opening no row
        await pilot.click(table, offset=(x(3) + 1, 2))
        await pilot.double_click(table, offset=(x(4) + 1, 1))
        await pilot.pause()
        assert events == [
            (1, 0, "True"),
            (0, 0, "False"),
            (1, 0, "False"),
            (1, 0, "True"),
            (0, 2, "Output"),
            (1, 3),
            (0, 4),
        ]


@pytest.mark.asyncio
async def test_a_table_s_file_path_picker_opens_in_its_first_server_root(tmp_path: Path) -> None:
    (tmp_path / "studies").mkdir()
    view = StudyFilesTableMainView()
    view.inputs.cell_widgets = {1: CellWidget.file_path(server_roots=(tmp_path / "studies",))}
    app = _app_of(view)
    box = _widget(view.inputs)
    assert isinstance(box, ComposeFilterTable)
    table = box.table

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        x = next(iter(table.columns.values())).get_render_width(table) + 1
        await pilot.click(table, offset=(x, 1))
        await pilot.pause()
        location = app.screen.query_one(DirectoryNavigation).location
        app.screen.dismiss(tmp_path / "elsewhere.export")  # as the picker's Open does
        await pilot.pause()

    assert Path(location) == tmp_path / "studies"
    # the app's own machine: a file outside the roots is the cell's path too
    assert view.inputs.rows[0] == ["Mesh", str(tmp_path / "elsewhere.export")]


@pytest.mark.asyncio
async def test_a_table_s_path_by_kind_opens_the_picker_of_each_row_s_kind_from_the_study(
    tmp_path: Path,
) -> None:
    study = tmp_path / "study"
    (study / "inputs" / "materials").mkdir(parents=True)
    (study / "summary.txt").write_text("")
    view = StudyInputsMainView()
    view.show_study(study)
    # a kind without a path widget: its path is typed only
    view.files.cell_widgets = {
        **view.files.cell_widgets,
        KIND: CellWidget.combobox([*view.files.cell_widgets[KIND].options, "Notes"]),
    }
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.files.renderer, TextualWidgetRenderer)
    box = view.files.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    opened: list[tuple[str, Path]] = []

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        widths = [column.get_render_width(table) for column in table.columns.values()]

        async def browse(row: int, picked: Path | None) -> Screen[Any]:
            await pilot.click(table, offset=(sum(widths[:PATH]) + 1, row + 1))
            await pilot.pause()
            location = app.screen.query_one(DirectoryNavigation).location
            opened.append((type(app.screen).__name__, Path(location)))
            app.screen.dismiss(picked)  # as the picker's Open, Select or Save does
            await pilot.pause()
            return app.screen

        await browse(0, study / "inputs" / "beam.med")
        await browse(1, None)
        question = await browse(2, study / "summary")  # exists, its extension added
        assert isinstance(question, ReplaceFileScreen)
        await pilot.press("escape")  # kept
        await pilot.pause()
        assert view.files.rows[2][PATH] == "report.txt"
        question = await browse(2, study / "summary")
        assert isinstance(question, ReplaceFileScreen)
        await _click_laid_out(pilot, question.replace_button)
        await pilot.pause()
        # the last row's kind picked: its path's picker follows
        await pilot.click(table, offset=(widths[0] + 1, 4))
        await pilot.pause()
        assert isinstance(app.screen, ComposeOptionPicker)
        await pilot.press("up", "enter")
        await pilot.pause()
        await browse(3, study / "totals")  # a new file: at once
        # a kind without a widget: the path cell, drawn again, has no button
        await pilot.click(table, offset=(widths[0] + 1, 4))
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert (view.files.rows[3][KIND], str(table.get_cell_at(Coordinate(3, PATH)))) == (
            "Notes",
            "totals.txt",
        )

    assert opened == [
        ("FileOpen", study / "inputs"),
        ("SelectDirectory", study / "inputs" / "materials"),
        ("FileSave", study),
        ("FileSave", study),
        ("FileSave", study),
    ]
    paths = [cells[PATH] for cells in view.files.rows]
    assert paths == [
        str(Path("inputs", "beam.med")),
        "inputs/materials",
        "summary.txt",
        "totals.txt",
    ]


@pytest.mark.asyncio
async def test_space_toggles_the_box_that_cell_widget_gives_the_cursor_row_only() -> None:
    view = RequiredOptionsMainView()
    app = _app_of(view)
    assert isinstance(view.options.renderer, TextualWidgetRenderer)
    box = view.options.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        width = next(iter(table.columns.values())).get_render_width(table)
        await pilot.click(table, offset=(width + 1, 2))  # the report's name: the cursor's row
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        # the mesh's row has no box: Space leaves it
        await pilot.press("up", "space")
        await pilot.pause()
        assert view.options.rows == [["True", "Mesh"], ["True", "Report"]]
        # no row left, the cursor still shown, as it stays when selecting several
        view.options.selection_mode = SelectionMode.MULTIPLE
        view.options.rows = []
        await pilot.pause()
        assert table.show_cursor
        await pilot.press("space")
        await pilot.pause()


@pytest.mark.asyncio
async def test_a_table_s_cell_widget_of_each_row_opens_its_own_picker(tmp_path: Path) -> None:
    view = StudyPathsMainView()
    view.inputs.show_paths(view.inputs.rows, folders=[1], roots=[tmp_path])
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.inputs.renderer, TextualWidgetRenderer)
    box = view.inputs.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    picks = [("FileOpen", tmp_path / "beam.med"), ("SelectDirectory", tmp_path / "mat")]

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        width = next(iter(table.columns.values())).get_render_width(table)
        for row, (picker, picked) in enumerate(picks):
            await pilot.click(table, offset=(width + 1, row + 1))
            await pilot.pause()
            # the rows are named alike: only the table's `cell_widget` tells them apart
            assert type(app.screen).__name__ == picker
            app.screen.dismiss(picked)  # as the picker's Open or Select does
            await pilot.pause()

    assert view.inputs.rows == [
        ["Mesh", str(tmp_path / "beam.med")],
        ["Mesh", str(tmp_path / "mat")],
    ]


@pytest.mark.asyncio
async def test_a_table_s_file_path_is_picked_in_the_file_picker_or_typed(tmp_path: Path) -> None:
    (tmp_path / "flows.csv").write_text("1,2", encoding="utf-8")
    view = DataFilesTableMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.inputs.renderer, TextualWidgetRenderer)
    box = view.inputs.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    edits: list[tuple[int, int, str]] = []
    view.inputs.cell_edited.connect(lambda row, column, text: edits.append((row, column, text)))

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # the offset of the path's column
        x = next(iter(table.columns.values())).get_render_width(table) + 1
        assert [str(cell) for cell in table.get_row_at(0)] == ["Flows", " [\u2026]"]
        # a click opens the picker, the cell taking the file picked; Escape picks none
        await pilot.click(table, offset=(x, 1))
        await pilot.pause()
        assert [type(s).__name__ for s in app.screen_stack] == ["Screen", "FileOpen"]
        await pilot.press("escape")
        await pilot.pause()
        assert (len(app.screen_stack), edits) == (1, [])
        await pilot.click(table, offset=(x, 1))
        await pilot.pause()
        file_input = app.screen.query_one(Input)
        file_input.focus()
        file_input.value = str(tmp_path / "flows.csv")
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(4):
            await pilot.pause()
        assert len(app.screen_stack) == 1
        assert view.inputs.rows[0] == ["Flows", str(tmp_path / "flows.csv")]
        # or F2's editor types it
        await pilot.click(table, offset=(1, 2))
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, ComposeRowEditor)
        await pilot.press(*"/data/levels.csv", "enter")
        await pilot.pause()
        assert edits == [(0, 1, str(tmp_path / "flows.csv")), (1, 1, "/data/levels.csv")]
        # not editable, a click opens nothing
        view.inputs.editable_columns = []
        await pilot.click(table, offset=(x, 1))
        await pilot.pause()
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_a_refused_edit_leaves_its_cell_and_the_selection_as_they_were() -> None:
    view = EditableTableMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.places.renderer, TextualWidgetRenderer)
    box = view.places.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    table = box.table

    def refuse(_row: int, _column: int, _text: str) -> None:
        raise EditRefusedError

    view.places.cell_edited.connect(refuse)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.click(table, offset=(2, 1))  # the lake's row
        await pilot.press("f2", *"Windy", "enter")
        await pilot.pause()
        assert view.places.rows == [["Lake", "Calm"], ["Harbour"]]
        assert [str(cell) for cell in table.get_row_at(0)] == ["Lake", "Calm"]
        assert view.places.selected_rows == [0]


def _sorted_rooms(
    view: Optional[SortedRoomsMainView] = None,
) -> tuple[SortedRoomsMainView, App[Any], ComposeFilterTable]:
    """Render the rooms (`view`, or new ones): set them up before, the app not yet running."""
    view = SortedRoomsMainView() if view is None else view
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.rooms.renderer, TextualWidgetRenderer)
    box = view.rooms.renderer.widget
    assert isinstance(box, ComposeFilterTable)
    return view, app, box


def _shown_column(table: ComposeTable, column: int) -> list[str]:
    return [str(table.get_row_at(row)[column]) for row in range(table.row_count)]


@pytest.mark.asyncio
async def test_clicking_a_sortable_header_sorts_by_it_then_back_and_marks_the_order() -> None:
    view, app, box = _sorted_rooms()
    table = box.table

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()

        async def click_header(column: int) -> None:
            x = sum(c.get_render_width(table) for c in list(table.columns.values())[:column])
            await pilot.click(table, offset=(x + 1, 0))
            await pilot.pause()

        await click_header(2)  # the occupants
        assert _shown_column(table, 2) == ["2", "9", "10", ""]
        assert str(list(table.columns.values())[2].label) == "Occupants ▲"
        await click_header(2)
        assert _shown_column(table, 2) == ["10", "9", "2", ""]
        assert str(list(table.columns.values())[2].label) == "Occupants ▼"
        await click_header(2)
        assert view.rooms.sort_column is None
        assert _shown_column(table, 0) == ["Hall", "kitchen", "Attic", "Bedroom"]
        assert str(list(table.columns.values())[2].label) == "Occupants"

        # a table sorting and filtering by no column: no bar
        assert isinstance(view.notes.renderer, TextualWidgetRenderer)
        notes = view.notes.renderer.widget
        assert isinstance(notes, ComposeFilterTable)
        assert not notes.bar.display
        assert box.bar.display


async def _add_filter(pilot: Pilot[Any], bar: ComposeFilterBar, option: int, text: str) -> None:
    """Add a filter through the bar's editor, on the column at `option` in its picker."""
    if not bar.is_editing():
        await pilot.click(bar.add_filter)
        await pilot.pause()
    # the column picker's options: a blank one, then the columns
    await pilot.click(bar.column)
    await pilot.pause()
    await pilot.press("home", *["down"] * (option + 1), "enter")
    await pilot.click(bar.value)
    await pilot.press("end", *["backspace"] * len(bar.value.value), *text, "enter")
    await pilot.pause()


@pytest.mark.asyncio
async def test_the_filter_bar_searches_and_adds_filters_shown_as_chips() -> None:
    view, app, box = _sorted_rooms()
    bar, table = box.bar, box.table

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(bar.search)
        await pilot.press(*"ROOM")
        await pilot.pause()
        assert view.rooms.search == ""  # once the user stops typing: one search, not four
        await pilot.pause(SEARCH_DELAY_MS / 1000 * 2)
        assert _shown_column(table, 0) == ["Bedroom"]
        assert str(bar.count.render()) == "1 of 4"
        await pilot.press(*["backspace"] * 4)
        await pilot.pause()
        assert table.row_count == 4
        assert not bar.count.display

        # a value that doesn't parse isn't added: the field says why, the editor stays
        await _add_filter(pilot, bar, 1, "warm")  # the temperature
        assert bar.is_editing()
        assert bar.value.has_class("-invalid")
        assert str(bar.value.tooltip) == '"warm" isn\'t a number'
        assert bar.value.placeholder == ">=20, 18..24"
        await _add_filter(pilot, bar, 1, ">=20")
        assert not bar.is_editing()
        assert _shown_column(table, 0) == ["kitchen", "Bedroom"]
        (chip,) = bar.chips.query(ComposeFilterChip)
        assert str(chip.open_button.label) == "Temperature: >=20 \u270e"
        assert str(chip.open_button.tooltip) == "Edit the filter on Temperature"
        # its chip has the focus: Enter opens it again, to replace the filter on its
        # column; another column's combines
        assert app.focused is chip.open_button
        await pilot.press("enter")
        await pilot.pause()
        assert bar.value.value == ">=20"
        await _add_filter(pilot, bar, 1, ">=21")
        await _add_filter(pilot, bar, 3, "true")  # heated
        assert view.rooms.filters == {1: ">=21", 3: "true"}
        assert _shown_column(table, 0) == ["Bedroom"]

        chips = list(bar.chips.query(ComposeFilterChip))
        await pilot.click(chips[0].remove_button)
        await pilot.pause()
        assert view.rooms.filters == {3: "true"}
        await _add_filter(pilot, bar, 2, ">100")  # occupants
        assert table.row_count == 0
        assert box.empty.display
        assert str(box.empty.render()) == "No rows match the filters"
        # Escape closes the editor, adding nothing
        await pilot.click(bar.add_filter)
        await pilot.pause()
        await pilot.press(*"=", "escape")
        await pilot.pause()
        assert not bar.is_editing()
        assert view.rooms.filters == {2: ">100", 3: "true"}


@pytest.mark.asyncio
async def test_the_filter_editor_s_toggle_makes_the_value_a_regular_expression() -> None:
    view, app, box = _sorted_rooms()
    bar, table = box.bar, box.table

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(bar.add_filter)
        await pilot.pause()
        # only for text, the first column: a number column takes comparisons
        assert bar.pattern.display
        await pilot.click(bar.pattern)
        await pilot.pause()
        assert bar.value.placeholder == "a regular expression, as Room [1-3]"
        await pilot.click(bar.value)
        await pilot.press(*"^(hall|attic)$", "enter")
        await pilot.pause()
        assert _shown_column(table, 0) == ["Hall", "Attic"]
        (chip,) = bar.chips.query(ComposeFilterChip)
        assert str(chip.open_button.label) == "Room matches ^(hall|attic)$ \u270e"

        # reopened, the toggle is on and the value the pattern as typed
        await pilot.press("enter")
        await pilot.pause()
        assert bar.is_pattern()
        assert bar.value.value == "^(hall|attic)$"
        await _add_filter(pilot, bar, 1, ">=20")  # the temperature
        assert not bar.pattern.display
        assert view.rooms.filters == {0: "/^(hall|attic)$/", 1: ">=20"}


@pytest.mark.asyncio
async def test_a_click_and_an_edit_on_a_sorted_filtered_table_reach_their_rows() -> None:
    view = SortedRoomsMainView()
    rooms = view.rooms
    rooms.filters = {3: "true"}
    rooms.sort_by(0)
    rooms.sort_by(0)  # descending: the kitchen, then the bedroom
    view, app, box = _sorted_rooms(view)
    table = box.table
    emitted: list[list[int]] = []
    rooms.selection_changed.connect(emitted.append)
    edited: list[tuple[Room, Room]] = []
    rooms.record_edited.connect(lambda old, new: edited.append((old, new)))

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        # the header, then the rows: the bedroom is the second
        await pilot.click(table, offset=(2, 2))
        await pilot.pause()
        assert rooms.selected_records == [Room("Bedroom", 21, 9, is_heated=True)]
        assert emitted == [[3]]

        # renamed, the bedroom sorts first and stays selected
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("end", *["backspace"] * len("Bedroom"), *"Study", "enter")
        await pilot.pause()
        assert edited == [
            (Room("Bedroom", 21, 9, is_heated=True), Room("Study", 21, 9, is_heated=True))
        ]
        assert _shown_column(table, 0) == ["Study", "kitchen"]
        assert rooms.selected_rows == [3]
        assert table.cursor_row == 0


@pytest.mark.asyncio
async def test_a_large_table_draws_the_lines_on_screen_reading_only_their_windows() -> None:
    view = MillionRowsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    source = view.table.source
    assert isinstance(source, MillionSource)

    async with app.run_test(size=(80, 30)) as pilot:
        table = app.query_one(ComposeSourceTable)
        assert table.virtual_size.height == 1_000_001  # the headers' line, then the rows'
        assert table.render_line(0).text.split() == ["Value", "Half"]
        assert table.render_line(2).text.split() == ["2", "2", "0.5"]
        table.scroll_to(y=500_000, animate=False)
        await pilot.pause()
        assert table.render_line(1).text.split() == ["500,001", "1000000", "250000.0"]
        assert table.render_line(0).text.split() == ["Value", "Half"]  # still on top
        assert len(source.read) < 10 * SOURCE_TABLE_WINDOW

        source.size = 3
        source.changed.emit()
        await pilot.pause()
        assert table.virtual_size.height == 4


@pytest.mark.asyncio
async def test_a_large_table_s_header_clicks_sort_by_its_column_marking_the_order() -> None:
    view = MillionRowsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 30)) as pilot:
        table = app.query_one(ComposeSourceTable)
        # the positions take "1,000,000 ", the two columns share the 70 cells left
        half = (len("1,000,000 ") + 35 + 2, 0)
        await pilot.click(ComposeSourceTable, offset=half)
        assert (view.table.sort_column, view.table.sort_descending) == ("half", False)
        assert table.render_line(0).text.split() == ["Value", "Half", "▲"]
        await pilot.click(ComposeSourceTable, offset=half)
        assert table.render_line(0).text.split() == ["Value", "Half", "▼"]
        await pilot.click(ComposeSourceTable, offset=(3, 0))  # over the positions: nothing
        await pilot.click(ComposeSourceTable, offset=(15, 2))  # on a row: nothing
        assert view.table.sort_column == "half"


@pytest.mark.asyncio
async def test_a_large_table_s_cursor_and_clicks_select_its_rows_and_activate_one() -> None:
    view = MillionRowsMainView()
    view.table.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    activated: list[Any] = []
    view.table.row_activated.connect(activated.append)

    async with app.run_test(size=(80, 30)) as pilot:
        table = app.query_one(ComposeSourceTable)
        table.focus()
        await pilot.press("down", "down", "space", "down", "down", "shift+space", "enter")
        assert view.table.selected_ids == [2, 3, 4]
        assert activated == [4]

        await pilot.click(ComposeSourceTable, offset=(15, 1))  # the first row's line
        await pilot.click(ComposeSourceTable, offset=(15, 3))  # the selected third: off
        await pilot.double_click(ComposeSourceTable, offset=(15, 7))
        assert view.table.selected_ids == [3, 4, 0, 6]
        assert activated == [4, 6]

        await pilot.press("end")
        assert table.cursor == 999_999
        last = table.scrollable_content_region.height - 1
        assert table.render_line(last).text.split()[0] == "1,000,000"
        await pilot.press("home")  # back up: scrolled to the first row
        assert table.render_line(1).text.split()[0] == "1"


@pytest.mark.asyncio
async def test_a_large_table_s_bar_searches_and_filters_its_columns_by_name() -> None:
    view = RoomsDataMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        box = app.query_one(ComposeDataFilterTable)
        bar = box.bar
        assert bar.display
        await pilot.click(bar.search)
        await pilot.press(*"room", "enter")  # searches at once
        await pilot.pause()
        assert (view.rooms.search, view.rooms.row_count) == ("room", 1)
        assert str(bar.count.render()) == "1 of 3"
        await pilot.press(*["backspace"] * 4)
        await pilot.pause()

        await _add_filter(pilot, bar, 1, "warm")  # the temperature: by the column's name
        assert str(bar.value.tooltip) == '"warm" isn\'t a number'
        await _add_filter(pilot, bar, 1, ">19")
        assert view.rooms.filters == {"temperature": ">19"}
        assert view.rooms.row_count == 2
        (chip,) = bar.chips.query(ComposeFilterChip)
        assert str(chip.open_button.label) == "Temperature: >19 \u270e"

        view.rooms.filters = {"temperature": ">30"}
        await pilot.pause()
        assert box.empty.display
        (chip,) = bar.chips.query(ComposeFilterChip)
        await pilot.click(chip.remove_button)
        await pilot.pause()
        assert (view.rooms.filters, view.rooms.row_count, box.empty.display) == ({}, 3, False)


@pytest.mark.asyncio
async def test_ctrl_c_copies_a_large_table_s_selected_rows_to_the_clipboard() -> None:
    view = MillionRowsMainView()
    view.table.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 30)) as pilot:
        app.query_one(ComposeSourceTable).focus()
        await pilot.press("down", "space", "down", "down", "space", "ctrl+c")
        await pilot.pause()
        # the value, then its half
        assert app.clipboard == "2\t0.5\n6\t1.5"


@pytest.mark.asyncio
async def test_a_large_source_s_rows_show_loading_while_a_job_orders_them() -> None:
    view = GatedMainView()
    view.render(RendererType.TEXTUAL)
    _add_reference_to_signals(view, None)  # as the app does: the table finds the jobs
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    source = view.table.source
    assert isinstance(source, GatedSource)

    async with app.run_test(size=(80, 30)) as pilot:
        table = app.query_one(ComposeSourceTable)
        source.gate.clear()
        view.table.sort_by("value")
        view.table.sort_by("value")  # descending, while the job orders
        await pilot.pause()
        assert table.loading

        source.gate.set()
        for _ in range(100):
            await pilot.pause(0.05)
            if not view.table.is_ordering:
                break
        assert not table.loading
        assert view.table.rows(0, 1) == [(source.size - 1, [str(source.size - 1)])]


@pytest.mark.asyncio
async def test_a_large_table_s_cell_shows_on_its_row_s_line_its_breaks_as_spaces() -> None:
    view = RoomsDataMainView()
    view.rooms.source = ListSource(
        Room, {"name": T("Room"), "temperature": T("Temperature")}, [Room("Hall\tway\nB", 18.0)]
    )
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        line = app.query_one(ComposeSourceTable).render_line(1).text

    assert "Hall way B" in line
    assert line.split() == ["1", "Hall", "way", "B", "18.0"]


@pytest.mark.asyncio
@pytest.mark.parametrize("is_cancelled", [False, True])
async def test_a_large_table_s_key_exports_its_rows_as_csv(
    is_cancelled: bool,
    tmp_path: Path,
) -> None:
    view = RoomsDataMainView()
    view.rooms.sort_column = "temperature"
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 30)) as pilot:
        app.query_one(ComposeSourceTable).focus()
        await pilot.pause()
        footer = [binding.description for (_, binding, *_rest) in app.active_bindings.values()]
        assert "Export CSV" in footer

        await pilot.press("e")
        await pilot.pause()
        assert [type(screen).__name__ for screen in app.screen_stack] == ["Screen", "FileSave"]
        # as the dialog's Save button does, or Cancel
        app.screen.dismiss(None if is_cancelled else tmp_path / "rooms")
        await pilot.pause()

    if is_cancelled:
        assert _names(tmp_path) == []
        return
    assert (tmp_path / "rooms.csv").read_text(encoding="utf-8").splitlines() == [
        "Room,Temperature,Occupants",
        "Hall,18.0,",
        "Bedroom,19.5,1",
        "Kitchen,21.5,2",
    ]


@pytest.mark.asyncio
async def test_a_check_box_column_leaves_its_header_and_cells_once_a_plain_one() -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.variables.renderer, TextualWidgetRenderer)
    box = view.variables.renderer.widget
    assert isinstance(box, ComposeFilterTable)

    def header() -> str:
        return str(next(iter(box.table.columns.values())).label)

    def first_cell() -> str:
        return str(box.table.get_cell_at(Coordinate(0, 0)))

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        boxed = (header(), first_cell())
        view.variables.cell_widgets = {2: CellWidget.combobox(["Input", "Output"])}
        await pilot.pause()

        # its cells too: drawn with the widgets the view holds
        assert [boxed, (header(), first_cell())] == [("▣ Keep", "☑"), ("Keep", "True")]


@pytest.mark.asyncio
async def test_a_header_s_click_sorts_or_checks_only_a_column_that_allows_it() -> None:
    rooms, rooms_app, rooms_box = _sorted_rooms()
    rooms.rooms.sortable_columns = [2]
    async with rooms_app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(rooms_box.table, offset=(1, 0))  # the room's
        await pilot.pause()
        assert rooms.rooms.sort_column is None

    view = CellWidgetsMainView()
    view.variables.editable_columns = []
    app = _app_of(view)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.click(_widget(view.variables), offset=(1, 0))  # the box
        await pilot.pause()
        assert [row[0] for row in view.variables.rows] == ["True", "false"]


@pytest.mark.asyncio
async def test_the_filter_bar_clears_its_filters_and_shows_a_search_set_in_code() -> None:
    view = SortedRoomsMainView()
    view.rooms.filters = {1: ">=20", 3: "true"}  # the bar clears two or more
    view, app, box = _sorted_rooms(view)

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(box.bar.clear)
        await pilot.pause()
        view.rooms.search = "kit"
        await pilot.pause()

        assert view.rooms.filters == {}
        assert box.bar.search.value == "kit"


@pytest.mark.asyncio
async def test_a_table_s_picker_closes_on_escape_and_a_disabled_box_ignores_space() -> None:
    view = CellWidgetsMainView()
    view.variables.cell_styles = {(0, 0): CellStyle(is_enabled=False)}
    app = _app_of(view)
    box = _widget(view.variables)
    assert isinstance(box, ComposeFilterTable)
    table = box.table
    edits: list[tuple[int, int, str]] = []
    view.variables.cell_edited.connect(lambda row, column, text: edits.append((row, column, text)))

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        first = next(iter(table.columns.values())).get_render_width(table)
        await pilot.click(table, offset=(first + 1, 1))  # the first row's name
        await pilot.press("space")  # its box, disabled
        await pilot.press("f2")  # no field typed in: the role's picker
        await pilot.pause()
        picked = isinstance(app.screen, ComposeOptionPicker)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("enter")  # the role it has
        await pilot.pause()

        assert picked
        assert not isinstance(app.screen, ComposeOptionPicker)
        assert edits == []
        assert view.variables.rows[0][:3] == ["True", "Length", "Input"]


@pytest.mark.asyncio
async def test_a_large_table_without_rows_answers_no_key_or_click() -> None:
    view = RoomsDataMainView()
    view.rooms.filters = {"temperature": ">30"}
    activated: list[Any] = []
    view.rooms.row_activated.connect(activated.append)
    app = _app_of(view)

    # 81 columns: the rows' numbers' 2, then 26 a header, one left over past the last
    async with app.run_test(size=(81, 30)) as pilot:
        table = app.query_one(ComposeSourceTable)
        table.focus()
        await pilot.press("space", "enter")
        await pilot.click(ComposeSourceTable, offset=(15, 1))
        await pilot.click(ComposeSourceTable, offset=(80, 0))
        await pilot.pause()

        assert (view.rooms.selected_ids, activated, view.rooms.sort_column) == ([], [], None)


@define_view
class _EmptyDataMainView(MainView):
    app_title = "Empty"
    extension = ".empty"

    table: SourceTableView = Factory(SourceTableView)  # no source: no column


@pytest.mark.asyncio
async def test_a_large_table_without_columns_draws_its_lines_empty() -> None:
    app = _app_of(_EmptyDataMainView())

    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        table = app.query_one(ComposeSourceTable)

        assert table.render_line(0).text.strip() == ""


@pytest.mark.asyncio
async def test_a_table_emptied_under_its_cursor_answers_no_key() -> None:
    view = CellWidgetsMainView()
    app = _app_of(view)
    places_view = EditableTableMainView()
    places_app = _app_of(places_view)
    edits: list[tuple[int, int, str]] = []
    view.variables.cell_edited.connect(lambda row, column, text: edits.append((row, column, text)))

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = _widget(view.variables)
        assert isinstance(table, ComposeFilterTable)
        name = next(iter(table.table.columns.values())).get_render_width(table.table) + 1
        await pilot.click(table.table, offset=(name, 1))  # the cursor shown, on the first row
        view.variables.rows = []  # e.g. its records deleted
        await pilot.pause()
        await pilot.press("space", "f2")
        await pilot.pause()
        assert not isinstance(app.screen, ComposeOptionPicker)
    async with places_app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        places = _widget(places_view.places)
        assert isinstance(places, ComposeFilterTable)
        await pilot.click(places.table, offset=(2, 1))
        places_view.places.rows = []
        await pilot.pause()
        await pilot.press("f2")
        await pilot.pause()
        assert not isinstance(places_app.screen, ComposeRowEditor)

    assert edits == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("removes", "expected"),
    [(False, [["b", "2"], ["za", "91"]]), (True, [["b", "2"]])],
)
async def test_a_row_s_edit_of_several_cells_stays_on_its_record(
    *, removes: bool, expected: list[list[str]]
) -> None:
    view = EditableTableMainView()
    view.places.editable_columns = [0, 1]
    view.places.rows = [["a", "1"], ["b", "2"]]
    app = _app_of(view)

    def answer(row: int, column: int, text: str) -> None:
        rows = replace_cell(view.places.rows, row, column, text)
        view.places.rows = [*rows[:row], *rows[row + 1 :]] if removes else sorted(rows)

    view.places.cell_edited.connect(answer)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = _widget(view.places)
        assert isinstance(table, ComposeFilterTable)
        await pilot.click(table.table, offset=(2, 1))
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("ctrl+a", "z", "tab", "ctrl+a", "9", "enter")
        await pilot.pause()

    assert view.places.rows == expected


@pytest.mark.asyncio
async def test_an_edit_whose_answer_empties_the_table_leaves_its_other_cells() -> None:
    view = EditableTableMainView()
    view.places.editable_columns = [0, 1]
    app = _app_of(view)
    edits: list[tuple[int, int, str]] = []

    def answer(row: int, column: int, text: str) -> None:
        edits.append((row, column, text))
        view.places.rows = []  # e.g. the edit deletes its record

    view.places.cell_edited.connect(answer)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = _widget(view.places)
        assert isinstance(table, ComposeFilterTable)
        await pilot.click(table.table, offset=(2, 1))
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("end", *"side", "tab", "end", *"er", "enter")
        await pilot.pause()

        assert edits == [(0, 0, "Lakeside")]  # the note's edit had no row left
        assert view.places.rows == []


@pytest.mark.asyncio
async def test_a_table_selecting_several_shows_its_cursor_first_and_checks_none_by_its_header() -> (
    None
):
    view = HorizontalMainView()
    table_view = view.tables.narrow
    table_view.selection_mode = SelectionMode.MULTIPLE
    app = _app_of(view)
    emitted: list[list[int]] = []
    table_view.selection_changed.connect(emitted.append)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        box = _widget(table_view)
        assert isinstance(box, ComposeFilterTable)
        await pilot.click(box.table, offset=(1, 0))  # the header of the selection's column
        box.table.focus()
        await pilot.press("enter")  # the cursor shows, selecting nothing yet
        await pilot.pause()
        shown = box.table.show_cursor
        table_view.rows = []
        await pilot.pause()
        await pilot.press("enter")  # no row under the cursor
        await pilot.pause()

        assert shown
        assert emitted == []


@pytest.mark.asyncio
async def test_the_filter_bar_offers_the_columns_set_before_the_app_runs_and_adds_by_button() -> (
    None
):
    view, app, box = _sorted_rooms()
    view.rooms.filterable_columns = [1, 2]  # the temperature and the occupants
    bar = box.bar

    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(bar.search)
        await pilot.press("enter")  # nothing typed since: no search
        await pilot.click(bar.add_filter)
        await pilot.pause()
        await pilot.click(bar.column)
        await pilot.pause()
        await pilot.press("home", "enter")  # the blank option: no column
        await pilot.pause()
        blank_placeholder = bar.value.placeholder
        await pilot.click(bar.add)  # nothing to add without a column
        await pilot.pause()
        await _add_filter(pilot, bar, 1, ">5")  # the second offered: the occupants

        assert blank_placeholder == ""
        assert view.rooms.search == ""
        assert view.rooms.filters == {2: ">5"}


@pytest.mark.asyncio
async def test_f2_on_a_row_whose_editable_cells_are_disabled_opens_nothing() -> None:
    view = CellWidgetsMainView()
    view.variables.cell_styles = {(0, 2): CellStyle(is_enabled=False)}  # its role
    app = _app_of(view)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        box = _widget(view.variables)
        assert isinstance(box, ComposeFilterTable)
        name = next(iter(box.table.columns.values())).get_render_width(box.table) + 1
        await pilot.click(box.table, offset=(name, 1))  # the first row
        await pilot.press("f2")
        await pilot.pause()

        assert not isinstance(app.screen, (ComposeOptionPicker, ComposeRowEditor))
