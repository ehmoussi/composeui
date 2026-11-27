"""Tests of a session folder: the sessions that outlive their server (`session_folder`)."""

from __future__ import annotations

import errno
import itertools
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import attrs
import pytest
from attrs import Factory
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from composeui.core.application import WebSettings
from composeui.core.model import Model
from composeui.core.view import (
    OMIT,
    CheckListView,
    ConsoleView,
    DialogView,
    LabelRowFilePathInputView,
    LabelRowFileUploadView,
    LabelRowIntInputView,
    MainView,
    UploadedFile,
    define_view,
)
from composeui.core.webstyle import WebStyle
from composeui.webcore import session as session_module
from composeui.webcore import webapplication as webapplication_module
from composeui.webcore.session import Hibernation, SessionFolder, SessionStore, WebSession
from composeui.webcore.sessionfolder import FolderInUseError
from composeui.webcore.uploads import ReceivedFile
from examples.webhello import HelloMainView
from tests.datafiles import DataFileMainView
from tests.tables import DataFilesTableMainView
from tests.webcore.support import (
    _Browser,
    _Clock,
    _HelloApp,
    _part,
    _pick_cell_file,
    _pick_file,
    _type_name,
    _widget_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.applications import Starlette

#: the repository, where a program started by a test finds `tests` and the package
_ROOT = Path(__file__).parents[2]


def _kept(folder: Path, style: WebStyle | None = None) -> _HelloApp:
    app = _HelloApp(WebSettings(session_folder=folder))
    if style is not None:
        app.style = style
    return app


def _saved_ids(folder: Path) -> list[str]:
    """Get the ids of the sessions saved in `folder`: each directory named as an id."""
    return sorted(path.name for path in folder.iterdir() if len(path.name) == 43)


def _cookie_browser(starlette_app: Starlette, cookie: str) -> _Browser:
    """Make a browser that comes back with the session cookie of a previous server."""
    browser = _Browser(starlette_app)
    browser.cookies.set("session", cookie)
    return browser


def _store(
    folder: Path,
    build: Callable[[], tuple[MainView, Model | None]] = lambda: (HelloMainView(), None),
    *,
    max_saved: int = 10,
    ttl: float = 600.0,
    hibernation: Hibernation | None = None,
) -> SessionStore:
    return SessionStore(
        build,
        ttl=ttl,
        max_sessions=3,
        saved=SessionFolder(folder, max_saved),
        hibernation=hibernation,
    )


def _created(store: SessionStore) -> tuple[str, WebSession]:
    created = store.get_or_create(None)
    assert created is not None
    return created


def test_a_session_in_a_folder_outlives_its_server_under_the_same_cookie(
    tmp_path: Path,
) -> None:
    """The cookie's key is in the folder: the next server reads it, and opens the session."""
    folder = tmp_path / "sessions"
    first = _kept(folder)
    with _Browser(first.create_starlette_app()) as browser:
        browser.get("/")
        _type_name(browser, first.session_views[0], "Bob")
        cookie = browser.cookies["session"]
    (session_id,) = _saved_ids(folder)

    second = _kept(folder)
    with _cookie_browser(second.create_starlette_app(), cookie) as browser:
        page = browser.get("/").text

    assert 'value="Bob"' in page
    assert _saved_ids(folder) == [session_id]  # saved again as the second server stopped
    assert second.session_views[0].browser_id == first.session_views[0].browser_id


_CRASHED_WITH_AN_IDLE_SESSION = """
import sys
from pathlib import Path
from composeui.core.application import WebSettings
from tests.webcore.support import _Browser, _HelloApp, _type_name

settings = WebSettings(session_folder=Path(sys.argv[1]), session_idle=0.0)
app = _HelloApp(settings)
starlette_app = app.create_starlette_app()
# not entered: no lifespan, so no sweep but the test's, and nothing saved as it ends
browser = _Browser(starlette_app)
browser.get("/")
_type_name(browser, app.session_views[0], "Bob")
starlette_app.state.sessions.hibernate_idle()
print(browser.cookies["session"])
# ends as a crash does: the server's stop never ran, nor saved the sessions in memory
"""


def _crash(program: str, folder: Path) -> str:
    """Run `program`, a server that ends without its stop, on `folder`; get what it printed."""
    crashed = subprocess.run(  # noqa: S603 (the test's own program, with this Python)
        [sys.executable, "-c", program, str(folder)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert crashed.returncode == 0, crashed.stderr
    return crashed.stdout.strip()


def test_an_idle_session_on_disk_outlives_a_crash_of_its_server(tmp_path: Path) -> None:
    """With `session_idle`, it waits in the folder; a server that never stopped frees it."""
    folder = tmp_path / "sessions"
    cookie = _crash(_CRASHED_WITH_AN_IDLE_SESSION, folder)

    app = _kept(folder)
    with _cookie_browser(app.create_starlette_app(), cookie) as browser:
        page = browser.get("/").text

    assert 'value="Bob"' in page


@define_view
class _AskingMainView(MainView):
    question: DialogView = Factory(DialogView)


def _hold_a_question(session: WebSession) -> None:
    """Show what a study doesn't keep: the session can't be saved."""
    assert isinstance(session.main_view, _AskingMainView)
    session.main_view.question.open()


def test_a_session_that_can_t_be_saved_as_its_server_stops_is_lost(tmp_path: Path) -> None:
    """A study doesn't keep a dialog's question: at a restart, the session would lose it."""
    folder = tmp_path / "sessions"
    store = _store(folder, lambda: (_AskingMainView(), None))
    session_id, session = _created(store)
    _hold_a_question(session)
    store.keep_all()

    assert _saved_ids(folder) == []
    assert _store(folder).get(session_id) is None


def test_a_session_idle_past_its_timeout_while_no_server_ran_is_dropped(tmp_path: Path) -> None:
    """Idle from its last request, as a clock time: not from its save, nor the next start."""
    clock = _Clock()
    folder = tmp_path / "sessions"
    with mock.patch.object(session_module, "time", clock):
        first = _store(folder, ttl=60.0)
        old, _old_session = _created(first)
        clock.now = 30.0
        recent, _recent_session = _created(first)
        first.keep_all()  # both saved at 30 s
        clock.now = 61.0
        second = _store(folder, ttl=60.0)
        old_session = second.get(old)
        recent_session = second.get(recent)
        second.keep_all()

    assert old_session is None
    assert recent_session is not None
    assert _saved_ids(folder) == [recent]


def test_a_session_whose_saved_time_is_unreadable_counts_from_its_save(tmp_path: Path) -> None:
    """Never from the next start: one idle past its timeout while no server ran ends."""
    folder = tmp_path / "sessions"
    app = _kept(folder)
    with _Browser(app.create_starlette_app()) as browser:
        browser.get("/")
        _type_name(browser, app.session_views[0], "Bob")
        cookie = browser.cookies["session"]
    (session_id,) = _saved_ids(folder)
    (folder / session_id / "last-seen").write_text("")  # e.g. damaged
    long_ago = time.time() - 4000.0  # past the hour of `session_ttl`
    os.utime(folder / session_id, (long_ago, long_ago))

    with _cookie_browser(_kept(folder).create_starlette_app(), cookie) as browser:
        page = browser.get("/").text

    assert 'value="Bob"' not in page


def test_one_server_at_a_time_keeps_its_sessions_in_a_folder(tmp_path: Path) -> None:
    folder = tmp_path / "sessions"
    first = _kept(folder).create_starlette_app()
    with pytest.raises(FolderInUseError, match="another server keeps its sessions"):
        _kept(folder).create_starlette_app()
    with _Browser(first):
        pass  # served, then stopped: its lock released
    with _Browser(_kept(folder).create_starlette_app()):
        pass


def test_a_server_started_again_takes_its_folder_again(tmp_path: Path) -> None:
    """And while it serves again, no other server takes it."""
    folder = tmp_path / "sessions"
    first = _kept(folder).create_starlette_app()
    with _Browser(first):
        pass
    with _Browser(first), pytest.raises(FolderInUseError):
        _kept(folder).create_starlette_app()


def test_a_server_that_fails_to_be_made_frees_its_folder(tmp_path: Path) -> None:
    """E.g. a stylesheet missing: the app fixed, the server made again takes the folder."""
    folder = tmp_path / "sessions"
    styles = tmp_path / "styles"
    styles.mkdir()
    style = WebStyle(folder=styles, stylesheets=("app.css",))
    # kept: its traceback holds the failed server, which would free the folder as it goes
    with pytest.raises(ValueError, match=r"app\.css") as failure:
        _kept(folder, style).create_starlette_app()
    (styles / "app.css").write_text("a { color: red; }")

    with _Browser(_kept(folder, style).create_starlette_app()):
        pass
    assert failure.traceback


def test_a_folder_whose_key_is_empty_is_refused_rather_than_signing_with_it(
    tmp_path: Path,
) -> None:
    """An empty key signs cookies that anyone can make."""
    folder = tmp_path / "sessions"
    folder.mkdir()
    (folder / "secret-key").write_text("\n")

    with pytest.raises(ValueError, match="holds no key"):
        _kept(folder).create_starlette_app()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no such file modes")
def test_only_the_server_s_user_reads_the_key_and_the_sessions(tmp_path: Path) -> None:
    folder = tmp_path / "sessions"
    with _Browser(_kept(folder).create_starlette_app()) as browser:
        browser.get("/")
    (session_id,) = _saved_ids(folder)

    assert (folder / "secret-key").stat().st_mode & 0o077 == 0
    assert (folder / session_id).stat().st_mode & 0o077 == 0


@pytest.mark.skipif(sys.platform == "win32", reason="a link needs a privilege on Windows")
def test_a_link_left_where_the_key_is_written_writes_no_other_file(tmp_path: Path) -> None:
    """Someone who can write in the folder can't make the server overwrite their target."""
    folder = tmp_path / "sessions"
    folder.mkdir()
    target = tmp_path / "target"
    target.write_text("kept")
    (folder / "secret-key.partial").symlink_to(target)

    with _Browser(_kept(folder).create_starlette_app()):
        pass

    assert target.read_text() == "kept"
    assert (folder / "secret-key").read_text() != ""


def test_a_cookie_signed_before_the_clock_stepped_back_still_opens_its_session(
    tmp_path: Path,
) -> None:
    """E.g. a time sync between two servers: the key proves the cookie, the folder its age."""
    folder = tmp_path / "sessions"
    app = _kept(folder)
    with _Browser(app.create_starlette_app()) as browser:
        browser.get("/")
        _type_name(browser, app.session_views[0], "Bob")
        cookie = browser.cookies["session"]
    stepped_back = types.SimpleNamespace(time=lambda: time.time() - 100.0)

    with (
        mock.patch.object(webapplication_module, "time", stepped_back),
        _cookie_browser(_kept(folder).create_starlette_app(), cookie) as browser,
    ):
        page = browser.get("/").text

    assert 'value="Bob"' in page


def test_a_cookie_older_than_its_max_age_is_refused_still(tmp_path: Path) -> None:
    """Taking a cookie signed later than the clock keeps the cookie's own age limit."""
    folder = tmp_path / "sessions"
    app = _kept(folder)
    with _Browser(app.create_starlette_app()) as browser:
        browser.get("/")
        _type_name(browser, app.session_views[0], "Bob")
        cookie = browser.cookies["session"]
    weeks_later = types.SimpleNamespace(time=lambda: time.time() + 15 * 24 * 3600.0)

    with (
        mock.patch.object(webapplication_module, "time", weeks_later),
        _cookie_browser(_kept(folder).create_starlette_app(), cookie) as browser,
    ):
        page = browser.get("/").text

    assert 'value="Bob"' not in page


def test_the_server_s_stop_saves_no_more_sessions_than_the_disk_takes(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    folder = tmp_path / "sessions"
    store = _store(folder, max_saved=1)
    _created(store)
    _created(store)
    with caplog.at_level(logging.WARNING, logger="COMPOSEUI"):
        store.keep_all()

    assert len(_saved_ids(folder)) == 1
    assert "No room on disk for a session" in caplog.text


@pytest.mark.parametrize("saves_by", ["hibernation", "stop"])
def test_a_session_that_can_t_be_saved_leaves_the_last_place_on_disk_to_the_next(
    saves_by: str, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """A place counts once a save is there: one disk place, the first session can't take it."""
    clock = _Clock()
    folder = tmp_path / "sessions"
    with mock.patch.object(session_module, "time", clock):
        store = _store(
            folder,
            lambda: (_AskingMainView(), None),
            max_saved=1,
            hibernation=Hibernation(5.0, 1),
        )
        _busy_id, busy = _created(store)
        saveable_id, _saveable = _created(store)
        _hold_a_question(busy)
        clock.now = 6.0
        with caplog.at_level(logging.WARNING, logger="COMPOSEUI"):
            if saves_by == "hibernation":
                store.hibernate_idle()
            # before the stop, which saves any session left in memory
            saved = _saved_ids(folder)
            store.keep_all()

    assert saved == ([saveable_id] if saves_by == "hibernation" else [])
    assert _saved_ids(folder) == [saveable_id]
    assert "No room on disk" not in caplog.text


def test_expired_sessions_leave_their_places_to_a_live_one_at_the_stop(
    tmp_path: Path,
) -> None:
    """Dropped first, on disk or in memory, though no request or sweep came since they expired."""
    clock = _Clock()
    folder = tmp_path / "sessions"
    with mock.patch.object(session_module, "time", clock):
        store = _store(folder, max_saved=1, ttl=60.0, hibernation=Hibernation(5.0, 1))
        _created(store)
        clock.now = 6.0
        store.hibernate_idle()  # the only place on disk
        _created(store)  # in memory, before the next one: it would take the place first
        clock.now = 50.0
        live_id, _live = _created(store)
        clock.now = 70.0  # the first two expired, at 66 s and 60 s
        store.keep_all()

    assert _saved_ids(folder) == [live_id]


@define_view
class _AskedMainView(HelloMainView):
    """A main view whose app's `can_hibernate` fails, e.g. on a bug."""

    @override
    def can_hibernate(self) -> bool:
        msg = "the app's check failed"
        raise RuntimeError(msg)


def test_an_app_s_check_failing_at_the_stop_leaves_the_next_sessions_kept(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """With no room on disk: the check runs only to say so, and fails for one session."""
    clock = _Clock()
    folder = tmp_path / "sessions"
    views = iter([HelloMainView(), _AskedMainView(), HelloMainView()])
    with mock.patch.object(session_module, "time", clock):
        store = _store(
            folder,
            lambda: (next(views), None),
            max_saved=1,
            hibernation=Hibernation(5.0, 1),
        )
        _created(store)
        clock.now = 6.0
        store.hibernate_idle()  # the only place on disk
        _created(store)
        _created(store)
        with caplog.at_level(logging.WARNING, logger="COMPOSEUI"):
            store.keep_all()

    assert "Can't tell whether a session can be saved" in caplog.text
    assert "No room on disk for a session" in caplog.text  # the next one's
    with _Browser(_kept(folder).create_starlette_app()):
        pass  # the folder is free


class _UnsaveableModel(Model):
    """A model whose data can't be saved, e.g. on a full disk."""

    data_name = "data.txt"

    @override
    def save_data(self, path: Path) -> None:
        raise OSError(errno.ENOSPC, "No space left on device", str(path))

    @override
    def open_data(self, path: Path) -> None:
        raise AssertionError  # never saved


def test_a_session_that_fails_to_save_as_the_server_stops_is_lost(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    folder = tmp_path / "sessions"
    store = _store(folder, lambda: (HelloMainView(), _UnsaveableModel()))
    _created(store)
    with caplog.at_level(logging.ERROR, logger="COMPOSEUI"):
        store.keep_all()

    assert _saved_ids(folder) == []
    assert "Can't save a session as the server stops" in caplog.text


class _CountedUnsaveableModel(_UnsaveableModel):
    """A model whose data can't be saved, which counts the tries."""

    def __init__(self) -> None:
        super().__init__()
        self.saves = 0

    @override
    def save_data(self, path: Path) -> None:
        self.saves += 1
        super().save_data(path)


def test_a_session_that_failed_to_save_while_idle_isn_t_tried_again_at_the_stop(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    folder = tmp_path / "sessions"
    model = _CountedUnsaveableModel()
    with mock.patch.object(session_module, "time", clock):
        store = _store(folder, lambda: (HelloMainView(), model), hibernation=Hibernation(5.0, 10))
        _created(store)
        clock.now = 6.0
        store.hibernate_idle()
        store.keep_all()

    assert model.saves == 1
    assert _saved_ids(folder) == []


class _UnclosableModel(Model):
    """A model that fails to close, e.g. a database that another program locked."""

    data_name = "data.txt"

    @override
    def save_data(self, path: Path) -> None:
        path.write_text("data")

    @override
    def open_data(self, path: Path) -> None:
        assert path.read_text() == "data"

    @override
    def close(self) -> None:
        raise OSError(errno.EBUSY, "Device or resource busy")


def test_a_model_that_fails_to_close_at_the_stop_leaves_the_other_sessions_kept(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    folder = tmp_path / "sessions"
    views = iter([_AskingMainView(), HelloMainView(), HelloMainView()])
    store = _store(folder, lambda: (next(views), _UnclosableModel()))
    lost_id, lost = _created(store)
    _hold_a_question(lost)  # it ends, its model failing to close
    _created(store)
    _created(store)
    with caplog.at_level(logging.ERROR, logger="COMPOSEUI"):
        store.keep_all()

    assert len(_saved_ids(folder)) == 2
    assert lost_id not in _saved_ids(folder)
    assert "Can't release a session as the server stops" in caplog.text
    _store(folder).keep_all()  # the folder is free


def _uploaded(store: SessionStore) -> tuple[str, Path]:
    """Upload a file to a new session's path field; get the session's id and the file's path."""
    session_id, session = _created(store)
    assert isinstance(session.main_view, DataFileMainView)
    measurements = session.main_view.form.measurements
    _pick_file(session, _part(measurements, "field").widget_id, "first.csv", b"first")
    assert measurements.path is not None
    return session_id, measurements.path


def _cell_uploaded(store: SessionStore) -> tuple[str, Path]:
    """Upload a file to a new session's path cell; get the session's id and the file's path."""
    session_id, session = _created(store)
    assert isinstance(session.main_view, DataFilesTableMainView)
    table = session.main_view.inputs
    _pick_cell_file(session, _widget_id(table.renderer), 0, "flows.csv", b"1,2")
    return session_id, Path(table.rows[0][1])


def _restored_path(session: WebSession | None) -> Path | None:
    """Get the path of the upload that a restored session's field or cell names."""
    assert session is not None
    if isinstance(session.main_view, DataFileMainView):
        return session.main_view.form.measurements.path
    assert isinstance(session.main_view, DataFilesTableMainView)
    return Path(session.main_view.inputs.rows[0][1])


@pytest.mark.parametrize(
    ("main_view_type", "upload"),
    [(DataFileMainView, _uploaded), (DataFilesTableMainView, _cell_uploaded)],
)
def test_an_upload_of_a_path_outlives_its_server_in_the_folder(
    main_view_type: type[MainView],
    upload: Callable[[SessionStore], tuple[str, Path]],
    tmp_path: Path,
) -> None:
    """Not in the system's temporary folder, which a new container or a reboot empties."""
    folder = tmp_path / "sessions"
    store = _store(folder, lambda: (main_view_type(), None))
    session_id, path = upload(store)
    store.keep_all()

    next_server = _store(folder, lambda: (main_view_type(), None))
    restored_path = _restored_path(next_server.get(session_id))
    next_server.drop(session_id)  # e.g. Exit

    assert path.is_relative_to(folder)
    assert restored_path == path
    assert not path.exists()


@define_view
class _RunMainView(DataFileMainView):
    """A run's page: its output, the files a run takes, and a search among its cases."""

    console: ConsoleView = Factory(lambda: ConsoleView(ansi_colors=True))
    inputs: LabelRowFileUploadView = Factory(
        lambda: LabelRowFileUploadView(label="Inputs", multiple=True)
    )
    cases: CheckListView[str] = Factory(
        lambda: CheckListView[str](values={"Wall": "wall", "Beam": "beam"}, has_search=True)
    )


def _give_inputs(session: WebSession, *names: str) -> tuple[Path, ...]:
    """Upload files to the run's inputs, as the route does; get where the session keeps them."""
    assert isinstance(session.main_view, _RunMainView)
    inputs = session.main_view.inputs
    with tempfile.TemporaryDirectory() as directory:
        received = []
        for index, name in enumerate(names):
            path = Path(directory, f"upload-{index}")
            path.write_bytes(name.encode())
            received.append(ReceivedFile(name, "", path))
        session.pick_files(_part(inputs, "field").widget_id, received)
    return tuple(file.path for file in inputs.files)


def test_a_run_s_output_inputs_and_search_outlive_its_server_in_the_folder(
    tmp_path: Path,
) -> None:
    """The session comes back as the user left it; the uploads it replaces next are removed."""
    folder = tmp_path / "sessions"
    store = _store(folder, lambda: (_RunMainView(), None))
    session_id, session = _created(store)
    assert isinstance(session.main_view, _RunMainView)
    session.main_view.console.append("meshing\n\x1b[31mstep 2 failed\n")
    inputs = _give_inputs(session, "mesh.med", "loads.csv")
    measurements = session.main_view.form.measurements
    _pick_file(session, _part(measurements, "field").widget_id, "first.csv", b"first")
    measured = measurements.path
    assert measured is not None
    session.main_view.cases.search = "be"
    store.keep_all()

    next_server = _store(folder, lambda: (_RunMainView(), None))
    restored = next_server.get(session_id)
    assert restored is not None
    main_view = restored.main_view
    assert isinstance(main_view, _RunMainView)
    shown = (
        main_view.console.text,
        main_view.console.line_styles,
        [file.path for file in main_view.inputs.files],
        main_view.form.measurements.path,
        main_view.cases.search,
    )
    page = restored.page_html()
    # the next ones replace them
    _give_inputs(restored, "mesh2.med")
    _pick_file(restored, _part(main_view.form.measurements, "field").widget_id, "b.csv", b"b")
    replaced_left = [path for path in (*inputs, measured) if path.exists()]
    next_server.drop(session_id)

    assert shown == (
        "meshing\nstep 2 failed\n",
        session.main_view.console.line_styles,
        list(inputs),
        measured,
        "be",
    )
    assert all(path.is_relative_to(folder) for path in inputs)
    assert "step 2 failed" in page
    assert 'value="be"' in page
    assert replaced_left == []


def _forge(saved: Path, *paths: Path) -> None:
    """Make the saved session name `paths` as its upload view's files, as a forged save would."""
    data = json.loads(saved.read_text())
    file = data["views"]["inputs.files"][0]
    data["views"]["inputs.files"] = [{**file, "path": str(path)} for path in paths]
    saved.write_text(json.dumps(data))


def _remove_upload(_saved: Path, inputs: tuple[Path, ...], _tmp_path: Path) -> None:
    inputs[1].unlink()  # e.g. a cleanup of the disk


def _point_elsewhere(saved: Path, _inputs: tuple[Path, ...], tmp_path: Path) -> None:
    # named as an upload view's upload is, out of the session's folder
    other = tmp_path / "cui-1-file_upload" / "kept" / "results.csv"
    other.parent.mkdir(parents=True)
    other.write_text("1,2")
    _forge(saved, other)


def _point_above(saved: Path, inputs: tuple[Path, ...], _tmp_path: Path) -> None:
    # held, the folder of every upload of the session would go at the field's next upload
    field = inputs[0].parent.parent
    (field.parent / "mesh.med").write_text("mesh")
    _forge(saved, field / ".." / "mesh.med")


def _point_through_a_link(saved: Path, inputs: tuple[Path, ...], tmp_path: Path) -> None:
    field = inputs[0].parent.parent
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "kept").mkdir(parents=True)
    (elsewhere / "kept" / "mesh.med").write_text("mesh")
    link = field.with_name("cui-1-file_upload")
    link.symlink_to(elsewhere, target_is_directory=True)
    _forge(saved, link / "kept" / "mesh.med")


@pytest.mark.parametrize(
    "change",
    [
        _remove_upload,
        _point_elsewhere,
        _point_above,
        pytest.param(
            _point_through_a_link,
            marks=pytest.mark.skipif(
                sys.platform == "win32", reason="a link needs a privilege on Windows"
            ),
        ),
    ],
)
def test_a_restored_upload_view_holds_only_files_that_its_session_kept(
    change: Callable[[Path, tuple[Path, ...], Path], None], tmp_path: Path
) -> None:
    """Never a file that the session doesn't own, which its next upload would remove."""
    folder = tmp_path / "sessions"
    store = _store(folder, lambda: (_RunMainView(), None))
    session_id, session = _created(store)
    inputs = _give_inputs(session, "mesh.med", "loads.csv")
    store.keep_all()
    change(folder / session_id / "session.json", inputs, tmp_path)

    next_server = _store(folder, lambda: (_RunMainView(), None))
    restored = next_server.get(session_id)
    assert restored is not None
    assert isinstance(restored.main_view, _RunMainView)
    files = restored.main_view.inputs.files
    next_server.drop(session_id)

    assert files == ()


def test_a_restored_upload_view_keeps_the_app_s_own_file(tmp_path: Path) -> None:
    """The app gave it, not the user: the session neither owns it nor drops it."""
    folder = tmp_path / "sessions"
    results = tmp_path / "results.csv"
    results.write_text("1,2")
    store = _store(folder, lambda: (_RunMainView(), None))
    session_id, session = _created(store)
    assert isinstance(session.main_view, _RunMainView)
    session.main_view.inputs.take_file(UploadedFile.of_path(results))
    store.keep_all()

    next_server = _store(folder, lambda: (_RunMainView(), None))
    restored = next_server.get(session_id)
    assert restored is not None
    assert isinstance(restored.main_view, _RunMainView)
    files = [file.path for file in restored.main_view.inputs.files]
    next_server.drop(session_id)

    assert files == [results]
    assert results.exists()


@define_view
class _CopiedPathMainView(DataFilesTableMainView):
    """Fields whose uploads a user can copy the path of, and a field to paste it in."""

    measurements: LabelRowFilePathInputView = Factory(
        lambda: LabelRowFilePathInputView(label="Measurements")
    )
    dataset: LabelRowFileUploadView = Factory(lambda: LabelRowFileUploadView(label="Dataset"))
    results: LabelRowFilePathInputView = Factory(lambda: LabelRowFilePathInputView(label="Results"))


def _upload_measurements(session: WebSession) -> Path:
    assert isinstance(session.main_view, _CopiedPathMainView)
    measurements = session.main_view.measurements
    _pick_file(session, _part(measurements, "field").widget_id, "first.csv", b"first")
    assert measurements.path is not None
    return measurements.path


def _upload_dataset(session: WebSession) -> Path:
    assert isinstance(session.main_view, _CopiedPathMainView)
    dataset = session.main_view.dataset
    _pick_file(session, _part(dataset, "field").widget_id, "data.csv", b"1,2")
    assert dataset.file is not None
    return dataset.file.path


def _upload_to_a_cell(session: WebSession) -> Path:
    assert isinstance(session.main_view, _CopiedPathMainView)
    table = session.main_view.inputs
    _pick_cell_file(session, _widget_id(table.renderer), 0, "flows.csv", b"1,2")
    return Path(table.rows[0][1])


@pytest.mark.parametrize("upload", [_upload_measurements, _upload_dataset, _upload_to_a_cell])
def test_a_path_copied_to_another_field_outlives_that_field_s_next_upload_after_a_restart(
    upload: Callable[[WebSession], Path], tmp_path: Path
) -> None:
    """The restored session doesn't take the upload the path names for the field's own."""
    folder = tmp_path / "sessions"
    store = _store(folder, lambda: (_CopiedPathMainView(), None))
    session_id, session = _created(store)
    copied = upload(session)
    assert isinstance(session.main_view, _CopiedPathMainView)
    results_id = _part(session.main_view.results, "field").widget_id
    session.handle_event(results_id, "input", {"value": str(copied)})
    assert session.main_view.results.path == copied
    store.keep_all()

    next_server = _store(folder, lambda: (_CopiedPathMainView(), None))
    restored = next_server.get(session_id)
    assert restored is not None
    assert isinstance(restored.main_view, _CopiedPathMainView)
    results = _part(restored.main_view.results, "field").widget_id
    _pick_file(restored, results, "results.csv", b"3,4")
    is_left = copied.exists()
    next_server.drop(session_id)

    assert is_left


def test_an_upload_in_a_relative_session_folder_has_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The field's path names the file wherever the app reads it, e.g. a job in another folder."""
    monkeypatch.chdir(tmp_path)
    store = _store(Path("sessions"), lambda: (DataFileMainView(), None))
    _session_id, path = _uploaded(store)
    store.keep_all()

    assert path.is_absolute()
    assert path.is_relative_to(tmp_path / "sessions")


def test_uploads_that_no_saved_session_names_are_removed_as_the_server_starts(
    tmp_path: Path,
) -> None:
    """E.g. those of a session in memory that a crash lost."""
    folder = tmp_path / "sessions"
    store = _store(folder, lambda: (DataFileMainView(), None))
    _session_id, path = _uploaded(store)
    store.keep_all()
    orphan = folder / "uploads" / "composeui-lost"
    orphan.mkdir()

    _store(folder).keep_all()

    assert path.read_bytes() == b"first"
    assert not orphan.exists()


def test_a_saved_session_naming_uploads_outside_its_folder_never_deletes_them(
    tmp_path: Path,
) -> None:
    """Even a directory of the system's temporary folder, where other servers keep theirs."""
    folder = tmp_path / "sessions"
    store = _store(folder, lambda: (DataFileMainView(), None))
    session_id, _path = _uploaded(store)
    store.keep_all()
    other = Path(tempfile.mkdtemp(prefix="composeui-"))
    try:
        (folder / session_id / "uploads").write_text(str(other))
        next_server = _store(folder, lambda: (DataFileMainView(), None))
        assert next_server.get(session_id) is not None
        next_server.drop(session_id)

        assert other.is_dir()
    finally:
        shutil.rmtree(other)


def test_the_next_server_waits_for_the_jobs_of_the_sessions_that_ended(tmp_path: Path) -> None:
    """A job may still read its session's uploads, which the next start would take for a crash's."""
    folder = tmp_path / "sessions"
    store = _store(folder, lambda: (DataFileMainView(), None))
    session_id, path = _uploaded(store)
    session = store.get(session_id)
    assert session is not None
    may_end = threading.Event()
    jobs = session.main_view.jobs
    jobs.start(lambda _job: may_end.wait(10))  # it can't be saved: it ends
    store.keep_all()
    try:
        with pytest.raises(FolderInUseError):
            _store(folder)
        readable = path.read_bytes()
    finally:
        may_end.set()
    for _ in range(200):  # until its thread is over
        if not jobs.has_workers:
            break
        time.sleep(0.05)
    _store(folder).keep_all()

    assert readable == b"first"
    assert not path.exists()


def test_a_folder_of_something_else_is_refused_and_left_as_it_is(tmp_path: Path) -> None:
    """E.g. an app's data folder, given by mistake: the server would remove its files."""
    folder = tmp_path / "data"
    (folder / "notes.partial").mkdir(parents=True)
    (folder / "uploads" / "composeui-report").mkdir(parents=True)

    with pytest.raises(ValueError, match="holds files of something else"):
        _kept(folder).create_starlette_app()
    assert (folder / "notes.partial").is_dir()
    assert (folder / "uploads" / "composeui-report").is_dir()


def test_a_session_folder_leaves_what_isn_t_a_session_s_alone(tmp_path: Path) -> None:
    """A file put there later, by a person or a program, is never removed or moved."""
    folder = tmp_path / "sessions"
    with _Browser(_kept(folder).create_starlette_app()):
        pass  # the folder is the sessions' from now on: it holds their key
    (folder / "notes.partial").mkdir()
    (folder / "uploads" / "report").mkdir()

    with _Browser(_kept(folder).create_starlette_app()):
        pass

    assert (folder / "notes.partial").is_dir()
    assert (folder / "uploads" / "report").is_dir()


_STARTS = itertools.count(1)


@define_view
class _NumberedMainView(MainView):
    """A main view whose field starts with another value at each build, as a date would."""

    number: LabelRowIntInputView = Factory(lambda: LabelRowIntInputView(value=next(_STARTS)))


def test_a_session_saved_in_a_folder_comes_back_with_a_value_its_field_starts_with(
    tmp_path: Path,
) -> None:
    """A field that starts with another value at each build isn't taken for an edit of the code."""
    folder = tmp_path / "sessions"
    first = _store(folder, lambda: (_NumberedMainView(), None))
    session_id, session = _created(first)
    assert isinstance(session.main_view, _NumberedMainView)
    session.main_view.number.value = 98765
    first.keep_all()
    second = _store(folder, lambda: (_NumberedMainView(), None))
    restored = second.get(session_id)
    second.keep_all()

    assert restored is not None
    assert isinstance(restored.main_view, _NumberedMainView)
    assert restored.main_view.number.value == 98765


@define_view
class _OwnedMainView(_NumberedMainView):
    """A main view that the app builds with an argument, which no save holds."""

    owner: str = attrs.field(kw_only=True, metadata={OMIT: True})

    @override
    def build_initial_view(self) -> _OwnedMainView:
        return _OwnedMainView(owner=self.owner)


def test_a_session_whose_app_builds_its_view_with_an_argument_comes_back(
    tmp_path: Path,
) -> None:
    """Its save is checked against a view that `build_initial_view` builds, as Open does."""
    folder = tmp_path / "sessions"
    first = _store(folder, lambda: (_OwnedMainView(owner="Ann"), None))
    session_id, session = _created(first)
    assert isinstance(session.main_view, _OwnedMainView)
    session.main_view.number.value = 98765
    first.keep_all()
    second = _store(folder, lambda: (_OwnedMainView(owner="Ann"), None))
    restored = second.get(session_id)
    second.keep_all()

    assert restored is not None
    assert isinstance(restored.main_view, _OwnedMainView)
    assert (restored.main_view.owner, restored.main_view.number.value) == ("Ann", 98765)
