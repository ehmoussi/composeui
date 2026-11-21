"""Tests of the web server's reload: the app built again in a new process."""

from __future__ import annotations

import logging
import os
import re
import secrets
import sys
import types
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from attrs import Factory
from uvicorn.importer import import_from_string

from composeui.core.view import (
    LabelRowIntInputView,
    MainView,
    define_view,
)
from composeui.webcore import session as session_module
from composeui.webcore.session import Hibernation, SessionStore
from composeui.webcore.webapplication import WebApplication
from examples import pipeform
from examples.pipeform import PipeMainView
from examples.webhello import HelloMainView

if TYPE_CHECKING:
    from starlette.applications import Starlette

    from composeui.core.model import Model


from tests.webcore.support import _Browser, _Clock, _HelloApp, _type_name


def test_a_reload_server_s_next_process_removes_a_session_cut_short_by_a_crash(
    tmp_path: Path,
) -> None:
    cut = tmp_path / f"{'a' * 43}.partial"
    cut.mkdir()
    (cut / "session.json").write_text("{")

    SessionStore(lambda: (HelloMainView(), None), ttl=60.0, max_sessions=1, saved=tmp_path)

    assert not cut.exists()


@define_view
class _CountMainView(MainView):
    count: LabelRowIntInputView = Factory(lambda: LabelRowIntInputView(value=1))


@define_view
class _CountEditedMainView(MainView):
    """`_CountMainView` after an edit of the initial count in its code."""

    count: LabelRowIntInputView = Factory(lambda: LabelRowIntInputView(value=2))


