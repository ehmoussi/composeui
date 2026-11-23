"""Tests of the web application: a main view and a model per session, and its options."""

from __future__ import annotations

import json
import sys
import threading
from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from composeui.core.application import ModelApplication, WebSettings
from composeui.core.sqlitemodel import DatabaseModel, SqliteDatabase, SqliteTable, per_session
from composeui.core.study import save_study
from composeui.core.view import (
    MainView,
    define_view,
)
from composeui.webcore.changes import collect_dirty
from composeui.webcore.webapplication import WebApplication, WebModelApplication
from examples.pipecatalogue import (
    Material,
    Pipe,
    PipeCatalogueMainView,
    PipeCatalogueModel,
)
from examples.webhello import HelloMainView, NameRowView
from tests.tables import (
    SortedRoomsMainView,
)
from tests.translated import Size, TranslatedMainView

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from composeui.core.jobs import Job

from tests.webcore.support import (
    _Browser,
    _element,
    _field_id,
    _HelloApp,
    _part,
    _selected,
    _swapped,
    _type_name,
    _widget_id,
)


def test_each_browser_gets_its_own_main_view(app: _HelloApp) -> None:
    web = app.create_starlette_app()
    with _Browser(web) as alice, _Browser(web) as bob:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = app.session_views

        _type_name(alice, alice_view, "Alice")

        assert alice_view.form.name.text == "Alice"
        assert bob_view.form.name.text == ""
        assert 'value="Alice"' in alice.get("/").text
        assert 'value="Alice"' not in bob.get("/").text


def test_app_connect_refuses_a_view_outside_the_main_view(app: _HelloApp) -> None:
    name = NameRowView()  # e.g. built by the program, never put in the main view

    with pytest.raises(ValueError, match="isn't part of the app's main view"):
        app.connect(view=name, signals=[name.text_edited])


def test_app_connect_reacts_in_each_browser_on_its_own_views(app: _HelloApp) -> None:
    name = app.main_view.form.name

    @app.connect(view=name, signals=[name.text_edited])
    def echo(_text: str, *, view: NameRowView, main_view: HelloMainView) -> None:
        # connected after the view's own summary update, so it has the last word
        main_view.summary.text = f"Echo: {view.text}"

    web = app.create_starlette_app()
    with _Browser(web) as alice, _Browser(web) as bob:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = app.session_views

        def type_name(client: TestClient, view: HelloMainView, text: str) -> str:
            """Type `text` as the name; return the summary as swapped into the page."""
            field_id = _field_id(view.form.name)
            response = client.post(
                f"/_composeui/widget/{field_id}", data={"value": text, "event": "input"}
            )
            assert response.status_code == 200
            return _swapped(response.text, _widget_id(view.summary.renderer)).text

        assert type_name(alice, alice_view, "Alice") == "Echo: Alice"
        assert bob_view.summary.text != "Echo: Alice"
        assert type_name(bob, bob_view, "Bob") == "Echo: Bob"
        assert alice_view.summary.text == "Echo: Alice"
    assert app.main_view.summary.text != "Echo: Alice"  # the template is never wired


class _Signatures(SqliteTable):
    create = "CREATE TABLE signature(id INTEGER PRIMARY KEY, name TEXT NOT NULL);"

    def sign(self, name: str) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO signature(name) VALUES (?)", (name,))

    def names(self) -> list[str]:
        with self.connection() as db:
            return [row["name"] for row in db.execute("SELECT name FROM signature ORDER BY id")]


class _GuestbookDatabase(SqliteDatabase):
    def __init__(self) -> None:
        super().__init__()
        self.signatures = self.add_table(_Signatures)


class _SignedGuestbook(DatabaseModel):
    study = per_session(_GuestbookDatabase)


