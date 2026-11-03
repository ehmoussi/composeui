"""Tests for views' own behavior, outside any backend: what they accept, refuse and keep."""

from __future__ import annotations

import copy
import datetime
import pickle
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from attrs import Factory
from hypothesis import given, settings
from hypothesis import strategies as st

from composeui.core.application import Application
from composeui.core.model import RefusedError
from composeui.core.view import (
    CellKind,
    CellWidget,
    ConsoleView,
    FilePathInputView,
    FormView,
    GroupFormView,
    LabelView,
    LanguageMenu,
    ListView,
    MainView,
    MapPoint,
    MapView,
    NodeMark,
    RowInputView,
    TableView,
    TextStyle,
    TreeView,
    TypedFormDialogView,
    define_view,
    find_in_lines,
    follow_match,
    line_styles_after,
    parse_date,
)
from examples.studyinputs import INPUT_FILE, OUTPUT_FOLDER, PATH, StudyInputsMainView
from tests.buildings import SITE
from tests.console import RunMainView
from tests.pages import InputsPage
from tests.splitter import StudySplitter
from tests.tabs import PipeTabs

if TYPE_CHECKING:
    from collections.abc import Callable


def _note(_instance: object, _attribute: object, value: str) -> str:
    return value.strip()


@define_view(on_setattr=_note)
class _OneHookView(LabelView):
    """A view with an `on_setattr` hook of its own."""


@define_view(on_setattr=[_note])
class _HooksView(LabelView):
    """A view with a list of `on_setattr` hooks of its own."""


@pytest.mark.parametrize("view_type", [_OneHookView, _HooksView])
def test_a_view_s_own_on_setattr_hooks_run_before_its_renderer_hears(
    view_type: type[LabelView],
) -> None:
    view = view_type()

    view.text = "  Ready  "

    assert view.text == "Ready"


def test_a_language_menu_has_no_action_for_a_language_it_doesn_t_offer() -> None:
    menu = LanguageMenu()
    menu.set_languages(["en", "fr"])

    with pytest.raises(KeyError, match="'de'"):
        menu.action("de")


@define_view
class _CountMainView(MainView):
    app_title = "Count"
    extension = ".count"


def test_closing_a_main_view_not_rendered_drops_its_jobs() -> None:
    view = _CountMainView()
    job = view.jobs.start(lambda job: job.sleep(10))

    view.close()

    assert job.is_canceled
    assert not view.jobs.is_running


def test_a_date_in_a_format_that_isn_t_one_is_read_as_iso() -> None:
    assert parse_date("2026-10-18", "not a format") == datetime.date(2026, 10, 18)


def test_a_splitter_refuses_sizes_not_one_per_pane_and_keeps_its_own_unlaid_out() -> None:
    splitter = StudySplitter()

    with pytest.raises(ValueError, match="3 panes"):
        splitter.sizes = [1, 1]
    with pytest.raises(ValueError, match="3 panes"):
        splitter.sizes = [1, 0, 1]
    assert splitter.shares_of([0, 0, 0]) == splitter.sizes  # not laid out yet
    assert StudySplitter(sizes=[2, 1, 1]).sizes == [2, 1, 1]  # given, not the panes' shares


def test_tabs_refuse_to_show_a_tab_they_don_t_have() -> None:
    tabs = PipeTabs()

    with pytest.raises(ValueError, match="tab 3 of PipeTabs: it has 3 tabs"):
        tabs.current_index = 3


def test_a_page_s_icon_is_its_action_s() -> None:
    page = InputsPage()

    page.icon = "run.svg"

    assert (page.icon, page.action.icon) == ("run.svg", "run.svg")


@define_view
class _NamesList(ListView[str]):
    def build_item(self, item: str) -> LabelView:
        return LabelView(text=item)


def test_a_list_tells_its_records_apart_by_themselves_unless_told_otherwise() -> None:
    names = _NamesList()
    names.items = ["Ada", "Bob"]
    ada = names.item_views[0]

    names.items = ["Ada", "Carol"]

    assert names.item_views[0] is ada  # the same record: its view kept
    assert names.item_key("Ada") == "Ada"


