"""Tests of the web dialogs."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from composeui.core.registry import RendererType
from composeui.core.view import (
    DialogKind,
    DialogView,
    MainView,
    PageView,
    Router,
    TabPage,
    TabView,
    VerticalView,
    child,
    define_view,
)
from composeui.webcore.session import WebSession
from composeui.webcore.webapplication import WebApplication, WebModelApplication
from composeui.webcore.webrenderer import (
    WebRenderer,
    handle_event,
)
from examples.pipecatalogue import (
    PipeCatalogueMainView,
    PipeCatalogueModel,
)
from examples.pipecatalogue import PipeExpander as CataloguePipeExpander
from tests.dialogs import DialogsMainView
from tests.formdialog import PipeMainView as EditedPipeMainView
from tests.settingsdialog import NO_FOLDER, SettingsMainView
from tests.studydialog import StudyDialogMainView

if TYPE_CHECKING:
    from collections.abc import Iterator

    if sys.version_info >= (3, 11):
        import httpx2 as httpx
    else:
        import httpx
    from starlette.testclient import TestClient


from tests.webcore.support import (
    _Browser,
    _contains,
    _disable_on_submit,
    _element,
    _field_id,
    _find,
    _NoteMainView,
    _swapped,
    _widget_id,
)


def test_a_catalogue_pipe_s_edit_button_opens_the_form_dialog_on_it() -> None:
    views: list[PipeCatalogueMainView] = []

    class CatalogueApp(WebModelApplication[PipeCatalogueMainView, PipeCatalogueModel]):
        @override
        def setup_session(self, main_view: PipeCatalogueMainView) -> None:
            views.append(main_view)

    app = CatalogueApp(
        build_main_view=PipeCatalogueMainView,
        build_model=PipeCatalogueModel,
        setup_model=PipeCatalogueMainView.connect_model,
    )
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        add_id = _widget_id(view.add.add_pipe.renderer)
        name_id = _field_id(view.add.pipe.name)
        client.post(f"/_composeui/widget/{name_id}", data={"event": "input", "value": "Main line"})
        client.post(f"/_composeui/widget/{add_id}", data={"event": "click"})
        (pipe,) = view.catalogue.browser.pipes.item_views
        assert isinstance(pipe, CataloguePipeExpander)
        edit = pipe.buttons.edit.renderer

        body = client.post(f"/_composeui/widget/{_widget_id(edit)}", data={"event": "click"}).text

        dialog = _swapped(body, _widget_id(view.edit_dialog.renderer))
        assert "hidden" not in dialog.attributes
        name = _element(body, _field_id(view.edit_dialog.form.name))
        assert name.attributes["value"] == "Main line"


@pytest.fixture
def edited_pipe() -> Iterator[tuple[TestClient, EditedPipeMainView]]:
    """Serve an app editing a pipe in a form dialog; yield a client and its main view."""
    views: list[EditedPipeMainView] = []

    class EditApp(WebApplication[EditedPipeMainView]):
        @override
        def setup_session(self, main_view: EditedPipeMainView) -> None:
            views.append(main_view)

    app = EditApp(build_main_view=EditedPipeMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield client, view


def test_a_form_dialog_swaps_only_its_ok_as_its_form_s_checks_change(
    edited_pipe: tuple[TestClient, EditedPipeMainView],
) -> None:
    client, view = edited_pipe
    dialog_id = _widget_id(view.edit_dialog.renderer)
    accept_id = f"{dialog_id}-accept"
    name_id = _field_id(view.edit_dialog.form.name)

    body = client.post(
        f"/_composeui/widget/{_widget_id(view.edit.renderer)}", data={"event": "click"}
    ).text
    dialog = _swapped(body, dialog_id)
    assert "hidden" not in dialog.attributes
    assert _contains(dialog, name_id)  # the form, in the dialog
    assert "disabled" not in _element(body, accept_id).attributes

    # the name emptied: only OK swaps, disabled, the dialog left as the user has it
    body = client.post(f"/_composeui/widget/{name_id}", data={"event": "input", "value": ""}).text
    assert "disabled" in _swapped(body, accept_id).attributes
    assert "A name is mandatory" in body
    assert f'id="{dialog_id}"' not in body
    # OK anyway: refused, the dialog left open as it is
    body = client.post(f"/_composeui/widget/{dialog_id}", data={"event": "accept"}).text
    assert view.edit_dialog.is_visible
    assert f'id="{dialog_id}"' not in body

    client.post(f"/_composeui/widget/{name_id}", data={"event": "input", "value": "Return"})
    body = client.post(f"/_composeui/widget/{dialog_id}", data={"event": "accept"}).text
    assert "hidden" in _swapped(body, dialog_id).attributes  # closed
    assert "Return, 12 m" in body


@pytest.fixture
def study_dialog() -> Iterator[tuple[TestClient, StudyDialogMainView]]:
    """Serve an app opening a study from a content dialog; yield a client and its main view."""
    views: list[StudyDialogMainView] = []

    class StudyApp(WebApplication[StudyDialogMainView]):
        @override
        def setup_session(self, main_view: StudyDialogMainView) -> None:
            views.append(main_view)

    app = StudyApp(build_main_view=StudyDialogMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield client, view


def test_a_content_dialog_shows_its_view_whose_buttons_leave_it_open(
    study_dialog: tuple[TestClient, StudyDialogMainView],
) -> None:
    client, view = study_dialog
    content = view.open_dialog.content
    dialog_id = _widget_id(view.open_dialog.renderer)
    up_id, table_id = _widget_id(content.up.renderer), _widget_id(content.entries.renderer)

    body = client.post(
        f"/_composeui/widget/{_widget_id(view.open.renderer)}", data={"event": "click"}
    ).text
    dialog = _swapped(body, dialog_id)
    assert "hidden" not in dialog.attributes
    assert all(_contains(dialog, element_id) for element_id in (up_id, table_id))
    assert "disabled" in _element(body, f"{dialog_id}-accept").attributes  # nothing selected

    body = client.post(f"/_composeui/widget/{up_id}", data={"event": "click"}).text

    assert view.open_dialog.is_visible
    assert f'id="{dialog_id}"' not in body  # left as the user has it
    assert "notes.txt" in _swapped(body, table_id).text


def test_a_dialog_s_own_buttons_and_check_show_on_the_web_and_act_on_their_posts() -> None:
    views: list[SettingsMainView] = []

    class SettingsApp(WebApplication[SettingsMainView]):
        @override
        def setup_session(self, main_view: SettingsMainView) -> None:
            main_view.settings.open()
            views.append(main_view)

    with _Browser(SettingsApp(build_main_view=SettingsMainView).create_starlette_app()) as client:
        page = client.get("/").text
        (view,) = views
        settings = view.settings
        dialog_id = _widget_id(settings.renderer)
        apply_id, discard_id = (
            _widget_id(settings.apply.renderer),
            _widget_id(settings.discard.renderer),
        )
        log_id = _widget_id(settings.log_view.renderer)
        field_id = _widget_id(settings.content.folder.renderer)
        dialog = _element(page, dialog_id)
        assert all(_contains(dialog, element_id) for element_id in (apply_id, discard_id, log_id))
        footer = [attributes.get("id") for tag, attributes in dialog.descendants if tag == "button"]
        assert footer[-3:] == [apply_id, discard_id, f"{dialog_id}-accept"]  # after Cancel

        body = client.post(
            f"/_composeui/widget/{field_id}", data={"event": "input", "value": ""}
        ).text
        assert NO_FOLDER in _swapped(body, log_id).text
        assert "disabled" in _swapped(body, f"{dialog_id}-accept").attributes
        assert "disabled" in _swapped(body, apply_id).attributes
        assert (
            client.post(f"/_composeui/widget/{apply_id}", data={"event": "click"}).status_code
            == 400
        )

        client.post(f"/_composeui/widget/{field_id}", data={"event": "input", "value": "out"})
        body = client.post(f"/_composeui/widget/{apply_id}", data={"event": "click"}).text
        assert f'id="{dialog_id}"' not in body  # left open, as the user has it
        body = client.post(f"/_composeui/widget/{discard_id}", data={"event": "click"}).text
        assert "hidden" in _swapped(body, dialog_id).attributes
    assert view.answers == ["apply", "discard"]


@define_view
class _ToolBox(VerticalView):
    tool: DialogView = child(DialogView, title="Tool", text="Run the tool?")


@define_view
class _BoxTab(TabPage):
    box: _ToolBox = child(_ToolBox)


@define_view
class _ToolTabs(TabView):
    first: TabPage = child(TabPage, title="First")
    tools: _BoxTab = child(_BoxTab, title="Tools")


@define_view
class _HomePage(PageView):
    route = "home"
    page_title = "Home"


@define_view
class _ToolsPage(PageView):
    route = "tools"
    page_title = "Tools"

    box: _ToolBox = child(_ToolBox)
    tabs: _ToolTabs = child(_ToolTabs)


@define_view
class _ToolsRouter(Router):
    home: _HomePage = child(_HomePage)
    tools: _ToolsPage = child(_ToolsPage)


@define_view
class _ToolsMainView(MainView):
    app_title = "Tools"
    extension = ".tools"

    router: _ToolsRouter = child(_ToolsRouter)


def test_the_dialogs_of_a_page_not_built_follow_its_enabled_state_then_their_tab_s() -> None:
    view = _ToolsMainView()
    session = WebSession(view)
    page = view.router.tools
    tool = page.tabs.tools.box.tool  # in a tab not shown, of a page not built
    answers: list[str] = []
    tool.accepted.connect(lambda: answers.append("tool"))
    page.is_enabled = False
    tool.open()  # the app opens it whatever the page shown
    tool_id = _widget_id(tool.renderer)

    session.handle_event(tool_id, "accept", {})  # a disabled dialog ignores its answer
    assert (answers, tool.is_visible) == ([], True)
    page.is_enabled = True
    session.handle_event(tool_id, "accept", {})
    assert answers == ["tool"]

    session.open_route("tools")  # its tab not built yet: the tab follows the page meanwhile
    page.tabs.tools.is_enabled = False
    tool.open()
    session.handle_event(tool_id, "accept", {})
    assert (answers, tool.is_visible) == (["tool"], True)
    session.close()


def test_a_dialog_keeps_its_container_once_its_page_rendered_again_is_shown() -> None:
    view = _ToolsMainView()
    view.render(RendererType.WEB)
    view.render(RendererType.WEB)  # as a test or a script may: its column adopts the dialog
    page = view.router.tools
    tool = page.box.tool
    answers: list[str] = []
    tool.accepted.connect(lambda: answers.append("tool"))

    view.router.navigate("tools")
    page.box.is_enabled = False
    tool.open()

    assert isinstance(tool.renderer, WebRenderer)
    handle_event(tool.renderer, "accept", {})  # a disabled dialog ignores its answer
    assert (answers, tool.is_visible) == ([], True)


@pytest.fixture
def dialog_views() -> list[DialogsMainView]:
    """Each session's main view, kept by `dialog_client`'s app."""
    return []


@pytest.fixture
def dialog_client(dialog_views: list[DialogsMainView]) -> Iterator[TestClient]:
    class DialogsApp(WebApplication[DialogsMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=DialogsMainView)

        @override
        def setup_session(self, main_view: DialogsMainView) -> None:
            dialog_views.append(main_view)

    with _Browser(DialogsApp().create_starlette_app()) as client:
        client.get("/")  # starts the session
        yield client


@pytest.fixture
def dialogs_main_view(
    dialog_views: list[DialogsMainView], dialog_client: TestClient
) -> DialogsMainView:
    dialog_client.get("/")  # the client's own session: still the one view built so far
    (main_view,) = dialog_views
    return main_view


def test_an_action_opens_a_dialog_whose_answers_close_it(
    dialogs_main_view: DialogsMainView, dialog_client: TestClient
) -> None:
    dialog_id = _widget_id(dialogs_main_view.confirm_clear.renderer)
    name_id = _widget_id(dialogs_main_view.name.renderer)
    clear_id = _widget_id(dialogs_main_view.edit_menu.clear.renderer)

    def post(widget_id: str, event: str) -> str:
        response: httpx.Response = dialog_client.post(
            f"/_composeui/widget/{widget_id}", data={"event": event}
        )
        return response.text

    closed = _element(dialog_client.get("/").text, dialog_id)
    assert closed.tag == "dialog"
    assert "hidden" in closed.attributes

    body = post(clear_id, "triggered")
    dialog = _swapped(body, dialog_id)
    assert "hidden" not in dialog.attributes
    assert dialog.attributes["hx-trigger"] == "cancel"  # Escape
    title_id = dialog.attributes["aria-labelledby"]
    text_id = dialog.attributes["aria-describedby"]
    assert title_id is not None
    assert text_id is not None
    assert _element(body, title_id).text == "Clear the name"
    assert _element(body, text_id).text == "The name will be lost."
    buttons = [
        attributes.get("hx-vals") for tag, attributes in dialog.descendants if tag == "button"
    ]
    assert buttons == ['{"event": "reject"}', '{"event": "accept"}']

    body = post(dialog_id, "dismiss")  # Escape rejects a confirmation
    assert "hidden" in _swapped(body, dialog_id).attributes
    assert _find(body, name_id) is None

    post(clear_id, "triggered")
    body = post(dialog_id, "accept")
    assert "hidden" in _swapped(body, dialog_id).attributes
    assert _swapped(body, name_id).text == ""

    assert post(dialog_id, "accept") == ""  # a second click on the closed dialog


def test_a_disabled_dialog_cannot_be_answered(
    dialogs_main_view: DialogsMainView, dialog_client: TestClient
) -> None:
    dialog = dialogs_main_view.confirm_clear
    dialog_id = _widget_id(dialog.renderer)
    dialog.is_enabled = False
    dialog.text = "<b>busy</b>"
    dialog.open()

    page = dialog_client.get("/").text
    element = _element(page, dialog_id)
    assert "hx-trigger" not in element.attributes
    assert "data-keep-open" in element.attributes  # the page's script keeps it open
    buttons = [attributes for tag, attributes in element.descendants if tag == "button"]
    assert all("disabled" in attributes for attributes in buttons)
    assert "<b>busy</b>" in element.text
    assert all(tag != "b" for tag, _ in element.descendants)

    dialog_client.post(f"/_composeui/widget/{dialog_id}", data={"event": "accept"})
    assert dialog.is_visible
    assert dialogs_main_view.name.text == "Ada"


def test_a_page_dialog_shows_outside_the_pages_hidden_slots(
    notes: tuple[TestClient, _NoteMainView],
) -> None:
    """A page that isn't shown hides its content: its dialog would never show."""
    client, main_view = notes
    main_view.pages.note.note.open()
    page = client.get("/inputs").text

    dialog_id = _widget_id(main_view.pages.note.note.renderer)
    assert "hidden" not in _element(page, dialog_id).attributes
    router = _element(page, _widget_id(main_view.pages.renderer))
    assert all(attributes.get("id") != dialog_id for _, attributes in router.descendants)