def test_a_saved_study_brings_its_database_to_another_browser() -> None:
    class GuestbookApp(WebModelApplication[HelloMainView, _SignedGuestbook]):
        @override
        def setup_session(self, main_view: HelloMainView) -> None:
            main_view.status_bar.timeout = 0
            views.append(main_view)

    def show_signatures(main_view: HelloMainView, model: _SignedGuestbook) -> None:
        # whatever changes the signatures, an upload included, the summary follows
        def show() -> None:
            main_view.summary.text = ", ".join(model.study.signatures.names())

        model.study.signatures.changed.connect(show)

    views: list[HelloMainView] = []
    # nothing but its session keeps a model
    app = GuestbookApp(
        build_main_view=HelloMainView, build_model=_SignedGuestbook, setup_model=show_signatures
    )
    name = app.main_view.form.name

    @app.connect(view=name, signals=[name.editing_finished])
    def sign(*, view: NameRowView, model: _SignedGuestbook) -> None:
        model.study.signatures.sign(view.text)

    def sign_as(client: TestClient, view: HelloMainView, text: str) -> None:
        field_id = _field_id(view.form.name)
        response = client.post(
            f"/_composeui/widget/{field_id}", data={"value": text, "event": "change"}
        )
        assert response.status_code == 200

    web = app.create_starlette_app()
    with _Browser(web) as alice, _Browser(web) as bob:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = views
        sign_as(alice, alice_view, "Alice")
        sign_as(alice, alice_view, "Ada")
        saved = alice.get("/_composeui/state")
        assert saved.headers["content-type"] == "application/zip"

        response = bob.post("/_composeui/state", files={"file": ("study.hello", saved.content)})

        assert response.headers["hx-refresh"] == "true"
        assert bob_view.form.name.text == "Ada"
        assert bob_view.summary.text == "Alice, Ada"
        sign_as(bob, bob_view, "Bob")
        assert bob_view.summary.text == "Alice, Ada, Bob"
        # the views' state alone isn't a study of this app: it would lose the signatures
        views_only = json.dumps(HelloMainView().state_data()).encode()
        bob.post("/_composeui/state", files={"file": ("study.hello", views_only)})
        # Bob's signature is unsaved: opened once he agrees to discard it
        discard_id = _widget_id(bob_view.discard_changes.renderer)
        response = bob.post(f"/_composeui/widget/{discard_id}", data={"event": "accept"})
        assert "isn&#39;t a valid .hello file" in response.text
        sign_as(bob, bob_view, "Eve")
        assert bob_view.summary.text == "Alice, Ada, Bob, Eve"


def test_a_state_file_opens_in_every_new_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study = HelloMainView()
    study.form.name.text = "Bob"
    state_file = tmp_path / "study.hello"
    study.save_state(state_file)
    served: list[Starlette] = []
    monkeypatch.setattr("sys.argv", ["webhello", "-f", str(state_file)])
    # the server itself is out of scope: keep the app it would serve
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda app, **_: served.append(app),
    )
    app = _HelloApp()

    app.run()

    with _Browser(served[0]) as alice, _Browser(served[0]) as bob:
        pages = [alice.get("/").text, bob.get("/").text]
    assert [view.form.name.text for view in app.session_views] == ["Bob", "Bob"]
    assert all('value="Bob"' in page for page in pages)


@pytest.mark.parametrize("with_study", [False, True])
def test_each_new_session_emits_loaded_once_with_or_without_a_study(
    with_study: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["webhello"]
    if with_study:
        study = HelloMainView()
        study.form.name.text = "Bob"
        state_file = tmp_path / "study.hello"
        study.save_state(state_file)
        argv += ["-f", str(state_file)]
    monkeypatch.setattr("sys.argv", argv)
    served: list[Starlette] = []
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda app, **_: served.append(app),
    )
    names: list[str] = []

    class LoadedApp(_HelloApp):
        @override
        def setup_session(self, main_view: HelloMainView) -> None:
            super().setup_session(main_view)
            main_view.loaded.connect(lambda: names.append(main_view.form.name.text))

    app = LoadedApp()
    app.run()

    with _Browser(served[0]) as alice, _Browser(served[0]) as bob:
        alice.get("/")
        bob.get("/")
    assert names == (["Bob", "Bob"] if with_study else ["", ""])  # once per session


def test_a_study_with_the_model_s_data_opens_in_every_new_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # an archive of the views' state and the database, not the views' JSON alone
    study = ModelApplication(
        build_main_view=PipeCatalogueMainView,
        build_model=PipeCatalogueModel,
        setup_model=PipeCatalogueMainView.connect_model,
    )
    study.model.study.pipes.add(Pipe("Main line", Material.STEEL, 50.0, 5.0, 6.0))
    study_file = tmp_path / "plant.pipes"
    save_study(study.main_view, study.model, study_file)
    study.model.close()
    served: list[Starlette] = []
    monkeypatch.setattr("sys.argv", ["pipecatalogue", "-f", str(study_file)])
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda app, **_: served.append(app),
    )
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

    app.run()

    with _Browser(served[0]) as alice, _Browser(served[0]) as bob:
        pages = [alice.get("/").text, bob.get("/").text]
    assert [[pipe.name for pipe in view.catalogue.browser.pipes.items] for view in views] == [
        ["Main line"],
        ["Main line"],
    ]
    assert all("Main line" in page for page in pages)


