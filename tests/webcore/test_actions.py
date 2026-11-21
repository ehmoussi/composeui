"""Tests of the web actions, menus and toolbars."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from attrs import Factory

from composeui.core._views.actions import SaveAsAction
from composeui.core.registry import RendererType
from composeui.core.view import (
    ActionView,
    MainView,
    Menu,
    SeparatorAction,
    define_view,
)
from composeui.webcore._renderers.navigation import WebMainRenderer
from composeui.webcore.changes import collect_dirty
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import (
    UnsupportedEventError,
    WebRenderer,
    handle_event,
    render_dirty,
)
from examples.webhello import GreetingStyle, HelloMainView
from tests.markdown import HelpMainView, HelpViewerMainView

if TYPE_CHECKING:
    if sys.version_info >= (3, 11):
        import httpx2 as httpx
    else:
        import httpx
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from examples.pipeform import PipeMainView
    from tests.toolbar import ToolBarMainView


from tests.webcore.support import (
    _action_id,
    _Browser,
    _count,
    _element,
    _field_id,
    _find,
    _HelloApp,
    _part,
    _selected,
    _swapped,
    _type_name,
    _widget_id,
)


def test_a_pick_file_action_uploads_the_file_and_hands_it_over(
    help_views: list[HelpMainView], help_client: TestClient
) -> None:
    page = help_client.get("/").text
    (main_view,) = help_views
    action = main_view.help_menu.open_help
    action_id = _widget_id(action.renderer)
    (picker,) = [a for tag, a in _element(page, action_id).descendants if tag == "input"]
    assert picker["type"] == "file"
    assert picker["accept"] == ".md,.markdown"
    assert picker["hx-post"] == f"/widget/{action_id}/file"
    picked: list[tuple[Path, bool]] = []
    action.file_picked.connect(lambda path: picked.append((path, path.is_file())))
    help_id = _widget_id(main_view.help.renderer)

    response = help_client.post(
        f"/widget/{action_id}/file", files={"file": ("notes.md", b"# Notes", "text/markdown")}
    )
    assert response.status_code == 200
    assert _swapped(response.text, help_id).text == "Notes\n"
    assert main_view.help.text == "# Notes"
    # a copy under its name while the callbacks run, gone after
    ((path, was_there),) = picked
    assert (path.name, was_there) == ("notes.md", True)
    assert not path.exists()

    # refused: another type, or no file at all
    response = help_client.post(
        f"/widget/{action_id}/file", files={"file": ("notes.txt", b"plain", "text/plain")}
    )
    status = _swapped(response.text, _widget_id(main_view.status_bar.renderer))
    assert status.text == "Can't open 'notes.txt': expected a .md or .markdown file."
    assert main_view.help.text == "# Notes"
    assert help_client.post(f"/widget/{action_id}/file").status_code == 400
    # another action takes no file, and an unknown widget is none of the session's
    open_id = _widget_id(main_view.file_menu.open_file.renderer)
    files = {"file": ("notes.md", b"# Other", "text/markdown")}
    assert help_client.post(f"/widget/{open_id}/file", files=files).status_code == 400
    assert help_client.post("/widget/cui-0/file", files=files).status_code == 404
    assert len(picked) == 1


def test_saving_downloads_the_session_state(main_view: HelloMainView, client: TestClient) -> None:
    _type_name(client, main_view, "Bob")

    response = client.get("/state")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="hello-composeui.hello"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.text)["views"]["form"]["name"]["text"] == "Bob"


def test_a_saved_state_opens_in_another_browser(app: _HelloApp) -> None:
    web = app.create_starlette_app()
    with _Browser(web) as alice, _Browser(web) as bob:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = app.session_views
        _type_name(alice, alice_view, "Alice")
        style_id = _field_id(alice_view.form.style)
        alice.post(f"/widget/{style_id}", data={style_id: "FORMAL", "event": "change"})
        saved = alice.get("/state").content

        response = bob.post("/state", files={"file": ("study.hello", saved)})

        # a load can change anything: the page reloads instead of swapping fragments
        assert response.headers["hx-refresh"] == "true"
        assert bob_view.form.name.text == "Alice"
        assert bob_view.form.style.value is GreetingStyle.FORMAL
        assert 'value="Alice"' in bob.get("/").text
        # the next save offers the name the state was opened from
        assert 'filename="study.hello"' in bob.get("/state").headers["content-disposition"]


def _read_name(job: object) -> str:
    """Read a name, as a session's start reads what the next one reads again."""
    del job
    return "Ada"