def test_a_tree_has_no_node_where_none_is() -> None:
    tree = TreeView(nodes=SITE)

    with pytest.raises(KeyError):
        tree.node(("Building Z",))


@define_view
class _NameGroup(GroupFormView):
    name: RowInputView = Factory(RowInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.name.set_validator(lambda: "A name is needed" if self.name.text == "" else None)


@define_view
class _OuterForm(FormView):
    group: _NameGroup = Factory(_NameGroup)


@define_view
class _NameDialog(TypedFormDialogView[_OuterForm]):
    form: _OuterForm = Factory(_OuterForm)


def test_a_form_s_check_and_its_dialog_s_ok_follow_its_nested_forms() -> None:
    dialog = _NameDialog()
    name = dialog.form.group.name
    accepted: list[None] = []
    dialog.accepted.connect(lambda: accepted.append(None))

    dialog.accept()  # not open: ignored
    dialog.form.check()  # the nested group's rows too
    shown = name.log_message
    dialog.open()
    refused = dialog.is_accept_enabled
    name.text = "Ada"
    name.run_validator()

    assert (accepted, shown, refused) == ([], "A name is needed", False)
    assert dialog.is_accept_enabled


@define_view
class _RefusingMainView(MainView):
    app_title = "Refusing"
    extension = ".refusing"

    name: LabelView = Factory(LabelView)


def test_a_refusal_shows_in_the_status_bar_or_raises_outside_an_app() -> None:
    app = Application(build_main_view=_RefusingMainView)
    view = app.main_view.name
    lone = LabelView()

    with view.refusing(view.tr("Can't rename: {error}")):
        raise RefusedError(view.tr("the name is taken"))  # translated already
    taken = "the name is taken"
    with pytest.raises(RefusedError), lone.refusing("Can't rename: {error}"):
        raise RefusedError(taken)  # nowhere to show it

    assert app.main_view.status_bar.message == "Can't rename: the name is taken"


def test_a_table_and_a_tree_name_their_marks() -> None:
    names = [TableView().mark_text(NodeMark.DONE), TreeView().mark_text(NodeMark.DONE)]

    assert names == ["Done", "Done"]


def test_a_console_ends_a_line_at_a_newline_and_starts_it_again_at_a_return() -> None:
    console = ConsoleView(max_lines=3)
    console.append("Ready\nStep")
    console.append(" 1\r\n50%\r")
    assert (list(console.lines), console.last_line) == (["Ready", "Step 1"], "50%")
    # a return then text: the progress line again; a return then a newline ends it as it is
    console.append("80%\r")
    console.append("\n")
    assert (list(console.lines), console.last_line) == (["Ready", "Step 1", "80%"], "")

    # the oldest lines go past `max_lines`, counted all the same
    console.append("Done\n")
    assert console.text == "Step 1\n80%\nDone\n"
    assert console.line_count == 4
    console.max_lines = 1
    assert list(console.lines) == ["Done"]

    console.text = "New\nrun"
    assert (list(console.lines), console.last_line) == (["New"], "run")
    console.clear()
    assert console.text == ""


def test_a_console_s_search_finds_plain_text_in_any_case_and_follows_its_match() -> None:
    lines = ["Step 1 done", "a.b DONE, done", ""]
    assert find_in_lines(lines, "done") == [(0, 7, 11), (1, 4, 8), (1, 10, 14)]
    assert find_in_lines(lines, "a.b") == [(1, 0, 3)]  # not a pattern
    assert find_in_lines(["axb"], "a.b") == []
    assert find_in_lines(lines, "") == []

    matches = [(0, 0, 1), (3, 2, 3), (5, 0, 1)]
    assert follow_match(matches, 0, None) == 0  # a new search: the first
    assert follow_match(matches, 2, (5, 2)) == 1  # the same, two lines dropped before it
    assert follow_match(matches, 10, (5, 2)) == 0  # gone with them: the next
    assert follow_match(matches, 0, (9, 0)) == 2  # past the last: the last
    assert follow_match([], 0, (1, 1)) == 0


def test_a_console_keeps_its_text_plain_and_the_styles_its_ansi_codes_ask_for() -> None:
    console = ConsoleView(max_lines=2)
    red, green = TextStyle(foreground="#cd3131", is_bold=True), TextStyle(background="#0dbc79")
    console.append("\x1b[1;31mERR\x1b[0mOR <x> \x1b[42mbg\x1b[0m\n\x1b[3")  # cut in the code
    console.append("2mgo\x1b]0;a title\x07\x1b[2K!")  # a title, an erased line: gone
    assert (console.text, console.lines[0]) == ("ERROR <x> bg\ngo!", "ERROR <x> bg")
    assert console.line_styles[0] == ((0, 3, red), (10, 12, green))
    # the style goes on, in one part, until a code changes it
    assert console.last_line_styles == [(0, 3, TextStyle(foreground="#0dbc79"))]

    console.append("\r\x1b[38;5;208;48;2;1;2;300;4mnew\x1b[24;39;49m\x1b x\n")
    orange = TextStyle(foreground="#ff8700", background="#0102ff", is_underlined=True)
    assert (console.lines[-1], console.line_styles[-1]) == ("new x", ((0, 3, orange),))
    console.append("\x1b[3mlast\n")  # the oldest line goes, its styles too
    assert [len(styles) for styles in console.line_styles] == [1, 1]
    assert line_styles_after(console, 2) == [((0, 4, TextStyle(is_italic=True)),)]

    # a gray of the 256 colors; an unknown kind of color, one cut short, and a code that
    # a console doesn't show (inverse): no change
    console.text = "\x1b[38;5;240mg\x1b[38;9;1;1;1m\x1b[48;2;1;2m\x1b[7mh"
    assert console.last_line_styles == [(0, 2, TextStyle(foreground="#585858"))]

    console.text = "\x1b[1mbold"  # replaced: from the plain style
    assert console.last_line_styles == [(0, 4, TextStyle(is_bold=True))]
    console.text = "plain"
    assert console.last_line_styles == []


#: a process's output, in pieces: text, line ends, ANSI codes (colors, a title, an
#: erased line) and the characters they are made of, which a cut leaves on their own
_OUTPUT_PIECES = [
    # text often: a cut in a styled part must leave it one part
    "a",
    "ab",
    "é",
    "text",
    "\n",
    "\r",
    "\r\n",
    "\x1b[31m",
    "\x1b[1;4m",
    "\x1b[0m",
    "\x1b[38;5;200m",
    "\x1b]0;title\x07",
    "\x1b[2K",
    "\x1b",
    "[",
    "3",
    "m",
    ";",
    "\x07",
]


@st.composite
def _cut_output(draw: st.DrawFn) -> tuple[str, list[int]]:
    """Draw an output, and where its pieces end: anywhere in it."""
    output = "".join(draw(st.lists(st.sampled_from(_OUTPUT_PIECES), max_size=12)))
    return output, sorted(draw(st.sets(st.integers(0, len(output)), max_size=4)))


# cheap examples, many: a style must meet a cut between two of its letters
@settings(max_examples=300)
@given(_cut_output(), st.integers(1, 3), st.booleans())
def test_a_console_shows_its_output_the_same_wherever_it_was_cut(
    cut_output: tuple[str, list[int]], max_lines: int, ansi_colors: bool
) -> None:
    output, ends = cut_output

    def shown(console: ConsoleView) -> tuple[object, ...]:
        return (
            console.text,
            list(console.lines),
            [list(styles) for styles in console.line_styles],
            list(console.last_line_styles),
            console.line_count,
        )

    whole = ConsoleView(max_lines=max_lines, ansi_colors=ansi_colors)
    whole.append(output)
    # as a process writes it: in pieces that end anywhere, an escape code or "\r\n" too
    pieces = ConsoleView(max_lines=max_lines, ansi_colors=ansi_colors)
    for start, end in zip([0, *ends], [*ends, len(output)]):
        pieces.append(output[start:end])

    assert shown(pieces) == shown(whole)


def test_a_console_saves_its_text_and_says_how_it_went(tmp_path: Path) -> None:
    app = Application(build_main_view=RunMainView)
    output, status_bar = app.main_view.output, app.main_view.status_bar

    output.export_text(tmp_path / "run.log")
    assert (tmp_path / "run.log").read_text(encoding="utf-8") == "Ready <ok>\n"
    assert status_bar.message == "Saved the output to run.log."
    output.export_text(tmp_path)  # a folder: not written
    assert status_bar.message.startswith(f"Can't save to {tmp_path.name}: ")

    with pytest.raises(OSError):  # noqa: PT011 (whichever the system raises)
        ConsoleView().export_text(tmp_path)  # outside a main view


def test_a_path_field_reads_a_relative_path_from_its_base_folder_and_shows_one_inside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study, elsewhere = tmp_path / "study", tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # the process started in another folder
    field = FilePathInputView(base_folder=study, text="inputs/model.med")

    assert (field.path, field.start_folder()) == (study / "inputs" / "model.med", study)
    field.text = str(elsewhere / "model.med")
    assert field.path == elsewhere / "model.med"
    # picked: inside the base folder relative to it, else whole
    inside = study / "inputs" / "model.med"
    assert field.path_text(inside) == str(Path("inputs", "model.med"))
    assert field.path_text(elsewhere / "model.med") == str(elsewhere / "model.med")
    # a relative base folder, from the working folder: inside once both are resolved
    field.base_folder = Path("..", "study")
    assert field.path_text(inside) == str(Path("inputs", "model.med"))
    # changed: the text stays, read from the new folder
    field.text = "inputs/model.med"
    field.base_folder = elsewhere
    assert (field.text, field.path) == ("inputs/model.med", elsewhere / "inputs" / "model.med")


def test_a_path_by_kind_cell_takes_its_row_s_kind_s_widget_and_base_folder(tmp_path: Path) -> None:
    study, own = tmp_path / "study", tmp_path / "own"
    view = StudyInputsMainView()
    view.show_study(study)
    table = view.files
    table.cell_widgets = {
        **table.cell_widgets,
        PATH: CellWidget.path_by(
            1,
            {
                INPUT_FILE: CellWidget.file_path(server_roots=(tmp_path,)),
                OUTPUT_FOLDER: CellWidget.folder_path(base_folder=own),
            },
            base_folder=study,
        ),
    }
    table.rows = [["Mesh", INPUT_FILE, ""], ["Results", OUTPUT_FOLDER, ""], ["Notes", "Text"], []]

    widgets = [table.cell_widget(row, PATH) for row in range(len(table.rows))]

    kinds = [None if widget is None else widget.kind for widget in widgets]
    assert kinds == [CellKind.FILE_PATH, CellKind.FOLDER_PATH, None, None]
    mesh, results = widgets[0], widgets[1]
    assert mesh is not None
    assert results is not None
    # the kind's own base folder, else the column's; a dialog opens there
    assert (mesh.start_folder(), results.start_folder()) == (study, own)
    assert mesh.path("inputs/mesh.med") == study / "inputs" / "mesh.med"
    assert mesh.path_text(study / "inputs" / "mesh.med") == str(Path("inputs", "mesh.med"))
    without_base = CellWidget.file_path(server_roots=(tmp_path,))
    assert (without_base.start_folder(), CellWidget.save_path().start_folder()) == (tmp_path, None)
    # the kinds' texts follow the language
    view.set_language("fr")
    translated = table.cell_widget(1, PATH)
    assert translated is not None
    assert translated.text == "Choisir un dossier"
    with pytest.raises(ValueError, match="with a COMBOBOX cell"):
        CellWidget.path_by(1, {"Notes": CellWidget.combobox()})


def test_saving_the_summary_asks_before_replacing_a_file_unless_the_picker_did(
    tmp_path: Path,
) -> None:
    view = StudyInputsMainView()
    view.status_bar.timeout = 0
    view.show_study(tmp_path)
    field, dialog = view.summary.file, view.replace_file
    summary = tmp_path / "summary.txt"

    view.save_summary()  # nowhere yet
    assert view.status_bar.message == "Type or pick where to save the summary."
    written: list[Path] = []
    view.write_file(field, written.append)
    assert written == []  # nothing to write while empty
    field.text = "summary"  # typed, from the study, its extension added
    view.save_summary()  # a new file: at once
    assert (summary.read_text().count("\n"), dialog.is_visible) == (4, False)
    summary.write_text("kept")
    view.save_summary()
    # the field's own texts
    question = (dialog.title, dialog.text, dialog.accept_text)
    assert question == ("Save as", "summary.txt already exists. Replace it?", "Replace")
    assert dialog.is_visible
    dialog.reject()
    assert summary.read_text() == "kept"
    view.save_summary()
    view.files.rows = view.files.rows[:1]  # changed while the user reads the question
    dialog.accept()
    assert summary.read_text().count("\n") == 4  # the rows of the click
    # agreed in the picker: no question again, for that file only, and one still open closes
    view.save_summary()
    field.remember_pick(summary)
    view.save_summary()
    assert (summary.read_text().count("\n"), dialog.is_visible) == (1, False)
    dialog.open()  # by the app itself: nothing to write once answered
    dialog.accept()
    assert summary.read_text().count("\n") == 1
    field.text = "other.txt"
    assert not field.is_replace_agreed
    # a folder there: asked, then the write fails, which the status bar says
    (tmp_path / "other.txt").mkdir()
    view.save_summary()
    dialog.accept()
    assert view.status_bar.message.startswith("Can't save 'other.txt': ")
    # a path rather than a field: asked too, in the main view's language
    view.set_language("fr")
    view.write_file(summary, written.append)
    assert (dialog.text, dialog.accept_text) == (
        "summary.txt existe déjà. Le remplacer ?",
        "Remplacer",
    )
    dialog.accept()
    assert written == [summary]


# a view's lists: set anew, never changed in place

_CHANGES_IN_PLACE: list[Callable[[list[Any]], object]] = [
    lambda items: items.append(["Ada"]),
    lambda items: items.extend([["Ada"]]),
    lambda items: items.insert(0, ["Ada"]),
    lambda items: items.pop(),
    lambda items: items.remove(["Bob"]),
    lambda items: items.clear(),
    lambda items: items.sort(),
    lambda items: items.reverse(),
    lambda items: items.__setitem__(0, ["Ada"]),
    lambda items: items.__setitem__(slice(0, 1), [["Ada"]]),
    lambda items: items.__delitem__(0),
]


@pytest.mark.parametrize("change", _CHANGES_IN_PLACE)
def test_a_view_s_list_and_its_inner_lists_refuse_a_change_in_place(
    change: Callable[[list[Any]], object],
) -> None:
    table = TableView(rows=[["Bob"]])

    with pytest.raises(TypeError, match=r"^TableView\.rows can't change in place"):
        change(table.rows)
    with pytest.raises(TypeError, match=r"^TableView\.rows can't change in place"):
        change(table.rows[0])

    assert table.rows == [["Bob"]]


def test_a_view_s_list_set_again_or_with_plus_equals_refuses_its_changes_too() -> None:
    points = MapView(points=[MapPoint(latitude=48.9, longitude=2.3)])
    shown = points.points

    points.points += [MapPoint(latitude=45.8, longitude=4.8)]
    points.points *= 2
    assert len(points.points) == 4
    assert len(shown) == 1  # set anew: the list read before is as it was
    with pytest.raises(TypeError, match=r"^MapView\.points can't change in place"):
        points.points.append(MapPoint(latitude=0, longitude=0))

    points.points = [MapPoint(latitude=0, longitude=0)]
    with pytest.raises(TypeError, match=r"^MapView\.points can't change in place"):
        points.points.pop()


def test_a_copy_of_a_view_s_list_is_a_plain_list_to_change() -> None:
    table = TableView(rows=[["Bob"]])

    for copied in (
        list(table.rows),
        copy.copy(table.rows),
        copy.deepcopy(table.rows),
        pickle.loads(pickle.dumps(table.rows)),  # noqa: S301 (our own data)
        [*table.rows, ["Ada"]],
    ):
        copied.append(["Eve"])
        assert type(copied) is list
    assert table.rows == [["Bob"]]