def test_a_reload_server_s_idle_session_takes_the_values_edited_in_the_code(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    built: list[MainView] = []

    def build() -> tuple[MainView, Model | None]:
        # the code of the server's next process, edited
        built.append(_CountEditedMainView() if len(built) > 0 else _CountMainView())
        return built[-1], None

    with mock.patch.object(session_module, "time", clock):
        store = SessionStore(
            build, ttl=60.0, max_sessions=1, saved=tmp_path, hibernation=Hibernation(5.0, 10)
        )
        created = store.get_or_create(None)
        assert created is not None
        session_id, _session = created
        clock.now += 6.0
        store.hibernate_idle()
        next_process = SessionStore(
            build, ttl=60.0, max_sessions=1, saved=tmp_path, hibernation=Hibernation(5.0, 10)
        )
        woken = next_process.get(session_id)

    assert woken is not None
    assert isinstance(woken.main_view, _CountEditedMainView)
    assert woken.main_view.count.value == 2


@pytest.mark.parametrize(("watchfiles", "polling"), [(True, "false"), (False, None)])
def test_reload_serves_the_app_the_program_builds_again_in_a_new_process(
    watchfiles: bool,
    polling: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if watchfiles:
        pytest.importorskip("watchfiles")
    else:
        monkeypatch.setitem(sys.modules, "watchfiles", None)  # not installed
    study = PipeMainView()
    study.pages.inputs.pipe_form.name.text = "Main line"
    state_file = tmp_path / "study.pipe"
    study.save_state(state_file)
    served: list[tuple[str, dict[str, Any]]] = []
    # `python -m examples.pipeform --backend web --reload -f study.pipe`, whose app is
    # built inline by `main()`, which also takes `--backend` out of the command line
    monkeypatch.setitem(sys.modules, "__main__", types.ModuleType("__main__"))
    monkeypatch.setattr(sys.modules["__main__"], "__spec__", find_spec("examples.pipeform"))
    monkeypatch.setattr(
        "sys.argv", ["pipeform", "--backend", "web", "--reload", "-f", str(state_file)]
    )
    polled: list[str | None] = []
    pages: list[str] = []
    saved: list[list[str]] = []

    def serve(app: str, **kwargs: Any) -> None:
        served.append((app, kwargs))
        polled.append(os.environ.get("WATCHFILES_FORCE_POLLING"))
        # what uvicorn's reloaded process does with it, without spawning one
        with _Browser(import_from_string(app)()) as client:
            pages.append(client.get("/").text)
        # stopped, as for a change: its session saved, for the next process
        saved_sessions = Path(os.environ["COMPOSEUI_WEB_SAVED_SESSIONS"])
        saved.append([path.name for path in saved_sessions.iterdir()])

    monkeypatch.setattr("composeui.webcore.webapplication.uvicorn.run", serve)
    # restore the variables `run` sets for the reloaded process
    for variable in (
        "COMPOSEUI_WEB_ENTRY",
        "COMPOSEUI_WEB_SAVED_SESSIONS",
        "COMPOSEUI_WEB_COOKIE_SIGNING",
    ):
        monkeypatch.setenv(variable, "")
    monkeypatch.setenv("WATCHFILES_FORCE_POLLING", "")
    monkeypatch.delenv("WATCHFILES_FORCE_POLLING")  # unset, as by default

    pipeform.main()

    ((_, options),) = served
    assert options["reload"] is True
    assert options["factory"] is True
    # the system reports the changes of the files here, outside a Windows drive on WSL:
    # watchfiles, if installed, waits for them
    assert polled == [polling]
    (page,) = pages
    assert "<title>Pipe Form</title>" in page
    assert 'value="Main line"' in page
    assert 'id="cui-reload"' in page  # it reloads once the server restarts
    assert [len(names) for names in saved] == [1]


#: a program serving the hello app, as a script: `python hello.py --reload`
_HELLO_SCRIPT = """
from composeui.webcore.webapplication import WebApplication
from examples.webhello import HelloMainView

WebApplication(build_main_view=HelloMainView).run()
"""


def _restore_reload_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore, after the test, the variables `run` sets for the reloaded process."""
    for variable in (
        "COMPOSEUI_WEB_ENTRY",
        "COMPOSEUI_WEB_SAVED_SESSIONS",
        "COMPOSEUI_WEB_COOKIE_SIGNING",
        "WATCHFILES_FORCE_POLLING",
    ):
        monkeypatch.setenv(variable, "")


def test_reload_serves_the_app_a_script_builds_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "hello.py"
    script.write_text(_HELLO_SCRIPT)
    program = types.ModuleType("__main__")
    program.__file__ = str(script)  # and no `__spec__`, as for a script
    monkeypatch.setitem(sys.modules, "__main__", program)
    monkeypatch.setattr("sys.argv", ["hello", "--reload"])
    _restore_reload_variables(monkeypatch)
    pages: list[str] = []

    def serve(app: str, **_: Any) -> None:
        # what uvicorn's reloaded process does with it, without spawning one
        with _Browser(import_from_string(app)()) as client:
            pages.append(client.get("/").text)

    monkeypatch.setattr("composeui.webcore.webapplication.uvicorn.run", serve)

    WebApplication(build_main_view=HelloMainView).run()

    (page,) = pages
    assert 'id="cui-reload"' in page


def test_a_program_that_a_reloaded_app_starts_doesn_t_get_the_cookie_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the program could show its environment to a user, e.g. in a console
    seen = tmp_path / "seen.txt"
    script = tmp_path / "hello.py"
    script.write_text(
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-c', 'import os, sys;"
        ' open(sys.argv[1], "w").write(os.environ.get("COMPOSEUI_WEB_COOKIE_SIGNING", ""))\','
        f" {str(seen)!r}], check=True)\n" + _HELLO_SCRIPT
    )
    program = types.ModuleType("__main__")
    program.__file__ = str(script)
    monkeypatch.setitem(sys.modules, "__main__", program)
    monkeypatch.setattr("sys.argv", ["hello", "--reload"])
    _restore_reload_variables(monkeypatch)
    keys: list[str] = []

    def serve(app: str, **_: Any) -> None:
        keys.append(os.environ["COMPOSEUI_WEB_COOKIE_SIGNING"])
        # what uvicorn's reloaded process does with it, without spawning one
        with _Browser(import_from_string(app)()) as client:
            assert client.get("/").status_code == 200

    monkeypatch.setattr("composeui.webcore.webapplication.uvicorn.run", serve)

    WebApplication(build_main_view=HelloMainView).run()

    (key,) = keys
    assert key != ""  # the reloaded process had it
    assert seen.read_text() == ""


def test_reload_refuses_a_program_it_can_t_run_again(monkeypatch: pytest.MonkeyPatch) -> None:
    # e.g. `python -c`: neither a module nor a script
    monkeypatch.setitem(sys.modules, "__main__", types.ModuleType("__main__"))
    monkeypatch.setattr("sys.argv", ["hello", "--reload"])
    _restore_reload_variables(monkeypatch)
    served: list[str] = []
    monkeypatch.setattr(
        "composeui.webcore.webapplication.uvicorn.run", lambda app, **_: served.append(app)
    )

    with pytest.raises(ValueError, match="start it as a script or with -m"):
        WebApplication(build_main_view=HelloMainView).run()
    assert served == []


@pytest.mark.parametrize(
    ("entry", "error"),
    [
        # renamed while the server restarts
        ("module:examples.no_such_example", "can't find examples.no_such_example"),
        # e.g. its `run` call moved under a condition it no longer meets
        ("path:{script}", "didn't run a WebApplication"),
    ],
)
def test_a_reloaded_process_fails_on_a_program_without_an_app(
    entry: str, error: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "hello.py"
    script.write_text("from examples.webhello import HelloMainView\n")
    monkeypatch.setitem(sys.modules, "__main__", sys.modules["__main__"])
    _restore_reload_variables(monkeypatch)
    monkeypatch.setenv("COMPOSEUI_WEB_ENTRY", entry.format(script=script))
    factory = import_from_string("composeui.webcore.webapplication:create_reloaded_starlette_app")

    with pytest.raises(RuntimeError, match=error):
        factory()


def _reload_instance(page: str) -> str:
    """Get the server process a page names in its reload poller."""
    found = re.search(r'id="cui-reload" hx-get="/reload\?instance=([^"]+)"', page)
    assert found is not None
    return found[1]


def test_a_reload_server_s_next_process_keeps_the_sessions_and_reloads_their_pages(
    app: _HelloApp, tmp_path: Path
) -> None:
    key = secrets.token_urlsafe(32)

    def serve() -> Starlette:  # a process of a `--reload` server
        return app.create_starlette_app(saved_sessions=tmp_path, secret_key=key)

    with _Browser(serve()) as before:
        page = before.get("/").text
        _type_name(before, app.session_views[0], "Bob")
        instance = _reload_instance(page)
        unchanged = before.get(f"/reload?instance={instance}")
        cookies = before.cookies
    # leaving the client stopped the server, which saved the session
    (saved,) = tmp_path.iterdir()
    with _Browser(serve()) as after:
        after.cookies = cookies
        restarted = after.get(f"/reload?instance={instance}")
        page = after.get("/").text
        opened = not saved.exists()
        polled = after.get(f"/reload?instance={_reload_instance(page)}")

    assert unchanged.status_code == 204
    assert restarted.headers["hx-refresh"] == "true"  # the page reloads, with the new code
    assert 'value="Bob"' in page
    assert polled.status_code == 204
    assert len(app.session_views) == 2  # built again, and opened
    assert opened
    assert saved.exists()  # saved again, for the next process


def test_a_reload_server_logs_its_pages_asks_only_once_it_restarted(
    app: _HelloApp,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = logging.getLogger("uvicorn.access")
    monkeypatch.setattr(access, "filters", [])  # none left for the other tests
    app.create_starlette_app(saved_sessions=tmp_path)  # a process of a `--reload` server

    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        # as uvicorn logs each request: client, method, path, HTTP version, status
        for path, status in [
            ("/reload?instance=any", 204),  # not restarted
            ("/reload?instance=any", 200),  # restarted: the page reloads
            ("/widget/1", 204),
        ]:
            access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", "GET", path, "1.1", status)
        access.info("not a request")  # e.g. a handler of the program's own

    assert [record.getMessage() for record in caplog.records] == [
        '127.0.0.1:50000 - "GET /reload?instance=any HTTP/1.1" 200',
        '127.0.0.1:50000 - "GET /widget/1 HTTP/1.1" 204',
        "not a request",
    ]


def test_another_server_s_pages_ask_nothing_a_reload_server_s_reloading_once(
    app: _HelloApp,
) -> None:
    with _Browser(app.create_starlette_app()) as browser:
        page = browser.get("/").text
        # a tab a `--reload` server served, still open once another server took its port
        poll = browser.get("/reload?instance=any")

    assert 'id="cui-reload"' not in page
    assert poll.headers["hx-refresh"] == "true"  # into a page that asks nothing