def test_what_a_session_s_start_jobs_give_is_no_unsaved_change() -> None:
    class ReadingApp(_HelloApp):
        @override
        def setup_session(self, main_view: HelloMainView) -> None:
            super().setup_session(main_view)
            job = main_view.jobs.start(_read_name)
            job.finished.connect(lambda name: setattr(main_view.form.name, "text", name))

    app = ReadingApp()
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (main_view,) = app.session_views
        for _ in range(200):  # the job's result, handed to the session after a request
            client.get("/jobs")
            if main_view.form.name.text == "Ada":
                break
            time.sleep(0.05)
        client.get("/jobs")  # after the job's callbacks, which hold the session's lock

        assert main_view.form.name.text == "Ada"
        assert not main_view.has_unsaved_changes()


@pytest.mark.parametrize(
    ("filename", "content", "reason"),
    [
        ("study.pipe", b"{}", "expected a .hello file"),
        ("study.hello", b"{not json", "isn&#39;t a valid .hello file"),
        ("study.hello", b"[1, 2]", "isn&#39;t a valid .hello file"),
        ("study.hello", b" " * (5 * 1024 * 1024 + 1), "the file is too large"),
        # fails halfway: the valid name must not be applied before the bad age fails
        (
            "study.hello",
            b'{"form": {"name": {"text": "Eve"}, "age": {"value": "abc"}}}',
            "doesn&#39;t match this application",
        ),
    ],
    # not the content: the too-large one would make an id of 5 MiB, longer than Windows
    # allows the PYTEST_CURRENT_TEST variable that holds it
    ids=["other-extension", "not-json", "not-an-object", "too-large", "half-valid"],
)
def test_a_rejected_state_file_changes_nothing_and_says_why(
    main_view: HelloMainView, client: TestClient, filename: str, content: bytes, reason: str
) -> None:
    _type_name(client, main_view, "Bob")
    main_view._mark_saved()  # noqa: SLF001 (as Save does: opened without asking to discard Bob)

    response = client.post("/state", files={"file": (filename, content)})

    assert "hx-refresh" not in response.headers
    status_bar_id = _widget_id(main_view.status_bar.renderer)
    assert f'<footer id="{status_bar_id}" hx-swap-oob="true"' in response.text
    assert reason in response.text
    assert main_view.form.name.text == "Bob"
    assert main_view.state_filepath is None


def test_an_upload_over_unsaved_changes_opens_once_the_user_discards_them(
    main_view: HelloMainView, client: TestClient
) -> None:
    def study(name: str) -> bytes:
        saved = HelloMainView()
        saved.form.name.text = name
        return json.dumps(saved.file_data()).encode()

    _type_name(client, main_view, "Bob")
    discard_id = _widget_id(main_view.discard_changes.renderer)

    # refused before the question: nothing to discard for
    response = client.post("/state", files={"file": ("study.pipe", b"{}")})
    assert "expected a .hello file" in response.text
    assert not main_view.discard_changes.is_visible
    response = client.post("/state", files={"file": ("alice.hello", study("Alice"))})
    assert f'id="{discard_id}" hx-swap-oob="true"' in response.text
    # picked again before the answer: the last file is the one to open
    client.post("/state", files={"file": ("ada.hello", study("Ada"))})
    assert main_view.form.name.text == "Bob"

    response = client.post(f"/widget/{discard_id}", data={"event": "accept"})

    assert main_view.form.name.text == "Ada"
    assert main_view.state_filepath == Path("ada.hello")
    assert f'id="{_field_id(main_view.form.name)}" hx-swap-oob="true"' in response.text
    assert not main_view.has_unsaved_changes()


def test_save_s_post_saves_the_study_and_a_link_s_download_does_not(
    main_view: HelloMainView, client: TestClient
) -> None:
    _type_name(client, main_view, "Bob")

    client.get("/state")  # e.g. a link from another site: the user may never get the file
    assert main_view.has_unsaved_changes()
    client.post("/state/download", data={"trigger": _action_id(main_view.file_menu.save)})
    assert not main_view.has_unsaved_changes()


