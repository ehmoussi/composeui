"""Tests of the web tables and their filter bars."""

from __future__ import annotations

import errno
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from markupsafe import escape

from composeui.core._views.tables import SOURCE_TABLE_WINDOW
from composeui.core.model import RefusedError
from composeui.core.registry import RendererType
from composeui.core.view import (
    CellWidget,
    EditRefusedError,
    SelectionMode,
    TableView,
    replace_cell,
)
from composeui.webcore._renderers.tables import WebTableRenderer
from composeui.webcore.session import WebSession
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import (
    WebRenderer,
    handle_event,
)
from examples.studyinputs import INPUT_FOLDER, OUTPUT_FILE, PATH, StudyInputsMainView
from tests.studyfiles import StudyFilesTableMainView, StudyPathsMainView
from tests.tables import (
    CellWidgetsMainView,
    DataFilesTableMainView,
    EditableTableMainView,
    MillionRowsMainView,
    MillionSource,
    Room,
    RoomsDataMainView,
    RoomsMainView,
    SortedRoomsMainView,
    StyledTablesMainView,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    if sys.version_info >= (3, 11):
        import httpx2 as httpx
    else:
        import httpx
    from starlette.testclient import TestClient

    from examples.pipeform import PipeMainView
    from tests.horizontal import HorizontalMainView


from tests.webcore.support import (
    _Browser,
    _element,
    _field_id,
    _find,
    _listed,
    _pick_cell_file,
    _shows_files,
    _swapped,
    _widget_id,
)


@pytest.fixture
def study_files(tmp_path: Path) -> Iterator[tuple[TestClient, StudyFilesTableMainView, Path]]:
    """Serve a table whose file path cells list the `.export` files of a folder of studies.

    Yield a client, its main view and the folder: `beam/beam.export`, `beam/beam.comm`.
    """
    root = tmp_path / "studies"
    (root / "beam").mkdir(parents=True)
    for name in ("beam.export", "beam.comm"):
        (root / "beam" / name).write_text("")
    views: list[StudyFilesTableMainView] = []

    class StudyFilesApp(WebApplication[StudyFilesTableMainView]):
        @override
        def setup_session(self, main_view: StudyFilesTableMainView) -> None:
            main_view.status_bar.timeout = 0
            main_view.inputs.cell_widgets = {
                1: CellWidget.file_path({"Code_Aster": (".export",)}, server_roots=(root,))
            }
            views.append(main_view)

    app = StudyFilesApp(build_main_view=StudyFilesTableMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield client, view, root


def test_a_table_s_file_path_with_server_roots_is_picked_among_their_files(
    study_files: tuple[TestClient, StudyFilesTableMainView, Path],
) -> None:
    client, view, root = study_files
    table = view.inputs
    renderer = table.renderer
    assert isinstance(renderer, WebTableRenderer)
    edits: list[tuple[int, int, str]] = []
    table.cell_edited.connect(lambda row, column, text: edits.append((row, column, text)))
    button = _element(renderer.to_html(), f"{renderer.widget_id}-cell-1-1").attributes
    assert json.loads(button["hx-vals"] or "") == {"event": "browse", "row": "1", "column": "1"}

    def post(event: str, **values: str) -> str:
        response: httpx.Response = client.post(
            f"/widget/{renderer.widget_id}", data={"event": event, **values}
        )
        return response.text

    body = post("browse", row="1", column="1")
    assert "hidden" not in _swapped(body, f"{renderer.widget_id}-files").attributes
    assert _listed(body, renderer) == [("browse-folder", "beam")]
    body = post("browse-folder", name="beam")
    assert _listed(body, renderer) == [("browse-parent", ""), ("browse-file", "beam.export")]
    assert _find(body, f"{renderer.widget_id}-files") is None  # only the list swaps

    body = post("browse-file", name="beam.export")

    # as the user's edit of the cell the list opened for
    path = str(root.resolve() / "beam" / "beam.export")
    assert edits == [(1, 1, path)]
    assert table.rows[1] == ["Commands", path]
    assert path in _swapped(body, f"{renderer.widget_id}-body").text  # the cell shows it
    assert "hidden" in _swapped(body, f"{renderer.widget_id}-files").attributes
    # opened again: in the folder of the cell's file
    assert _listed(post("browse", row="1", column="1"), renderer)[-1] == (
        "browse-file",
        "beam.export",
    )
    post("browse-close")
    assert not _shows_files(renderer)


def test_a_table_s_path_by_kind_lists_the_study_as_each_row_s_kind_picks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study, elsewhere = tmp_path / "study", tmp_path / "elsewhere"
    (study / "inputs" / "materials").mkdir(parents=True)
    (study / "summary.txt").write_text("")
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # the process started in another folder
    views: list[StudyInputsMainView] = []

    class StudyInputsApp(WebApplication[StudyInputsMainView]):
        @override
        def setup_session(self, main_view: StudyInputsMainView) -> None:
            main_view.status_bar.timeout = 0
            main_view.show_study(study)
            views.append(main_view)

    app = StudyInputsApp(build_main_view=StudyInputsMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        table = view.files
        renderer = table.renderer
        assert isinstance(renderer, WebTableRenderer)

        def post(event: str, **values: str) -> str:
            response: httpx.Response = client.post(
                f"/widget/{renderer.widget_id}", data={"event": event, **values}
            )
            return response.text

        def path(row: int) -> str:
            return table.rows[row][PATH]

        # a folder: its list of folders, from the cell's own, picking the folder shown
        body = post("browse", row="1", column=str(PATH))
        assert _listed(body, renderer) == [("browse-parent", "")]
        post("browse-file", name="materials")  # a file's event: not this list's
        post("browse-parent")
        post("browse-choose")
        assert path(1) == "inputs"
        # a file to save: in the study, the name typed, a file that exists replaced once agreed
        post("browse", row="2", column=str(PATH))
        post("browse-save", name="summary")
        assert path(2) == "report.txt"
        post("browse-replace")
        assert path(2) == "summary.txt"
        # the kind picked: the path cell's widget follows, and the body swaps to show it
        body = post("pick", row="3", column="1", text=OUTPUT_FILE)
        assert _find(body, f"{renderer.widget_id}-body") is not None
        post("browse", row="3", column=str(PATH))
        post("browse-save", name="totals")
        assert path(3) == "totals.txt"
        # typed: from the study, and refused out of it, `..` followed
        for text, shown in [(str(Path("inputs", "mesh.med")), True), ("../elsewhere/x.med", False)]:
            for event in ("start_edit", "edit"):
                post(event, row="0", column=str(PATH), text=text)
            assert (path(0) == text) == shown, text
        # without roots, the browser can't give a folder's path: typed, without a button
        table.cell_widgets = {
            **table.cell_widgets,
            PATH: CellWidget.path_by(1, {INPUT_FOLDER: CellWidget.folder_path()}),
        }
        cell = _element(renderer.to_html(), f"{renderer.widget_id}-row-1")
        assert [tag for tag, _attributes in cell.descendants if tag == "button"] == []


@pytest.fixture
def study_paths(tmp_path: Path) -> Iterator[tuple[TestClient, StudyPathsMainView, Path]]:
    """Serve a table whose `cell_widget` picks a file in its first row, a folder in its second.

    Without roots, until a test gives the folder that it yields, with `beam/` and `beam.med`,
    after a client and its main view.
    """
    (tmp_path / "beam").mkdir()
    (tmp_path / "beam.med").write_text("")
    views: list[StudyPathsMainView] = []

    class StudyPathsApp(WebApplication[StudyPathsMainView]):
        @override
        def setup_session(self, main_view: StudyPathsMainView) -> None:
            main_view.status_bar.timeout = 0
            views.append(main_view)

    app = StudyPathsApp(build_main_view=StudyPathsMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield client, view, tmp_path


def test_a_table_s_cell_widget_of_each_row_lists_its_own_server_files(
    study_paths: tuple[TestClient, StudyPathsMainView, Path],
) -> None:
    client, view, root = study_paths
    renderer = view.inputs.renderer
    assert isinstance(renderer, WebTableRenderer)

    def post(event: str, **values: str) -> str:
        response: httpx.Response = client.post(
            f"/widget/{renderer.widget_id}", data={"event": event, **values}
        )
        return response.text

    files_id = f"{renderer.widget_id}-files"
    assert _find(client.get("/").text, files_id) is None  # nothing lists the server's files
    # roots given, the rows as they were: the page, not drawn again, lacks the list, so the
    # whole table brings it
    view.inputs.show_paths(view.inputs.rows, folders=[1], roots=[root])
    body = post("browse", row="0", column="1")
    table = _swapped(body, renderer.widget_id)
    assert any(a.get("id") == files_id for _tag, a in table.descendants)
    assert _listed(body, renderer) == [("browse-folder", "beam"), ("browse-file", "beam.med")]
    post("browse-file", name="beam.med")
    # a page drawn since has it, closed, as for a column's widget
    assert _find(client.get("/").text, files_id) is not None
    # the rows are named alike: only the table's `cell_widget` tells them apart
    body = post("browse", row="1", column="1")
    assert _listed(body, renderer) == [("browse-folder", "beam")]
    post("browse-choose")
    assert view.inputs.rows == [["Mesh", str(root / "beam.med")], ["Mesh", str(root)]]


def test_a_table_s_cell_widget_s_uploads_are_kept_while_their_cells_hold_them(
    study_paths: tuple[TestClient, StudyPathsMainView, Path],
) -> None:
    client, view, _root = study_paths
    table = view.inputs
    table.show_paths(table.rows, folders=[])  # two files, uploaded
    table_id = _widget_id(table.renderer)

    for row in ("0", "1"):
        response = client.post(
            f"/widget/{table_id}/file",
            data={"row": row, "column": "1"},
            files={"file": (f"mesh{row}.med", b"1", "application/octet-stream")},
        )
        assert response.status_code == 200

    # the second upload dropped no copy a cell holds, though no column declares one
    assert [Path(cells[1]).exists() for cells in table.rows] == [True, True]


def test_a_table_s_file_path_typed_outside_its_server_roots_is_refused(
    study_files: tuple[TestClient, StudyFilesTableMainView, Path],
) -> None:
    client, view, root = study_files
    table = view.inputs
    renderer = table.renderer
    assert isinstance(renderer, WebTableRenderer)
    view.set_language("fr")

    def type_path(text: str) -> None:
        for event in ("start_edit", "edit"):
            data = {"event": event, "row": "0", "column": "1", "text": text}
            client.post(f"/widget/{renderer.widget_id}", data=data)

    for text in ("/etc/passwd", str(root / "beam" / ".." / ".."), "a\0b"):
        type_path(text)
        assert table.rows[0] == ["Mesh", ""], text  # the cell keeps its text
    assert view.notification.message == (
        "Impossible de prendre a\0b : il n'est pas dans les dossiers que liste cette colonne."
    )
    inside = str(root / "beam" / "beam.comm")
    type_path(inside)  # any file inside the roots, as typed
    assert table.rows[0] == ["Mesh", inside]
    type_path("")
    assert table.rows[0] == ["Mesh", ""]


def test_a_table_s_server_files_open_only_for_a_cell_the_user_can_edit(
    study_files: tuple[TestClient, StudyFilesTableMainView, Path],
) -> None:
    client, view, _root = study_files
    table = view.inputs
    renderer = table.renderer
    assert isinstance(renderer, WebTableRenderer)

    def post(event: str, **values: str) -> int:
        data = {"event": event, **values}
        response: httpx.Response = client.post(f"/widget/{renderer.widget_id}", data=data)
        return response.status_code

    for row, column in (("0", "0"), ("9", "1"), ("x", "1")):  # no path, no row, no number
        post("browse", row=row, column=column)
    table.editable_columns = []
    post("browse", row="0", column="1")
    assert not _shows_files(renderer)
    assert post("browse-close") == 400  # closed: nothing to move in

    table.editable_columns = [1]
    post("browse", row="0", column="1")
    assert _shows_files(renderer)
    # its column no longer lists the server's files: it closes, picking nothing
    table.cell_widgets = {1: CellWidget.file_path({"Code_Aster": (".export",)})}
    post("browse-folder", name="beam")
    assert not _shows_files(renderer)
    assert table.rows[0] == ["Mesh", ""]
    table.cell_widgets = {1: CellWidget.file_path(server_roots=(_root,))}
    post("browse", row="0", column="1")
    table.is_enabled = False
    assert not _shows_files(renderer)  # nothing to pick in a disabled table


def test_finishing_a_dimension_edit_updates_the_summary_table(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    radius_id = _field_id(pipe_main_view.pages.inputs.pipe_form.main_pipe.radius)
    pipe_client.get("/results")  # built once shown, then left
    summary_id = _widget_id(pipe_main_view.pages.results.summary.renderer)
    pipe_client.get("/inputs")

    pipe_client.post(f"/widget/{radius_id}", data={"value": "35", "event": "change"})

    summary = _element(pipe_client.get("/results").text, summary_id)
    assert [tag for tag, _ in summary.descendants].count("th") == 4
    assert "Main Pipe352020" in summary.text  # the main pipe's row, cell after cell


def _rows_with(markup: str, table_id: str, attribute: str) -> list[str | None]:
    """Ids of the swapped table's rows whose `attribute` is true."""
    rows = [attributes for _, attributes in _swapped(markup, table_id).descendants]
    return [row["id"] for row in rows if row.get(attribute) == "true"]


def test_clicking_a_table_row_selects_it_and_swaps_the_table_to_show_it(
    tables: tuple[TestClient, HorizontalMainView],
) -> None:
    client, view = tables
    table = view.tables.narrow
    table_id = _widget_id(table.renderer)
    emitted: list[list[int]] = []
    table.selection_changed.connect(emitted.append)

    def select(row: str) -> Any:
        return client.post(f"/widget/{table_id}", data={"event": "select", "row": row})

    body = select("1").text
    assert table.selected_rows == [1]
    assert emitted == [[1]]
    assert _rows_with(body, table_id, "aria-current") == [f"{table_id}-row-1"]

    select("1")  # the selected row again
    assert emitted == [[1]]

    # a row a stale page still shows: the table comes back as it now is
    body = select("7").text
    assert table.selected_rows == [1]
    assert _rows_with(body, table_id, "aria-current") == [f"{table_id}-row-1"]

    table.is_enabled = False
    assert select("2").status_code == 400
    assert table.selected_rows == [1]
    assert emitted == [[1]]


def test_activating_a_table_row_emits_it_leaving_the_selection_to_its_click(
    tables: tuple[TestClient, HorizontalMainView],
) -> None:
    client, view = tables
    table = view.tables.narrow
    table_id = _widget_id(table.renderer)
    activated: list[int] = []
    table.row_activated.connect(activated.append)

    def activate(row: str) -> Any:
        return client.post(f"/widget/{table_id}", data={"event": "activate_row", "row": row})

    activate("2")
    assert activated == [2]
    assert table.selected_rows == []

    # a row a stale page still shows: the table comes back as it now is
    _swapped(activate("7").text, table_id)
    table.is_enabled = False
    assert activate("1").status_code == 400
    assert activated == [2]


def test_each_click_adds_or_removes_its_row_in_a_table_selecting_several(
    tables: tuple[TestClient, HorizontalMainView],
) -> None:
    client, view = tables
    table = view.tables.narrow
    table.selection_mode = SelectionMode.MULTIPLE
    table_id = _widget_id(table.renderer)
    emitted: list[list[int]] = []
    table.selection_changed.connect(emitted.append)

    def select(row: str) -> str:
        response: httpx.Response = client.post(
            f"/widget/{table_id}", data={"event": "select", "row": row}
        )
        return response.text

    page = client.get("/").text
    grid = next(tag for tag in _element(page, table_id).descendants if tag[0] == "table")
    assert grid[1]["role"] == "grid"
    assert grid[1]["aria-multiselectable"] == "true"

    select("2")
    body = select("0")
    assert table.selected_rows == [0, 2]
    assert _rows_with(body, table_id, "aria-selected") == [f"{table_id}-row-{i}" for i in (0, 2)]
    assert _rows_with(body, table_id, "aria-current") == []
    body = select("2")
    assert table.selected_rows == [0]
    assert _rows_with(body, table_id, "aria-selected") == [f"{table_id}-row-0"]
    assert emitted == [[2], [0, 2], [0]]


class _Places(NamedTuple):
    """The editable table's view and its fragment's id, a client, and the edits emitted."""

    client: TestClient
    table: TableView
    table_id: str
    edited: list[tuple[int, int, str, list[str]]]

    def post(self, event: str, row: str, column: str, text: str = "") -> Any:
        data = {"event": event, "row": row, "column": column, "text": text}
        return self.client.post(f"/widget/{self.table_id}", data=data)

    def edit(self, row: str, column: str, text: str) -> str:
        """Edit a cell as the user does, and return the table the edit swaps back."""
        self.post("start_edit", row, column)
        return str(self.post("edit", row, column, text).text)

    def fields(self, markup: str) -> list[dict[str, str | None]]:
        descendants = _swapped(markup, self.table_id).descendants
        return [attributes for tag, attributes in descendants if tag == "input"]

    def texts(self, markup: str) -> list[str]:
        return [_element(markup, f"{self.table_id}-row-{row}").text for row in range(2)]


def _editable_cells(markup: str, table_id: str) -> int:
    descendants = _element(markup, table_id).descendants
    return sum("data-edit" in attributes for _, attributes in descendants)


@pytest.fixture
def places() -> Iterator[_Places]:
    """Serve an app with an editable table, recording each edit with its row as it was."""
    views: list[EditableTableMainView] = []

    class PlacesApp(WebApplication[EditableTableMainView]):
        @override
        def setup_session(self, main_view: EditableTableMainView) -> None:
            views.append(main_view)

    app = PlacesApp(build_main_view=EditableTableMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        table = view.places
        edited: list[tuple[int, int, str, list[str]]] = []

        def record(row: int, column: int, text: str) -> None:
            # the row as it was: the edit is applied once the callbacks have run
            edited.append((row, column, text, table.rows[row]))

        table.cell_edited.connect(record)
        yield _Places(client, table, _widget_id(table.renderer), edited)


def test_editing_a_cell_swaps_in_its_field_until_its_text_is_posted(places: _Places) -> None:
    table, table_id = places.table, places.table_id
    applied: list[tuple[int, int, str, list[str]]] = []
    table.cell_edit_applied.connect(
        lambda row, column, text: applied.append((row, column, text, table.rows[row]))
    )
    page = places.client.get("/").text
    # only the notes are editable, the harbour's too though its row is short of it
    assert _editable_cells(page, table_id) == 2

    table.selected_rows = [1]
    (field,) = places.fields(places.post("start_edit", "1", "1").text)
    assert (field["aria-label"], field["value"]) == ("Note", "")
    assert "autofocus" in field
    body = places.post("edit", "1", "1", "Busy").text
    assert table.rows == [["Lake", "Calm"], ["Harbour", "Busy"]]
    assert places.edited == [(1, 1, "Busy", ["Harbour"])]
    # then the row holds the edit
    assert applied == [(1, 1, "Busy", ["Harbour", "Busy"])]
    # the row moved nowhere: it stays selected
    assert table.selected_rows == [1]
    # the cell is text again
    assert places.fields(body) == []
    assert places.texts(body) == ["LakeCalm", "HarbourBusy"]
    # a cell no field is editing takes no text: e.g. leaving the field after Enter
    places.post("edit", "1", "1", "Busy")
    places.post("edit", "0", "1", "Pond")
    assert table.rows == [["Lake", "Calm"], ["Harbour", "Busy"]]
    assert len(places.edited) == 1

    # the place isn't editable, and the row a stale page shows is gone: the table
    # comes back as it now is, no field in it
    for row, column in (("0", "0"), ("7", "1")):
        assert places.fields(places.post("start_edit", row, column).text) == []

    # disabled, the notes are text only, and a stale page's posts are refused
    table.is_enabled = False
    assert _editable_cells(places.client.get("/").text, table_id) == 0
    assert places.post("start_edit", "0", "1").status_code == 400


def test_rows_answering_an_edit_are_shown_its_row_still_selected(places: _Places) -> None:
    table, table_id = places.table, places.table_id

    def answer(row: int, column: int, text: str) -> None:
        if text == "Windy":  # applied, the rows sorted by note: the lake moves last
            rows = replace_cell(table.rows, row, column, text)
            table.rows = sorted(rows, key=lambda cells: cells[1:])
        else:
            raise EditRefusedError

    table.cell_edited.connect(answer)
    table.selected_rows = [0]
    body = places.edit("0", "1", "Windy")
    assert table.rows == [["Harbour"], ["Lake", "Windy"]]
    assert _rows_with(body, table_id, "aria-current") == [f"{table_id}-row-1"]
    assert places.texts(places.edit("1", "1", "Foggy")) == ["Harbour", "LakeWindy"]
    assert len(places.edited) == 2


def test_a_refusal_in_an_edit_refuses_it_and_says_why(places: _Places) -> None:
    table = places.table
    rows = table.rows

    def refuse(_row: int, _column: int, _text: str) -> None:
        reason = "too foggy"
        with table.refusing("Can't note it: {error}"):
            raise RefusedError(reason)

    table.cell_edited.connect(refuse)
    body = places.edit("1", "1", "Foggy")

    assert table.rows == rows
    assert "Foggy" not in "".join(places.texts(body))
    assert escape("Can't note it: too foggy") in body


def test_a_record_table_shows_an_edit_as_its_new_record_or_refuses_it() -> None:
    views: list[RoomsMainView] = []

    class RoomsApp(WebApplication[RoomsMainView]):
        @override
        def setup_session(self, main_view: RoomsMainView) -> None:
            views.append(main_view)

    with _Browser(RoomsApp(build_main_view=RoomsMainView).create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        rooms = _Places(client, view.rooms, _widget_id(view.rooms.renderer), [])

        # the new record's cell, not the text as typed
        assert rooms.texts(rooms.edit("1", "1", "21")) == ["Hall18False", "Kitchen21.02True"]
        assert view.rooms.records[1] == Room("Kitchen", 21.0, 2, is_heated=True)
        body = rooms.edit("1", "1", "warm")
        assert rooms.texts(body) == ["Hall18False", "Kitchen21.02True"]
        assert escape('Temperature: "warm" isn\'t a valid value') in body


def test_a_table_s_cells_and_headers_look_as_the_view_says() -> None:
    views: list[StyledTablesMainView] = []

    class ResultsApp(WebApplication[StyledTablesMainView]):
        @override
        def setup_session(self, main_view: StyledTablesMainView) -> None:
            views.append(main_view)

    app = ResultsApp(build_main_view=StyledTablesMainView)
    with _Browser(app.create_starlette_app()) as client:
        page = client.get("/").text
        (view,) = views
        table_id = _widget_id(view.points.renderer)

        def cells(row: int) -> list[dict[str, str | None]]:
            element = _element(page, f"{table_id}-row-{row}")
            return [attributes for tag, attributes in element.descendants if tag == "td"]

        # "Coordinates" over its two columns, the others' headers across both rows
        head = _element(page, f"{table_id}-head")
        spans = [
            (attributes.get("colspan"), attributes.get("rowspan"))
            for tag, attributes in head.descendants
            if tag == "th"
        ]
        assert spans == [
            (None, "2"),
            (None, "2"),
            ("2", None),
            (None, "2"),
            (None, None),
            (None, None),
        ]
        assert "Coordinates" in head.text
        # the group's cell covers its two points: the second row has no cell of its own
        assert cells(0)[0].get("rowspan") == "2"
        assert len(cells(1)) == len(cells(0)) - 1
        # NaN on red, its text white; a warning marked, named for screen readers
        assert cells(1)[1]["style"] == "background-color: #dc2626; color: #ffffff"
        assert any(
            attributes.get("role") == "img" and attributes.get("aria-label") == "Warning"
            for _, attributes in _element(page, f"{table_id}-row-2").descendants
        )
        # a disabled cell is grayed and never edited: no field, its box disabled
        assert cells(1)[0].get("class") == "opacity-50"
        assert "data-edit" not in cells(1)[0]
        assert "disabled" in _element(page, f"{table_id}-cell-1-4").attributes

        def post(event: str, **values: str) -> str:
            return str(client.post(f"/widget/{table_id}", data={"event": event, **values}).text)

        assert _find(post("start_edit", row="1", column="1"), f"{table_id}-cell-1-1") is None
        post("check", row="1", column="4", checked="on")
        assert view.points.rows[1][4] == "False"

        # the key/value table's keys head its rows
        numbers = _element(page, _widget_id(view.numbers.renderer))
        assert [
            attributes.get("scope") for tag, attributes in numbers.descendants if tag == "th"
        ] == [None, "row", "row"]
        assert "Number of calls" in numbers.text


def test_a_table_s_cell_widgets_post_their_edits_and_clicks() -> None:
    views: list[CellWidgetsMainView] = []

    class VariablesApp(WebApplication[CellWidgetsMainView]):
        @override
        def setup_session(self, main_view: CellWidgetsMainView) -> None:
            views.append(main_view)

    app = VariablesApp(build_main_view=CellWidgetsMainView)
    with _Browser(app.create_starlette_app()) as client:
        page = client.get("/").text
        (view,) = views
        table = view.variables
        table_id = _widget_id(table.renderer)
        events: list[tuple[int, ...] | tuple[int, int, str]] = []
        table.cell_edited.connect(lambda row, column, text: events.append((row, column, text)))
        table.cell_clicked.connect(lambda row, column: events.append((row, column)))
        applied: list[tuple[int, int, str]] = []
        table.cell_edit_applied.connect(
            lambda row, column, _text: applied.append((row, column, table.rows[row][column]))
        )

        def post(event: str, **values: str) -> str:
            return str(client.post(f"/widget/{table_id}", data={"event": event, **values}).text)

        keep, role = _element(page, f"{table_id}-cell-1-0"), _element(page, f"{table_id}-cell-0-2")
        assert (keep.attributes["aria-label"], "checked" in keep.attributes) == ("Keep", False)
        assert role.tag == "select"
        assert [attributes.get("value") for _, attributes in role.descendants] == [
            "Input",
            "Output",
        ]
        assert "data-indeterminate" in _element(page, f"{table_id}-check-all-0").attributes

        # a check box's change: only the check-all box follows, the box itself not swapped
        body = post("check", row="1", column="0", checked="on")
        assert applied == [(1, 0, "True")]
        _swapped(body, f"{table_id}-head")
        assert "checked" in _element(body, f"{table_id}-check-all-0").attributes
        assert _find(body, f"{table_id}-cell-1-0") is None
        # the header's box unchecks every row: the rows come back, not the box
        post("select", row="1")
        body = post("check_all", column="0")
        assert [row[0] for row in table.rows] == ["False", "False"]
        assert "checked" not in _element(body, f"{table_id}-cell-0-0").attributes
        assert _find(body, f"{table_id}-check-all-0") is None
        assert table.selected_rows == [1]
        # a page still showing the box unchecked, the app having checked every row since
        table.rows = [["True", *row[1:]] for row in table.rows]
        post("check_all", column="0", checked="on")  # checks them, as the page showed
        assert [row[0] for row in table.rows] == ["True", "True"]
        post("pick", row="0", column="2", text="Output")
        assert table.rows[0][2] == "Output"

        # a button and a link post their clicks, the button named by its column
        button = _element(page, f"{table_id}-cell-1-3")
        assert button.attributes["aria-label"] == "Distribution: \u2026"
        assert _element(page, f"{table_id}-cell-0-4").text == "doc"
        post("click_cell", row="1", column="3")
        post("click_cell", row="0", column="4")
        # a stale page's posts: text typed in a check box, a role no longer editable, a
        # click on a text cell
        for event in ("start_edit", "edit"):
            post(event, row="0", column="0", text="maybe")
        table.editable_columns = [0]
        post("pick", row="1", column="2", text="Input")
        post("click_cell", row="0", column="1")
        assert table.rows[1][2] == "Output"
        assert "disabled" in _element(client.get("/").text, f"{table_id}-cell-1-2").attributes
        assert events == [
            (1, 0, "True"),
            (0, 0, "False"),
            (1, 0, "False"),
            (0, 2, "Output"),
            (1, 3),
            (0, 4),
        ]


def test_a_table_s_file_path_is_uploaded_or_typed_its_copy_kept_while_a_cell_holds_it() -> None:
    views: list[DataFilesTableMainView] = []

    class InputsApp(WebApplication[DataFilesTableMainView]):
        @override
        def setup_session(self, main_view: DataFilesTableMainView) -> None:
            main_view.status_bar.timeout = 0
            views.append(main_view)

    app = InputsApp(build_main_view=DataFilesTableMainView)
    with _Browser(app.create_starlette_app()) as client:
        page = client.get("/").text
        (view,) = views
        table = view.inputs
        table_id = _widget_id(table.renderer)
        edits: list[tuple[int, int, str]] = []
        table.cell_edited.connect(lambda row, column, text: edits.append((row, column, text)))

        def upload(row: str, name: str) -> str:
            response = client.post(
                f"/widget/{table_id}/file",
                data={"row": row, "column": "1"},
                files={"file": (name, b"1,2", "text/csv")},
            )
            assert response.status_code == 200
            return str(response.text)

        cell = _element(page, f"{table_id}-cell-0-1")
        assert cell.attributes["aria-label"] == "File: Choose a file"
        (picker,) = [
            a for tag, a in _element(page, f"{table_id}-row-0").descendants if tag == "input"
        ]
        assert (picker["type"], picker["accept"]) == ("file", ".csv")
        assert picker["hx-post"] == f"/widget/{table_id}/file"
        assert picker["hx-vals"] == '{"row": "0", "column": "1"}'

        # the cell shows the copy's path once swapped back
        body = upload("0", "flows.csv")
        flows = Path(table.rows[0][1])
        assert (flows.name, flows.read_bytes()) == ("flows.csv", b"1,2")
        _swapped(body, table_id)
        assert str(flows) in _element(body, f"{table_id}-row-0").text
        # each cell keeps its copy, a copy no cell holds is gone at the next upload
        upload("1", "levels.csv")
        levels = Path(table.rows[1][1])
        upload("0", "flows.csv")
        assert (flows.exists(), levels.exists()) == (True, True)
        upload("1", "levels.csv")
        assert (flows.exists(), levels.exists(), Path(table.rows[1][1]).exists()) == (
            False,
            True,
            True,
        )
        # another type is refused
        body = upload("0", "notes.md")
        status = _swapped(body, _widget_id(view.notification.renderer))
        assert status.text == "Can't open 'notes.md': expected a .csv file."
        # or the path is typed
        client.post(f"/widget/{table_id}", data={"event": "start_edit", "row": "1", "column": "1"})
        client.post(
            f"/widget/{table_id}",
            data={"event": "edit", "row": "1", "column": "1", "text": "/data/levels.csv"},
        )
        assert table.rows[1][1] == "/data/levels.csv"
        # a stale page's upload, to a table disabled or a column no longer editable: the
        # table as it now is
        table.is_enabled = False
        _swapped(upload("0", "flows.csv"), table_id)
        table.is_enabled = True
        table.editable_columns = []
        body = upload("0", "flows.csv")
        _swapped(body, table_id)
        assert "disabled" in _element(client.get("/").text, f"{table_id}-cell-0-1").attributes
        assert [edit[:2] for edit in edits] == [(0, 1), (1, 1), (0, 1), (1, 1), (1, 1)]


def test_a_table_s_file_path_upload_stays_in_the_app_s_folder_under_a_free_name(
    tmp_path: Path,
) -> None:
    main_view = DataFilesTableMainView()
    table = main_view.inputs
    table.cell_widgets = {
        1: CellWidget.file_path({"CSV": (".csv",)}, base_folder=tmp_path, upload_folder=tmp_path)
    }
    session = WebSession(main_view)
    table_id = _widget_id(table.renderer)
    edits: list[str] = []
    table.cell_edited.connect(lambda _row, _column, text: edits.append(text))
    (tmp_path / "flows.csv").write_bytes(b"theirs")
    _pick_cell_file(session, table_id, 0, "flows.csv", b"1,2")
    # a name taken gets a number: the file that has it stays as it was
    assert (edits, table.rows[0][1]) == (["flows-1.csv"], "flows-1.csv")
    assert (tmp_path / "flows.csv").read_bytes() == b"theirs"
    assert (tmp_path / "flows-1.csv").read_bytes() == b"1,2"
    # a name that a cell holds is taken, even once its file is gone: the edit says the file
    # changed
    (tmp_path / "flows-1.csv").unlink()
    _pick_cell_file(session, table_id, 0, "flows.csv", b"3")
    assert (edits[-1], (tmp_path / "flows-2.csv").read_bytes()) == ("flows-2.csv", b"3")
    # the app's file: neither a cell letting it go, the next upload, nor the session's end
    # removes it
    table.rows = [["Flows", ""], ["Levels", ""]]
    _pick_cell_file(session, table_id, 1, "levels.csv", b"4")
    session.close()
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "flows-2.csv",
        "flows.csv",
        "levels.csv",
    ]


def test_a_table_s_upload_that_no_cell_takes_leaves_nothing_in_the_app_s_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_view = DataFilesTableMainView()
    main_view.status_bar.timeout = 0
    table = main_view.inputs
    folder = tmp_path / "inputs"
    # the row's kind's widget takes the folder of `path_by`
    editors = {"Flows": CellWidget.file_path({"CSV": (".csv",)})}
    table.cell_widgets = {1: CellWidget.path_by(0, editors, upload_folder=folder)}
    session = WebSession(main_view)
    table_id = _widget_id(table.renderer)
    # a folder that can't take the file: the cell keeps its text, the status bar says why
    result = _pick_cell_file(session, table_id, 0, "flows.csv", b"1,2")
    assert result is not None
    status = _swapped(result[0], _widget_id(main_view.notification.renderer))
    assert status.text == "Can't open 'flows.csv': no such file or directory."
    assert (table.rows[0][1], folder.exists()) == ("", False)

    folder.mkdir()
    # a disk full as the file is written: neither its name nor a part of it stays
    with monkeypatch.context() as patch:

        def fill_the_disk(_partial: Path, _path: Path) -> None:
            raise OSError(errno.ENOSPC, "No space left on device")

        patch.setattr("composeui.webcore.session._publish", fill_the_disk)
        result = _pick_cell_file(session, table_id, 0, "flows.csv", b"1,2")
    assert result is not None
    status = _swapped(result[0], _widget_id(main_view.notification.renderer))
    assert status.text == "Can't open 'flows.csv': no space left on device."
    assert (table.rows[0][1], list(folder.iterdir())) == ("", [])

    def refuse(_row: int, _column: int, _text: str) -> None:
        raise EditRefusedError

    table.cell_edited.connect(refuse)
    _pick_cell_file(session, table_id, 0, "flows.csv", b"1,2")
    assert (table.rows[0][1], list(folder.iterdir())) == ("", [])


class _SortedRooms(NamedTuple):
    """The sortable, filterable table's view and its fragment's id, and a client."""

    client: TestClient
    view: SortedRoomsMainView
    table_id: str

    def post(self, event: str, **values: str) -> str:
        data = {"event": event, **values}
        response = self.client.post(f"/widget/{self.table_id}", data=data)
        assert response.status_code == 200
        return str(response.text)

    def shown(self, markup: str) -> list[str | None]:
        """Get the ids of the rows the swapped body shows, in order."""
        body = _swapped(markup, f"{self.table_id}-body")
        return [attributes.get("id") for tag, attributes in body.descendants if tag == "tr"]

    def row_ids(self, *rows: int) -> list[str | None]:
        return [f"{self.table_id}-row-{row}" for row in rows]


@pytest.fixture
def sorted_rooms() -> Iterator[_SortedRooms]:
    views: list[SortedRoomsMainView] = []

    class SortedRoomsApp(WebApplication[SortedRoomsMainView]):
        @override
        def setup_session(self, main_view: SortedRoomsMainView) -> None:
            views.append(main_view)

    app = SortedRoomsApp(build_main_view=SortedRoomsMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield _SortedRooms(client, view, _widget_id(view.rooms.renderer))


def test_a_sortable_header_posts_its_sort_swapping_only_the_headers_and_the_body(
    sorted_rooms: _SortedRooms,
) -> None:
    table_id = sorted_rooms.table_id

    def sort_state(markup: str) -> list[str | None]:
        head = _swapped(markup, f"{table_id}-head")
        return [attributes.get("aria-sort") for tag, attributes in head.descendants if tag == "th"]

    body = sorted_rooms.post("sort", column="2")  # the occupants
    assert sort_state(body) == ["none", "none", "ascending", "none"]
    # each row keeps its id from its index in the rows, the empty cell last
    assert sorted_rooms.shown(body) == sorted_rooms.row_ids(2, 3, 1, 0)
    # the table isn't swapped whole: its search field stays as the user left it
    assert _find(body, table_id) is None
    assert _find(body, f"{table_id}-search") is None
    body = sorted_rooms.post("sort", column="2")
    assert sort_state(body)[2] == "descending"
    body = sorted_rooms.post("sort", column="2")
    assert sort_state(body)[2] == "none"
    assert sorted_rooms.shown(body) == sorted_rooms.row_ids(0, 1, 2, 3)

    # a table sorting and filtering by no column: plain headers, no bar
    page = sorted_rooms.client.get("/").text
    notes_id = _widget_id(sorted_rooms.view.notes.renderer)
    notes = _element(page, notes_id)
    assert not any(tag == "button" for tag, _ in notes.descendants)
    assert "hidden" in _element(page, f"{notes_id}-bar").attributes
    assert _element(page, f"{table_id}-bar").attributes["role"] == "search"


def test_the_search_swaps_the_body_and_the_count_never_its_field(
    sorted_rooms: _SortedRooms,
) -> None:
    table_id = sorted_rooms.table_id
    body = sorted_rooms.post("search", search="ROOM")
    assert sorted_rooms.shown(body) == sorted_rooms.row_ids(3)
    count = _swapped(body, f"{table_id}-count")
    assert (count.text, count.attributes["aria-live"]) == ("1 of 4", "polite")
    assert _find(body, f"{table_id}-search") is None

    body = sorted_rooms.post("search", search="nowhere")
    (no_match,) = [
        attributes
        for tag, attributes in _swapped(body, f"{table_id}-body").descendants
        if tag == "td"
    ]
    assert no_match["colspan"] == "4"
    assert "No rows match the filters" in body


def test_a_table_sorted_without_a_filter_bar_swaps_no_count(
    sorted_rooms: _SortedRooms,
) -> None:
    # the bar is hidden, without a count: htmx would find no element to swap one into
    notes = sorted_rooms.view.notes
    notes.sortable_columns = [0]
    sorted_rooms.client.get("/")  # the page draws its headers sortable
    notes_id = _widget_id(notes.renderer)
    response = sorted_rooms.client.post(
        f"/widget/{notes_id}", data={"event": "sort", "column": "0"}
    )
    assert response.status_code == 200
    body = _swapped(response.text, f"{notes_id}-body").text
    assert body.index("Busy") < body.index("Calm")
    assert _find(response.text, f"{notes_id}-count") is None


def test_the_filter_editor_adds_a_filter_as_a_chip_or_says_why_it_can_t(
    sorted_rooms: _SortedRooms,
) -> None:
    table, table_id = sorted_rooms.view.rooms, sorted_rooms.table_id
    value_id = f"{table_id}-value"

    body = sorted_rooms.post("open_editor")
    _swapped(body, f"{table_id}-bar")
    field = _element(body, value_id)
    assert "autofocus" in field.attributes
    assert field.attributes["aria-describedby"] == f"{value_id}-error"

    # a value that doesn't parse: only its message is swapped in, the field left alone
    body = sorted_rooms.post("add_filter", column="1", value="warm")
    error = _swapped(body, f"{value_id}-error")
    assert (error.text, error.attributes["data-log"]) == ('"warm" isn\'t a number', "error")
    assert "hidden" not in error.attributes
    assert _find(body, value_id) is None
    assert table.filters == {}

    body = sorted_rooms.post("add_filter", column="1", value=">=20")
    assert table.filters == {1: ">=20"}
    assert sorted_rooms.shown(body) == sorted_rooms.row_ids(1, 3)
    bar = _swapped(body, f"{table_id}-bar")
    # the editor closed, the filter's chip taking the focus: it edits the filter
    assert _find(body, value_id) is None
    chip = _element(body, f"{table_id}-chip-1")
    assert chip.text == "Temperature: >=20"
    assert chip.attributes["title"] == "Edit the filter on Temperature"
    assert "autofocus" in chip.attributes
    assert "autofocus" not in _element(body, f"{table_id}-add-filter").attributes
    labels = [attributes.get("aria-label") for tag, attributes in bar.descendants]
    assert "Remove the filter on Temperature" in labels

    # its chip opens the editor on it; a second filter on its column replaces it
    body = sorted_rooms.post("open_editor", column="1")
    assert _element(body, value_id).attributes["value"] == ">=20"
    sorted_rooms.post("add_filter", column="1", value=">=21")
    sorted_rooms.post("open_editor")
    sorted_rooms.post("add_filter", column="3", value="true")
    assert table.filters == {1: ">=21", 3: "true"}
    sorted_rooms.post("remove_filter", column="1")
    assert table.filters == {3: "true"}
    sorted_rooms.post("open_editor")
    body = sorted_rooms.post("close_editor")
    assert _find(body, value_id) is None
    sorted_rooms.post("clear_filters")
    assert table.filters == {}

    # disabled, the table refuses a stale page's posts
    table.is_enabled = False
    response = sorted_rooms.client.post(
        f"/widget/{table_id}", data={"event": "sort", "column": "0"}
    )
    assert response.status_code == 400


def test_the_filter_editor_s_toggle_makes_the_value_a_regular_expression(
    sorted_rooms: _SortedRooms,
) -> None:
    table, table_id = sorted_rooms.view.rooms, sorted_rooms.table_id

    def toggle(markup: str) -> tuple[dict[str, str | None], dict[str, str | None]]:
        """Get the toggle's label and its checkbox."""
        tags = _element(markup, f"{table_id}-editor").descendants
        label = next(attributes for tag, attributes in tags if "data-filter-pattern" in attributes)
        box = next(attributes for tag, attributes in tags if attributes.get("name") == "pattern")
        return label, box

    label, box = toggle(sorted_rooms.post("open_editor"))  # the first column, text
    assert "hidden" not in label
    assert (box["type"], box["aria-label"]) == ("checkbox", "Regular expression")
    # a number column takes comparisons: the page hides the toggle for it
    label, _ = toggle(sorted_rooms.post("open_editor", column="1"))
    assert "hidden" in label

    body = sorted_rooms.post("add_filter", column="0", value="^(hall|attic)$", pattern="1")
    assert table.filters == {0: "/^(hall|attic)$/"}
    assert sorted_rooms.shown(body) == sorted_rooms.row_ids(0, 2)
    assert _element(body, f"{table_id}-chip-0").text == "Room matches ^(hall|attic)$"
    # reopened: the toggle on, the pattern as typed
    body = sorted_rooms.post("open_editor", column="0")
    _, box = toggle(body)
    assert "checked" in box
    assert _element(body, f"{table_id}-value").attributes["value"] == "^(hall|attic)$"
    # a pattern that doesn't compile is refused, saying why; a number column takes none
    body = sorted_rooms.post("add_filter", column="0", value="(hall", pattern="1")
    assert _swapped(body, f"{table_id}-value-error").text == (
        '"(hall" isn\'t a valid regular expression'
    )
    sorted_rooms.post("add_filter", column="1", value=">=20", pattern="1")
    assert table.filters == {0: "/^(hall|attic)$/", 1: ">=20"}


def test_a_post_can_t_filter_by_a_regular_expression_when_they_are_turned_off(
    monkeypatch: pytest.MonkeyPatch, sorted_rooms: _SortedRooms
) -> None:
    monkeypatch.setenv("COMPOSEUI_FILTER_PATTERNS", "off")
    table, table_id = sorted_rooms.view.rooms, sorted_rooms.table_id

    tags = _element(sorted_rooms.post("open_editor"), f"{table_id}-editor").descendants
    assert any("data-filter-pattern" in tag and "hidden" in tag for _, tag in tags)
    # slashes typed or posted are refused; the toggle's field makes no pattern of the text
    body = sorted_rooms.post("add_filter", column="0", value="/(a+)+$/")
    assert _swapped(body, f"{table_id}-value-error").text == (
        "This app doesn't accept regular expressions"
    )
    assert table.filters == {}
    # the bar drawn again keeps the text as typed: its slashes aren't dropped
    table.filters = {1: ">=20"}
    body = sorted_rooms.post("remove_filter", column="1")
    assert _element(body, f"{table_id}-value").attributes["value"] == "/(a+)+$/"
    table.filters = {}
    sorted_rooms.post("add_filter", column="0", value="(a+)+$", pattern="1")
    assert table.filters == {0: "(a+)+$"}


def test_a_click_and_an_edit_on_a_sorted_filtered_table_reach_their_rows(
    sorted_rooms: _SortedRooms,
) -> None:
    table = sorted_rooms.view.rooms
    table.filters = {3: "true"}
    emitted: list[list[int]] = []
    table.selection_changed.connect(emitted.append)

    sorted_rooms.post("select", row="3")
    assert table.selected_records == [Room("Bedroom", 21, 9, is_heated=True)]
    # a row the filters hide, which a stale page still shows: not selected
    sorted_rooms.post("select", row="0")
    assert (table.selected_rows, emitted) == ([3], [[3]])

    sorted_rooms.post("start_edit", row="3", column="0")
    body = sorted_rooms.post("edit", row="3", column="0", text="Study")
    assert table.records[3] == Room("Study", 21, 9, is_heated=True)
    assert table.selected_rows == [3]
    assert _rows_with(body, sorted_rooms.table_id, "aria-current") == sorted_rooms.row_ids(3)


@pytest.fixture
def million_views() -> list[MillionRowsMainView]:
    """Each session's main view, kept by `million_client`'s app."""
    return []


@pytest.fixture
def million_client(million_views: list[MillionRowsMainView]) -> Iterator[TestClient]:
    class MillionApp(WebApplication[MillionRowsMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=MillionRowsMainView)

        @override
        def setup_session(self, main_view: MillionRowsMainView) -> None:
            million_views.append(main_view)

    with _Browser(MillionApp().create_starlette_app()) as client:
        yield client


def _window(markup: str, table_id: str) -> list[dict[str, str | None]]:
    """Get the rows a large table drew, from its `<tbody>`: no filler."""
    body = _element(markup, f"{table_id}-rows")
    return [attributes for tag, attributes in body.descendants if "data-window-row" in attributes]


def test_a_large_table_draws_the_rows_around_the_view_as_it_scrolls(
    million_views: list[MillionRowsMainView], million_client: TestClient
) -> None:
    page = million_client.get("/").text
    (main_view,) = million_views
    table_id = _widget_id(main_view.table.renderer)
    source = main_view.table.source
    assert isinstance(source, MillionSource)
    frame = _element(page, f"{table_id}-frame")
    # a million rows, 400,000 rows' height: a filler's row height stands for 2.5 rows
    assert dict(frame.descendants)["table"].get("aria-rowcount") == "1000001"
    rows = _window(page, table_id)
    assert [row.get("aria-rowindex") for row in (rows[0], rows[-1])] == ["2", "101"]

    def scroll(start: str, offset: str = "") -> str:
        response: httpx.Response = million_client.post(
            f"/widget/{table_id}", data={"event": "scroll", "start": start, "offset": offset}
        )
        assert response.status_code == 200
        return response.text

    def fillers(scrolled: str) -> list[str | None]:
        return [
            attributes.get("style")
            for tag, attributes in _element(scrolled, f"{table_id}-rows").descendants
            if attributes.get("aria-hidden") == "true"
        ]

    scrolled = scroll("500000")
    assert _find(scrolled, f"{table_id}-frame") is None  # the scroll position stays
    rows = _window(scrolled, table_id)
    # from a fifth of the window above the first row shown
    assert [row.get("aria-rowindex") for row in (rows[0], rows[-1])] == ["499982", "500081"]
    assert fillers(scrolled) == [
        "height: calc(2.25rem * 199992.000)",
        "height: calc(2.25rem * 199968.000)",
    ]
    assert '<td class="whitespace-nowrap">1000000</td>' in scrolled
    assert scroll("500000") == ""  # drawn already
    assert scroll("first") == ""
    assert len(source.read) <= 3 * SOURCE_TABLE_WINDOW
    # the row scrolled to stays where it was: 20 rows of the window above it, the filler
    # above them up to it, the frame's height kept
    scrolled = scroll("600000", offset="240100.5")
    assert _window(scrolled, table_id)[0].get("aria-rowindex") == "599982"
    assert fillers(scrolled) == [
        "height: calc(2.25rem * 240080.500)",
        "height: calc(2.25rem * 159879.500)",
    ]

    # disabled: the rows scrolled to still show, but none is selected
    main_view.table.is_enabled = False
    response = million_client.post(f"/widget/{table_id}", data={"event": "scroll", "start": "0"})
    assert _window(response.text, table_id)[0].get("aria-rowindex") == "2"
    selected = million_client.post(f"/widget/{table_id}", data={"event": "select", "position": "0"})
    assert selected.status_code == 400


def test_a_large_table_s_header_sorts_by_its_column_from_the_top(
    million_views: list[MillionRowsMainView], million_client: TestClient
) -> None:
    million_client.get("/")
    (main_view,) = million_views
    table_id = _widget_id(main_view.table.renderer)
    million_client.post(f"/widget/{table_id}", data={"event": "scroll", "start": "5000"})

    response = million_client.post(f"/widget/{table_id}", data={"event": "sort", "column": "half"})

    assert (main_view.table.sort_column, main_view.table.sort_descending) == ("half", False)
    frame = _swapped(response.text, f"{table_id}-frame")
    headers = [attributes for tag, attributes in frame.descendants if tag == "th"][:2]
    assert [header.get("aria-sort") for header in headers] == ["none", "ascending"]
    buttons = [attributes for tag, attributes in frame.descendants if tag == "button"]
    assert ["autofocus" in button for button in buttons] == [False, True]
    assert _window(response.text, table_id)[0].get("aria-rowindex") == "2"

    refused = million_client.post(f"/widget/{table_id}", data={"event": "sort", "column": "mass"})
    assert refused.status_code == 400


def test_a_large_table_s_row_selected_by_a_click_keeps_the_focus(
    million_views: list[MillionRowsMainView], million_client: TestClient
) -> None:
    million_client.get("/")
    (main_view,) = million_views
    table_id = _widget_id(main_view.table.renderer)
    million_client.post(f"/widget/{table_id}", data={"event": "scroll", "start": "70"})

    def select(position: str) -> str:
        response: httpx.Response = million_client.post(
            f"/widget/{table_id}", data={"event": "select", "position": position}
        )
        assert response.status_code == 200
        return response.text

    selected = select("52")
    assert _find(selected, f"{table_id}-frame") is None  # the scroll position stays
    rows = _window(selected, table_id)  # from position 50
    assert main_view.table.selected_ids == [52]
    assert [row.get("aria-current") for row in rows[1:4]] == [None, "true", None]
    assert ["autofocus" in row for row in rows[1:4]] == [False, True, False]

    main_view.table.selection_mode = SelectionMode.MULTIPLE
    select("54")
    rows = _window(select("52"), table_id)  # selected: off
    assert main_view.table.selected_ids == [54]
    assert [row.get("aria-selected") for row in rows[2:5]] == ["false", "false", "true"]

    # a row a stale page still shows: the rows as they now are, nothing selected
    assert _window(select("1000000"), table_id)[0].get("aria-rowindex") == "52"
    assert main_view.table.selected_ids == [54]


def test_a_large_table_s_row_activated_emits_its_id(
    million_views: list[MillionRowsMainView], million_client: TestClient
) -> None:
    million_client.get("/")
    (main_view,) = million_views
    table = main_view.table
    table_id = _widget_id(table.renderer)
    activated: list[object] = []
    table.row_activated.connect(activated.append)

    def activate(position: str) -> str:
        response: httpx.Response = million_client.post(
            f"/widget/{table_id}", data={"event": "activate_row", "row": position}
        )
        return response.text

    page = million_client.get("/").text
    assert _window(page, table_id)[3].get("data-activate") == "3"
    activate("3")
    assert activated == [3]
    assert table.selected_ids == []  # the click or Enter before it selects

    # a row a stale page still shows: the rows as they now are
    assert _window(activate("1000000"), table_id)[0].get("aria-rowindex") == "2"
    table.is_enabled = False
    response = million_client.post(
        f"/widget/{table_id}", data={"event": "activate_row", "row": "3"}
    )
    assert response.status_code == 400
    assert activated == [3]


@pytest.fixture
def rooms_data_views() -> list[RoomsDataMainView]:
    """Each session's main view, kept by `rooms_data_client`'s app."""
    return []


@pytest.fixture
def rooms_data_client(rooms_data_views: list[RoomsDataMainView]) -> Iterator[TestClient]:
    class RoomsApp(WebApplication[RoomsDataMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=RoomsDataMainView)

        @override
        def setup_session(self, main_view: RoomsDataMainView) -> None:
            rooms_data_views.append(main_view)

    with _Browser(RoomsApp().create_starlette_app()) as client:
        yield client


def test_a_large_table_s_link_downloads_its_rows_shown_as_csv(
    rooms_data_views: list[RoomsDataMainView], rooms_data_client: TestClient
) -> None:
    page = rooms_data_client.get("/").text
    (main_view,) = rooms_data_views
    table_id = _widget_id(main_view.rooms.renderer)
    address = f"/widget/{table_id}/csv"
    link = next(
        attributes
        for tag, attributes in _element(page, table_id).descendants
        if tag == "a" and attributes.get("href") == address
    )
    assert "download" in link
    main_view.rooms.filters = {"temperature": ">19"}
    main_view.rooms.export_filename = "pièces.csv"

    response = rooms_data_client.get(address)

    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"pi_ces.csv\"; filename*=UTF-8''pi%C3%A8ces.csv"
    )
    assert response.headers["x-frame-options"] == "DENY"  # streamed, still guarded
    assert response.text.splitlines() == [
        "Room,Temperature,Occupants",
        "Kitchen,21.5,2",
        "Bedroom,19.5,1",
    ]
    assert rooms_data_client.get("/widget/nothing/csv").status_code == 404


def test_a_large_table_s_bar_searches_and_filters_its_columns_by_name(
    rooms_data_views: list[RoomsDataMainView], rooms_data_client: TestClient
) -> None:
    page = rooms_data_client.get("/").text
    (main_view,) = rooms_data_views
    table_id = _widget_id(main_view.rooms.renderer)
    assert _element(page, f"{table_id}-bar").attributes.get("role") == "search"

    def post(**data: str) -> str:
        response: httpx.Response = rooms_data_client.post(f"/widget/{table_id}", data=data)
        assert response.status_code == 200
        return response.text

    # typed: the rows and the count come back, never the field typed in
    searched = post(event="search", search="room")
    assert main_view.rooms.search == "room"
    _swapped(searched, f"{table_id}-frame")
    assert len(_window(searched, table_id)) == 1
    assert _swapped(searched, f"{table_id}-count").text == "1 of 3"
    assert _find(searched, f"{table_id}-bar") is None
    post(event="search", search="")

    # the editor knows the columns by their positions: the temperature is the second
    editor = _swapped(post(event="open_editor"), f"{table_id}-bar")
    options = [attributes for tag, attributes in editor.descendants if tag == "option"]
    assert [option.get("value") for option in options] == ["0", "1"]
    error = post(event="add_filter", column="1", value="warm")
    assert _swapped(error, f"{table_id}-value-error").text == '"warm" isn\'t a number'
    added = post(event="add_filter", column="1", value=">19")
    assert main_view.rooms.filters == {"temperature": ">19"}
    assert "Temperature: >19" in _swapped(added, f"{table_id}-bar").text
    _swapped(added, f"{table_id}-frame")
    assert len(_window(added, table_id)) == 2

    post(event="remove_filter", column="1")
    assert (main_view.rooms.filters, main_view.rooms.row_count) == ({}, 3)


def test_ctrl_c_answers_a_large_table_s_selected_rows_for_the_clipboard(
    million_views: list[MillionRowsMainView], million_client: TestClient
) -> None:
    page = million_client.get("/").text
    (main_view,) = million_views
    table_id = _widget_id(main_view.table.renderer)
    copied = _element(page, f"{table_id}-copied")
    assert (copied.text, "data-copy-answer" in copied.attributes) == ("", False)
    main_view.table.selection_mode = SelectionMode.MULTIPLE
    main_view.table.selected_ids = [3, 1]

    response = million_client.post(f"/widget/{table_id}", data={"event": "copy"})

    copied = _swapped(response.text, f"{table_id}-copied")
    assert copied.text == "2\t0.5\n6\t1.5"  # in the table's order
    assert "data-copy-answer" in copied.attributes  # the answer the page waits for
    assert copied.attributes.get("hx-trigger") == "copy-rows"  # the next copy posts again
    # the table swapped whole meanwhile (e.g. its texts changed): the answer comes in it
    main_view.table.texts = {**main_view.table.texts, "export": "Save the rows"}
    response = million_client.post(f"/widget/{table_id}", data={"event": "copy"})
    whole = _swapped(response.text, table_id)
    (answer,) = [
        attributes
        for tag, attributes in whole.descendants
        if attributes.get("id") == f"{table_id}-copied"
    ]
    assert "data-copy-answer" in answer
    assert _element(response.text, f"{table_id}-copied").text == "2\t0.5\n6\t1.5"


def test_a_table_answers_a_stale_page_s_posts_with_itself_as_it_now_is() -> None:
    views: list[CellWidgetsMainView] = []

    class VariablesApp(WebApplication[CellWidgetsMainView]):
        @override
        def setup_session(self, main_view: CellWidgetsMainView) -> None:
            views.append(main_view)

    app = VariablesApp(build_main_view=CellWidgetsMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        table = view.variables
        table_id = _widget_id(table.renderer)
        events: list[tuple[int, int, str]] = []
        table.cell_edited.connect(lambda row, column, text: events.append((row, column, text)))

        def post(event: str, **values: str) -> str:
            return str(client.post(f"/widget/{table_id}", data={"event": event, **values}).text)

        # e.g. sent by hand, or by a page showing rows, columns or a sort no longer there
        unknown_row = post("check", row="x", column="0", checked="on")
        same_role = post("pick", row="0", column="2", text="Input")
        unsorted = post("sort", column="1")
        table.editable_columns = [2]
        read_only_check_all = post("check_all", column="0")

        assert events == []
        assert table.rows[0][:3] == ["True", "Length", "Input"]
        assert table.sort_column is None
        assert _find(unknown_row, table_id) is not None  # the table as it now is
        assert _find(same_role, table_id) is None  # nothing to show again
        assert _find(unsorted, f"{table_id}-body") is not None
        assert _find(read_only_check_all, f"{table_id}-head") is not None


def test_a_table_cell_picked_keeps_the_rows_the_app_answers_with() -> None:
    views: list[CellWidgetsMainView] = []

    class VariablesApp(WebApplication[CellWidgetsMainView]):
        @override
        def setup_session(self, main_view: CellWidgetsMainView) -> None:
            views.append(main_view)

    app = VariablesApp(build_main_view=CellWidgetsMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        table = view.variables
        table.cell_widgets = {2: CellWidget.combobox(["Input", "Output"])}  # no check-all box
        table_id = _widget_id(table.renderer)
        answers: list[str] = []

        def answer(_row: int, _column: int, text: str) -> None:
            if len(answers) == 0:  # the first edit only, e.g. sorted by the model
                table.rows = [["True", "Width", text, "", ""]]
            answers.append(text)

        table.cell_edited.connect(answer)

        def pick(text: str) -> str:
            data = {"event": "pick", "row": "0", "column": "2", "text": text}
            return str(client.post(f"/widget/{table_id}", data=data).text)

        answered = pick("Output")
        kept = pick("Input")

    assert "Width" in _element(answered, table_id).text  # the app's rows
    assert table.rows == [["True", "Width", "Input", "", ""]]
    assert _find(kept, f"{table_id}-head") is None  # no check-all box to follow


def test_an_edit_leaving_its_cell_as_it_was_edits_nothing(places: _Places) -> None:
    places.post("start_edit", "0", "1")
    places.post("edit", "0", "1", "Calm")

    assert places.edited == []


def test_a_filter_bar_answers_a_stale_page_s_posts_with_itself_as_it_now_is() -> None:
    view = SortedRoomsMainView()
    view.render(RendererType.WEB)
    table = view.rooms.renderer
    assert isinstance(table, WebRenderer)
    view.rooms.filters = {3: "true"}

    added = handle_event(table, "add_filter", {"column": "1", "value": ">=20"})  # no editor
    removed = handle_event(table, "remove_filter", {"column": "2"})  # no filter there
    view.rooms.headers = view.rooms.headers[:2]  # its filter's column gone
    shown = table.to_html()

    assert view.rooms.filters == {3: "true"}
    assert f"{table.widget_id}-bar" in added
    assert f"{table.widget_id}-bar" in removed
    assert "Heated" not in shown  # no chip for the column gone


def test_a_large_table_with_no_row_shown_says_so() -> None:
    view = RoomsDataMainView()
    view.rooms.filters = {"temperature": ">30"}
    view.render(RendererType.WEB)
    table = view.rooms.renderer
    assert isinstance(table, WebRenderer)

    body = _element(table.to_html(), f"{table.widget_id}-rows")

    assert body.text == "No rows match the filters"