@pytest.mark.parametrize("disabled", ["page", "router"])
def test_disabling_a_page_disables_its_dialog_drawn_apart_from_it(
    notes: tuple[TestClient, _NoteMainView], disabled: str
) -> None:
    client, main_view = notes
    dialog = main_view.pages.note.note
    dialog.open()
    container = main_view.pages.note if disabled == "page" else main_view.pages
    submit_id = _disable_on_submit(main_view, container)
    body = client.post(f"/_composeui/widget/{submit_id}", data={"event": "click"}).text

    dialog_id = _widget_id(dialog.renderer)
    swapped = _swapped(body, dialog_id)
    assert "hx-trigger" not in swapped.attributes  # Escape doesn't dismiss it
    buttons = [attributes for tag, attributes in swapped.descendants if tag == "button"]
    assert all("disabled" in attributes for attributes in buttons)
    # a stale page's answer is ignored, as a disabled dialog's own
    client.post(f"/_composeui/widget/{dialog_id}", data={"event": "accept"})
    assert dialog.is_visible


@pytest.mark.parametrize(
    ("kind", "is_destructive", "focused", "accept_class"),
    [
        (DialogKind.CONFIRM, True, "reject", "btn-error"),
        (DialogKind.CONFIRM, False, "accept", "btn-primary"),
        (DialogKind.MESSAGE, True, "accept", "btn-primary"),  # its only button
    ],
)
def test_a_destructive_confirmation_focuses_its_rejecting_button_on_the_web(
    notes: tuple[TestClient, _NoteMainView],
    kind: DialogKind,
    *,
    is_destructive: bool,
    focused: str,
    accept_class: str,
) -> None:
    """Enter presses the focused button: a destructive confirmation's mustn't accept."""
    client, main_view = notes
    dialog = main_view.pages.note.note
    dialog.kind = kind
    dialog.is_destructive = is_destructive
    dialog.open()

    element = _element(client.get("/inputs").text, _widget_id(dialog.renderer))
    buttons = {
        json.loads(attributes["hx-vals"] or "")["event"]: attributes
        for tag, attributes in element.descendants
        if tag == "button"
    }
    assert [event for event, attributes in buttons.items() if "autofocus" in attributes] == [
        focused
    ]
    assert accept_class in (buttons["accept"]["class"] or "").split()


@pytest.mark.parametrize("question", ["replace_file", "discard_changes"])
def test_the_main_view_s_questions_before_losing_data_focus_cancel(
    notes: tuple[TestClient, _NoteMainView], question: str
) -> None:
    client, main_view = notes
    dialog: DialogView = getattr(main_view, question)
    dialog.open()

    element = _element(client.get("/inputs").text, _widget_id(dialog.renderer))
    focused = [
        attributes.get("hx-vals")
        for tag, attributes in element.descendants
        if tag == "button" and "autofocus" in attributes
    ]
    assert focused == ['{"event": "reject"}']
