"""Tests for views' own behavior, outside any backend: what they accept, refuse and keep."""

from __future__ import annotations

import datetime

import pytest
from attrs import Factory

from composeui.core.application import Application
from composeui.core.model import RefusedError
from composeui.core.view import (
    ConsoleView,
    FormView,
    GroupFormView,
    LabelView,
    LanguageMenu,
    ListView,
    MainView,
    NodeMark,
    RowInputView,
    TableView,
    TreeView,
    TypedFormDialogView,
    define_view,
    parse_date,
)
from tests.buildings import SITE
from tests.pages import InputsPage
from tests.splitter import StudySplitter
from tests.tabs import PipeTabs


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