@define_view
class _GreetedMainView(HelloMainView):
    """The hello app, greeting a name of its own command-line option."""

    @override
    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--greet", metavar="NAME")

    @override
    def apply_arguments(self, args: argparse.Namespace) -> None:
        if args.greet is not None:
            self.form.name.text = args.greet


def test_an_app_s_own_options_apply_to_every_new_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served: list[Starlette] = []
    monkeypatch.setattr("sys.argv", ["webhello", "--greet", "Ada", "--port", "8001"])
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda app, **_: served.append(app),
    )
    views: list[_GreetedMainView] = []

    class GreetedApp(WebApplication[_GreetedMainView]):
        @override
        def setup_session(self, main_view: _GreetedMainView) -> None:
            views.append(main_view)

    GreetedApp(build_main_view=_GreetedMainView).run()

    with _Browser(served[0]) as alice, _Browser(served[0]) as bob:
        pages = [alice.get("/").text, bob.get("/").text]
    assert [view.form.name.text for view in views] == ["Ada", "Ada"]
    assert all('value="Ada"' in page for page in pages)


def test_a_web_server_that_stops_stops_the_programs_that_jobs_run(app: _HelloApp) -> None:
    # uvicorn ends on SIGTERM by sending it again once stopped: Python's exit can't stop them
    main_view = MainView()
    started = threading.Event()
    exit_codes: list[int] = []

    def work(job: Job[int]) -> int:
        sleeper = "print('ready', flush=True); import time; time.sleep(60)"
        return job.run_process([sys.executable, "-c", sleeper], on_output=lambda _: started.set())

    main_view.jobs.start(work).finished.connect(exit_codes.append)
    try:
        with _Browser(app.create_starlette_app()):
            assert started.wait(20)
        # the program stopped, its job ends on its own: it would sleep 60 s
        main_view.jobs.wait(timeout=20)
    finally:
        main_view.jobs.cancel()
        main_view.jobs.wait(timeout=20)

    (exit_code,) = exit_codes
    assert exit_code != 0


class _ShapesApp(WebApplication[TranslatedMainView]):
    def __init__(self) -> None:
        super().__init__(build_main_view=TranslatedMainView)
        self.session_views: list[TranslatedMainView] = []

    @override
    def setup_session(self, main_view: TranslatedMainView) -> None:
        self.session_views.append(main_view)


def test_every_session_shows_the_language_asked_on_the_command_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served: list[Starlette] = []
    monkeypatch.setattr("sys.argv", ["shapes", "--language", "fr"])
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run",
        lambda app, **_: served.append(app),
    )
    app = _ShapesApp()

    app.run()

    with _Browser(served[0]) as client:
        page = client.get("/").text
    view = app.session_views[0]
    assert '<html lang="fr">' in page
    size = _element(page, _field_id(view.shape.size))
    assert [attributes["value"] for tag, attributes in size.descendants if tag == "option"] == [
        "SMALL",
        "LARGE",
    ]
    assert size.text == "PetiteGrande"
    assert _selected(size) == ["LARGE"]
    assert _element(page, _widget_id(_part(view.shape.size, "label"))).text == (
        "Taille de la forme"
    )

    # back to the text as written, e.g. from a language menu
    with collect_dirty() as dirty:
        view.set_language("en")

    combobox = _part(view.shape.size, "field")
    assert combobox.widget_id in dirty
    assert "Large</option>" in combobox.to_html()
    assert view.shape.size.value is Size.LARGE


@pytest.mark.parametrize(
    ("app_setting", "operator_setting", "is_taken"),
    [(True, "on", True), (False, "on", False), (True, "off", False)],
)
def test_a_web_app_refuses_regular_expressions_when_it_or_its_operator_says_so(
    monkeypatch: pytest.MonkeyPatch, operator_setting: str, *, app_setting: bool, is_taken: bool
) -> None:
    monkeypatch.setenv("COMPOSEUI_FILTER_PATTERNS", operator_setting)

    rooms = WebApplication(
        build_main_view=SortedRoomsMainView, settings=WebSettings(filter_patterns=app_setting)
    ).main_view.rooms
    assert rooms.filter_takes_pattern(0) is is_taken
    assert (rooms.filter_error(0, "/^k/") is None) is is_taken


def test_a_web_app_refuses_a_subclass_that_sets_a_setting_as_a_class_variable() -> None:
    """A setting that moved to `WebSettings` stops the app, rather than being ignored."""
    with pytest.raises(
        TypeError, match=r"PublicApp sets filter_patterns, which moved to WebSettings"
    ):

        class PublicApp(WebApplication[SortedRoomsMainView]):
            filter_patterns = False