def test_save_downloads_a_study_opened_from_a_file_and_writes_none_on_the_server(
    main_view: HelloMainView, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    main_view.state_filepath = Path("ada.hello")  # as an Open names the study: the user's file

    response = client.post(
        "/state/download", data={"trigger": _action_id(main_view.file_menu.save)}
    )

    assert response.status_code == 200
    assert "ada.hello" in response.headers["content-disposition"]
    assert list(tmp_path.iterdir()) == []


def test_the_file_menu_is_buttons_in_the_header(
    main_view: HelloMainView, client: TestClient
) -> None:
    menu = main_view.file_menu
    assert not menu.is_visible  # "popped up" in Qt terms; ignored, the buttons always show

    page = client.get("/").text

    header = page[page.index("<header") : page.index("</header>")]
    assert _element(header, _widget_id(menu.renderer)).tag == "div"
    new = _element(header, _action_id(menu.new))
    assert new.attributes["hx-post"] == f"/widget/{_action_id(menu.new)}"
    open_file = _element(header, _action_id(menu.open_file))
    assert ("input", "file") in [(tag, attrs.get("type")) for tag, attrs in open_file.descendants]
    save = _element(header, _action_id(menu.save))
    assert save.tag == "button"
    assert (save.attributes["form"], save.attributes["value"]) == (
        "cui-save",
        _action_id(menu.save),
    )
    assert '<form id="cui-save" method="post" action="/state/download" hidden>' in page
    # nothing left for a dropdown: the separator only set Exit apart
    menu_html = header[header.index(f'id="{_widget_id(menu.renderer)}"') :]
    assert "<ul" not in menu_html[: menu_html.index(f'id="{_action_id(menu.save)}"')]
    assert 'role="separator"' not in header


def test_an_app_without_studies_has_no_file_buttons() -> None:
    views: list[HelpViewerMainView] = []

    class ViewerApp(WebApplication[HelpViewerMainView]):
        @override
        def setup_session(self, main_view: HelpViewerMainView) -> None:
            views.append(main_view)

    app = ViewerApp(build_main_view=HelpViewerMainView)
    with _Browser(app.create_starlette_app()) as client:
        page = client.get("/").text
    header = page[page.index("<header") : page.index("</header>")]
    assert "Open Help" in header
    assert not any(text in header for text in (">New<", ">Open<", ">Save<", "/state"))
    (main_view,) = views
    assert main_view.file_menu.renderer is None  # never rendered


def test_another_menu_is_a_dropdown_under_its_title() -> None:
    @define_view
    class ViewMenu(Menu):
        zoom_in: ActionView = Factory(lambda: ActionView(text="Zoom in"))
        separator: SeparatorAction = Factory(SeparatorAction)
        zoom_out: ActionView = Factory(lambda: ActionView(text="Zoom out"))

    menu = ViewMenu(title="View")
    menu.render(RendererType.WEB)
    assert isinstance(menu.renderer, WebRenderer)

    markup = menu.renderer.to_html()

    assert re.search(r'role="button"[^>]*aria-haspopup="menu">View<', markup)
    dropdown = markup[markup.index("<ul") : markup.index("</ul>")]
    for action in (menu.zoom_in, menu.zoom_out):
        assert _element(dropdown, _action_id(action)).tag == "li"
    assert 'role="separator"' in dropdown


@pytest.mark.parametrize(("action", "key"), [("new", "N"), ("open_file", "O"), ("save", "S")])
def test_menu_shortcuts_avoid_the_browsers_own(
    main_view: HelloMainView, client: TestClient, action: str, key: str
) -> None:
    """Ctrl+N/O/S belong to the browser (new window, open file, save page)."""
    page = client.get("/").text
    button = _element(page, _action_id(getattr(main_view.file_menu, action)))
    elements = [(button.tag, button.attributes), *button.descendants]

    assert f"(Alt+Shift+{key})" in str(button.attributes.get("title"))
    # what the page's key handler clicks when Alt+Shift+<key> is pressed
    assert f"Key{key}" in [attributes.get("data-shortcut") for _, attributes in elements]
    assert "Ctrl" not in page[page.index("<header") : page.index("</header>")]


@pytest.mark.parametrize("action", ["save_as", "exit_app"])
def test_actions_a_browser_already_has_are_left_out(
    main_view: HelloMainView, client: TestClient, action: str
) -> None:
    """Save As downloads just like Save; a web page is left by closing its tab."""
    page = client.get("/").text
    left_out = _element(page, _action_id(getattr(main_view.file_menu, action)))

    # kept as a hidden placeholder, so a later change to the action still has a target
    assert "hidden" in left_out.attributes
    assert left_out.descendants == []
    assert "data-shortcut" not in left_out.attributes


def test_save_as_alone_in_its_menu_is_its_download_button() -> None:
    @define_view
    class ExportMenu(Menu):
        save_as: SaveAsAction = Factory(SaveAsAction)

    export = ExportMenu(title="Export")
    export.render(RendererType.WEB)
    assert isinstance(export.renderer, WebRenderer)

    button = _element(export.renderer.to_html(), _action_id(export.save_as))

    assert (button.tag, button.attributes["type"]) == ("button", "submit")
    assert button.attributes["form"] == "cui-save"
    # no Alt+Shift+S: Save's, wherever Save is
    assert "data-shortcut" not in button.attributes


def test_an_action_fires_its_triggered_unless_disabled() -> None:
    # a plain action: every File menu one also does more (New, Exit, Save, Open)
    action = ActionView(text="Refresh")
    action.render(RendererType.WEB)
    renderer = action.renderer
    assert isinstance(renderer, WebRenderer)
    triggered = _count(action.triggered)

    handle_event(renderer, "triggered", {})

    assert len(triggered) == 1

    action.is_enabled = False

    with pytest.raises(UnsupportedEventError):  # the route answers 400
        handle_event(renderer, "triggered", {})
    assert len(triggered) == 1


def test_exit_ends_the_session(
    app: _HelloApp, main_view: HelloMainView, client: TestClient
) -> None:
    field_id = _field_id(main_view.form.name)

    response = client.post(
        f"/widget/{_action_id(main_view.file_menu.exit_app)}", data={"event": "triggered"}
    )

    assert response.headers["hx-redirect"] == "/"
    stale = client.post(f"/widget/{field_id}", data={"value": "x", "event": "input"})
    assert stale.headers["hx-refresh"] == "true"
    client.get("/")
    assert len(app.session_views) == 2  # the redirect lands on a fresh session


@pytest.mark.parametrize("action", ["save", "save_as"])
def test_a_save_post_fires_its_action_then_downloads(
    main_view: HelloMainView, client: TestClient, action: str
) -> None:
    save = getattr(main_view.file_menu, action)
    triggered = _count(save.triggered)
    _type_name(client, main_view, "Bob")

    response = client.post("/state/download", data={"trigger": _action_id(save)})

    assert len(triggered) == 1
    assert "attachment" in response.headers["content-disposition"]
    assert json.loads(response.text)["views"]["form"]["name"]["text"] == "Bob"


@pytest.mark.parametrize("data", [{}, {"trigger": "cui-0"}], ids=["none", "not-an-action"])
def test_a_save_post_without_its_action_only_downloads(
    main_view: HelloMainView, client: TestClient, data: dict[str, str]
) -> None:
    menu = main_view.file_menu
    saves = [_count(menu.save.triggered), _count(menu.save_as.triggered)]

    response = client.post("/state/download", data=data)

    assert "attachment" in response.headers["content-disposition"]
    assert saves == [[], []]


def test_an_open_post_without_a_file_is_refused(client: TestClient) -> None:
    response = client.post("/state", data={"trigger": "none"})

    assert (response.status_code, response.text) == (400, "No file uploaded")


def test_a_state_link_downloads_without_firing_save(
    main_view: HelloMainView, client: TestClient
) -> None:
    """A GET changes nothing: a browser follows another site's link with the cookie."""
    save = main_view.file_menu.save
    triggered = _count(save.triggered)

    response = client.get(f"/state?trigger={_action_id(save)}")

    assert "attachment" in response.headers["content-disposition"]
    assert triggered == []


def test_the_open_upload_fires_its_action_then_loads(
    main_view: HelloMainView, client: TestClient
) -> None:
    open_file = main_view.file_menu.open_file
    triggered = _count(open_file.triggered)
    saved = json.dumps({"form": {"name": {"text": "Zoe"}}}).encode()

    response = client.post(
        "/state",
        files={"file": ("study.hello", saved)},
        data={"trigger": _action_id(open_file)},
    )

    assert len(triggered) == 1
    assert response.headers["hx-refresh"] == "true"
    assert main_view.form.name.text == "Zoe"


def test_the_open_picker_offers_only_the_apps_files(
    main_view: HelloMainView, client: TestClient
) -> None:
    open_file = main_view.file_menu.open_file
    file_inputs = re.compile(r'<input type="file"[^>]*>')

    page = client.get("/").text
    # renamed later: the action's fragment is swapped on its own, and keeps the filter
    open_file.text = "Open study"
    fragment = client.get(f"/widget/{_action_id(open_file)}").text

    assert [re.findall(r'accept="([^"]*)"', tag) for tag in file_inputs.findall(page)] == [
        [".hello"]
    ]
    assert "Open study" in fragment
    assert 'accept=".hello"' in "".join(file_inputs.findall(fragment))


def test_triggering_a_checkable_action_toggles_its_check_mark() -> None:
    action = ActionView(text="Wrap", is_checkable=True)
    action.render(RendererType.WEB)
    renderer = action.renderer
    assert isinstance(renderer, WebRenderer)
    renderer.to_html()  # on the page, as in its menu

    # the item comes back as an out-of-band fragment, with its check mark toggled
    assert ">✓ Wrap</span>" in handle_event(renderer, "triggered", {})
    assert ">Wrap</span>" in handle_event(renderer, "triggered", {})


def test_new_clears_the_form_in_place(
    app: _HelloApp, main_view: HelloMainView, client: TestClient
) -> None:
    form = main_view.form
    triggered = _count(main_view.file_menu.new.triggered)
    _type_name(client, main_view, "Bob")
    client.post(f"/widget/{_field_id(form.age)}", data={"value": "41", "event": "input"})

    client.post(f"/widget/{_action_id(main_view.file_menu.new)}", data={"event": "triggered"})
    assert form.name.text == "Bob"  # unsaved: kept until the user agrees to discard it
    response = client.post(
        f"/widget/{_widget_id(main_view.discard_changes.renderer)}", data={"event": "accept"}
    )

    assert len(triggered) == 1
    assert form.name.text == ""
    assert form.age.value is None
    # reset in place: every field New changed comes back out of band, no reload
    assert "hx-refresh" not in response.headers
    for widget_id in (
        _field_id(form.name),
        _field_id(form.age),
        _widget_id(main_view.summary.renderer),
    ):
        assert f'id="{widget_id}" hx-swap-oob="true"' in response.text
    assert "Nobody hasn&#39;t said how old they are." in response.text
    assert len(app.session_views) == 1


def test_a_pipe_study_from_first_page_to_reopening_it_elsewhere(
    pipe_web: Starlette, pipe_views: list[PipeMainView]
) -> None:
    """One study through the whole web stack, the way a user drives it.

    Every step checks both what the browser receives (each changed fragment out of band,
    never the field being edited) and the views behind it.
    """
    htmx = {"HX-Request": "true"}
    with _Browser(pipe_web, headers=htmx) as alice, _Browser(pipe_web, headers=htmx) as bob:
        page = alice.get("/").text
        (view,) = pipe_views
        form = view.pages.inputs.pipe_form
        name_id, material_id = _field_id(form.name), _field_id(form.material)
        edge_id, radius_id = _field_id(form.edge_type), _field_id(form.main_pipe.radius)
        name_log_id = _widget_id(_part(form.name, "log"))
        fillet_id, chamfer_id = _widget_id(form.fillet.renderer), _widget_id(form.chamfer.renderer)
        form_log_id = _widget_id(form.log_view.renderer)

        def post(widget_id: str, data: dict[str, str]) -> str:
            response: httpx.Response = alice.post(f"/widget/{widget_id}", data=data)
            assert response.status_code == 200
            assert _find(response.text, widget_id) is None  # never the edited field
            return response.text

        # the page as first served: rows, titled groups, edge options hidden
        for label in ("Name", "Material", "Radius", "Half Length", "Edge Type"):
            assert f">{label}<" in page  # Edge Type then its help's "?"
        assert ">Main Pipe</legend>" in page
        assert _element(page, name_log_id).text == "A name is mandatory"
        assert _selected(_element(page, material_id)) == ["Steel"]
        assert _selected(_element(page, edge_id)) == ["Normal"]
        for group_id in (fillet_id, chamfer_id):
            assert "hidden" in _element(page, group_id).attributes
        assert "hidden" in _element(page, form_log_id).attributes

        # a name clears its row's message
        body = post(name_id, {"value": "Tee", "event": "input"})
        assert form.name.text == "Tee"
        assert "hidden" in _swapped(body, name_log_id).attributes

        # another material changes nothing else on the page
        assert post(material_id, {material_id: "Copper", "event": "change"}) == ""
        assert form.material.value is not None
        assert form.material.value.value == "Copper"

        # Fillet shows its group and says so in the status bar
        body = post(edge_id, {edge_id: "Fillet", "event": "change"})
        assert "hidden" not in _swapped(body, fillet_id).attributes
        assert _swapped(body, _widget_id(view.status_bar.renderer)).text == (
            "Edge type changed: Fillet"
        )
        assert _find(body, chamfer_id) is None  # still hidden: unchanged

        # a main radius below the incident one fails the cross-field check, which is
        # wired to `editing_finished`: typing alone doesn't run it...
        assert _find(post(radius_id, {"value": "5", "event": "input"}), form_log_id) is None
        body = post(radius_id, {"value": "5", "event": "change"})
        log = _swapped(body, form_log_id)
        assert "hidden" not in log.attributes
        assert "incident radius" in log.text
        # it marks the two radii it is about through their rows' logs, which the page
        # marks the fields from: the field being typed in is never swapped
        _assert_radii_marked(body, form, marked=True)
        # and a page served meanwhile shows the field invalid from the start
        field_html = _part(form.main_pipe.radius, "field").to_html()
        assert _element(field_html, radius_id).attributes["aria-invalid"] == "true"
        # ...until it is fixed
        post(radius_id, {"value": "60", "event": "input"})
        body = post(radius_id, {"value": "60", "event": "change"})
        assert "hidden" in _swapped(body, form_log_id).attributes
        _assert_radii_marked(body, form, marked=False)
        assert form.log_view.log_message == ""

        # saved, then opened in another browser's session
        saved = alice.get("/state").content
        bob.get("/")
        reopened = pipe_views[1].pages.inputs.pipe_form
        assert (
            bob.post("/state", files={"file": ("tee.pipe", saved)}).headers["hx-refresh"] == "true"
        )
        _assert_shows_the_tee_study(bob.get("/").text, reopened)


def _assert_radii_marked(body: str, form: Any, *, marked: bool) -> None:
    """Check `body` swaps both radii's logs, flagged by a failing form check or not."""
    for row in (form.main_pipe.radius, form.incident_pipe.radius):
        log = _swapped(body, _widget_id(_part(row, "log")))
        assert ("data-form-error" in log.attributes) is marked


def _assert_shows_the_tee_study(page: str, form: Any) -> None:
    """Check a page and its pipe form hold the study the end-to-end test built."""
    assert _element(page, _field_id(form.name)).attributes["value"] == "Tee"
    assert "hidden" in _element(page, _widget_id(_part(form.name, "log"))).attributes
    assert _selected(_element(page, _field_id(form.material))) == ["Copper"]
    assert _selected(_element(page, _field_id(form.edge_type))) == ["Fillet"]
    assert "hidden" not in _element(page, _widget_id(form.fillet.renderer)).attributes
    assert _element(page, _field_id(form.main_pipe.radius)).attributes["value"] == "60"
    assert "hidden" in _element(page, _widget_id(form.log_view.renderer)).attributes
    assert form.name.text == "Tee"
    assert form.main_pipe.radius.value == 60.0


def test_a_toolbar_shows_its_actions_as_header_buttons(
    toolbar_views: list[ToolBarMainView], toolbar_client: TestClient
) -> None:
    page = toolbar_client.get("/results").text  # the page Run changes
    (main_view,) = toolbar_views
    toolbar_view = main_view.toolbar
    toolbar_id = _widget_id(toolbar_view.renderer)
    toolbar = _element(page, toolbar_id)
    assert (toolbar.attributes["role"], toolbar.attributes["aria-label"]) == ("toolbar", "Edit")
    assert [
        attributes.get("role") or tag
        for tag, attributes in toolbar.descendants
        if tag in {"label", "button", "div"}
    ] == ["label", "separator", "button", "button"]
    # Open uploads a study, as the File menu's does
    open_file = _element(page, _action_id(toolbar_view.open_file))
    file_input = next(a for tag, a in open_file.descendants if tag == "input")
    assert file_input["accept"] == ".toolbar"
    run = _element(page, _action_id(toolbar_view.run))
    assert (run.text, run.attributes["title"]) == ("Run", "Run (Alt+Shift+R)")

    response = toolbar_client.post(
        f"/widget/{_action_id(toolbar_view.run)}", data={"event": "triggered"}
    )
    total = _swapped(response.text, _widget_id(main_view.router.results.total.renderer))
    assert total.text == "Ran"
    wrap_id = _action_id(toolbar_view.wrap)
    response = toolbar_client.post(f"/widget/{wrap_id}", data={"event": "triggered"})
    wrap = _swapped(response.text, wrap_id)
    assert wrap.attributes["aria-pressed"] == "true"
    assert "btn-active" in (wrap.attributes["class"] or "").split()

    with collect_dirty() as dirty:
        toolbar_view.is_enabled = False
        swapped = _swapped(render_dirty(dirty), toolbar_id)
    assert all(
        "disabled" in attributes for tag, attributes in swapped.descendants if tag == "button"
    )
    refused = toolbar_client.post(
        f"/widget/{_action_id(toolbar_view.run)}", data={"event": "triggered"}
    )
    assert refused.status_code == 400


def test_the_language_menu_swaps_in_the_translated_widgets(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    menu = pipe_main_view.language_menu
    main_pipe_id = _widget_id(pipe_main_view.pages.inputs.pipe_form.main_pipe.renderer)

    response = pipe_client.post(
        f"/widget/{_action_id(menu.action('fr'))}", data={"event": "triggered"}
    )

    assert "hx-refresh" not in response.headers
    assert "Conduite principale" in _swapped(response.text, main_pipe_id).text
    assert pipe_main_view.language == "fr"
    # the page's script sets `<html lang>` and `<title>` from it
    marker = _swapped(response.text, "cui-page").attributes
    assert (marker["data-language"], marker["data-title"]) == ("fr", "Formulaire de conduite")
    assert "Formulaire de conduite" in _swapped(response.text, "cui-brand").text
    assert menu.action("fr").is_checked is True


@define_view
class _SeparatedMenu(Menu):
    """A menu whose separators separate nothing at its ends, nor each other."""

    first_separator: SeparatorAction = Factory(SeparatorAction)
    first: ActionView = Factory(lambda: ActionView(text="First"))
    separator: SeparatorAction = Factory(SeparatorAction)
    double: SeparatorAction = Factory(SeparatorAction)
    second: ActionView = Factory(lambda: ActionView(text="Second", is_enabled=False))
    last_separator: SeparatorAction = Factory(SeparatorAction)


@define_view
class _SeparatedMainView(MainView):
    app_title = "Separated"
    extension = ".separated"

    menu: _SeparatedMenu = Factory(_SeparatedMenu)


def test_a_menu_shows_only_the_separators_between_items_and_its_disabled_ones_so() -> None:
    view = _SeparatedMainView()
    view.render(RendererType.WEB)
    assert isinstance(view.renderer, WebMainRenderer)

    page = view.renderer.page_html()
    with collect_dirty() as dirty:
        view.menu.is_visible = True  # the web's menus are always there, in the header

    menu = _element(page, _widget_id(view.menu.renderer))
    separators = [
        tag for tag, attributes in menu.descendants if attributes.get("role") == "separator"
    ]
    assert len(separators) == 1
    second = _element(page, _widget_id(view.menu.second.renderer))
    assert "menu-disabled" in (second.attributes.get("class") or "")
    assert any(
        tag == "button" and "disabled" in attributes for tag, attributes in second.descendants
    )
    assert dirty == {}
