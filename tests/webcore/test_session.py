"""Tests of the web sessions: their life, their expiry, and their storage while idle."""

from __future__ import annotations

import contextlib
import errno
import itertools
import logging
import re
import sys
import threading
import time
import types
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

import attrs
from attrs import Factory
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    invariant,
    multiple,
    rule,
)
from starlette.testclient import TestClient

from composeui.core._views.base import made_signals
from composeui.core.application import WebSettings
from composeui.core.model import Model
from composeui.core.view import (
    ConsoleView,
    DialogView,
    FileUploadView,
    LabelRowIntInputView,
    ListSource,
    MainView,
    SourceTableView,
    UploadedFile,
    View,
    define_view,
)
from composeui.webcore import session as session_module
from composeui.webcore.page import SESSION_TAG_FIELD, SESSION_TAG_HEADER
from composeui.webcore.session import Hibernation, SessionStore, WebSession
from composeui.webcore.webapplication import WebApplication, WebModelApplication
from examples.webhello import HelloMainView, NameRowView
from tests.datafiles import DataFileMainView

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from composeui.core.jobs import Job
    from composeui.core.registry import RendererType

from tests.webcore.support import (
    _MAIN_VIEW_TYPES,
    _action_id,
    _Browser,
    _Clock,
    _count,
    _element,
    _field_id,
    _HelloApp,
    _Note,
    _part,
    _pick_file,
    _session_of,
    _type_name,
    _widget_id,
)


def test_a_closed_session_runs_none_of_its_jobs_callbacks() -> None:
    main_view = DataFileMainView()
    session = WebSession(main_view)
    started, release, threads = threading.Event(), threading.Event(), list[threading.Thread]()
    called: list[object] = []

    def work(job: Job[None, int]) -> None:
        threads.append(threading.current_thread())
        started.set()
        assert release.wait(30)
        job.report_progress(1)
        job.call_on_main_thread(lambda: called.append("handed over"))

    job = main_view.jobs.start(work)
    job.progress.connect(called.append)
    job.finished.connect(lambda _result: called.append("finished"))
    job.failed.connect(called.append)
    assert started.wait(30)  # running, not only started: a busy runner starts the thread late
    session.close()
    release.set()
    threads[0].join(30)

    assert not threads[0].is_alive()
    assert called == []


class _Guestbook(Model):
    def __init__(self) -> None:
        self.names: list[str] = []


class _ClosedGuestbook(_Guestbook):
    def __init__(self) -> None:
        super().__init__()
        self.is_closed = False

    @override
    def close(self) -> None:
        self.is_closed = True


def test_a_session_s_model_closes_with_it() -> None:
    models: list[_ClosedGuestbook] = []
    views: list[HelloMainView] = []

    class GuestbookApp(WebModelApplication[HelloMainView, _ClosedGuestbook]):
        @override
        def setup_session(self, main_view: HelloMainView) -> None:
            views.append(main_view)

    def build_model() -> _ClosedGuestbook:
        models.append(_ClosedGuestbook())
        return models[-1]

    app = GuestbookApp(build_main_view=HelloMainView, build_model=build_model)
    with _Browser(app.create_starlette_app()) as browser:
        browser.get("/")
        (view,) = views
        session_model = models[-1]
        exit_id = _action_id(view.file_menu.exit_app)
        browser.post(f"/widget/{exit_id}", data={"event": "triggered"})

    assert session_model.is_closed


def test_each_browser_gets_its_own_model() -> None:
    models: list[_Guestbook] = []

    def build_model() -> _Guestbook:
        models.append(_Guestbook())
        return models[-1]

    class GuestbookApp(WebModelApplication[HelloMainView, _Guestbook]):
        @override
        def setup_session(self, main_view: HelloMainView) -> None:
            views.append(main_view)

    views: list[HelloMainView] = []
    app = GuestbookApp(build_main_view=HelloMainView, build_model=build_model)
    name = app.main_view.form.name

    @app.connect(view=name, signals=[name.editing_finished])
    def sign(*, view: NameRowView, main_view: HelloMainView, model: _Guestbook) -> None:
        model.names.append(view.text)
        main_view.summary.text = ", ".join(model.names)

    def sign_as(client: TestClient, view: HelloMainView, text: str) -> str:
        """Enter `text` as the name; return the summary as the browser now shows it."""
        field_id = _field_id(view.form.name)
        response = client.post(f"/widget/{field_id}", data={"value": text, "event": "change"})
        assert response.status_code == 200
        return _element(client.get("/").text, _widget_id(view.summary.renderer)).text

    web = app.create_starlette_app()
    with _Browser(web) as alice, _Browser(web) as bob:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = views

        assert sign_as(alice, alice_view, "Alice") == "Alice"
        assert sign_as(bob, bob_view, "Bob") == "Bob"
        assert sign_as(alice, alice_view, "Ada") == "Alice, Ada"
    # one per session, and none for the template
    assert [model.names for model in models] == [["Alice", "Ada"], ["Bob"]]


def test_a_request_without_a_live_session_reloads_the_page(
    main_view: HelloMainView, app: _HelloApp
) -> None:
    field_id = _field_id(main_view.form.name)
    # e.g. after a server restart: the browser's cookie points at no session any more
    with _Browser(app.create_starlette_app()) as stale:
        posted = stale.post(f"/widget/{field_id}", data={"value": "x", "event": "input"})
        fetched = stale.get(f"/widget/{field_id}")
        uploaded = stale.post("/state", files={"file": ("s.hello", b"{}")})
        picked = stale.post(f"/widget/{field_id}/file", files={"file": ("a.txt", b"a")})
        polled = stale.get("/jobs")
        # a plain download link isn't htmx: it is sent to the page, which starts a session
        downloads = [
            stale.get("/state", follow_redirects=False),
            stale.post("/state/download", follow_redirects=False),
            stale.get(f"/widget/{field_id}/image", follow_redirects=False),
            stale.get(f"/widget/{field_id}/csv", follow_redirects=False),
            stale.get(f"/widget/{field_id}/text", follow_redirects=False),
        ]
        ticket = stale.get("/download/any", follow_redirects=False)

    for response in (posted, fetched, uploaded, picked, polled):
        assert response.status_code == 200
        assert response.headers["hx-refresh"] == "true"
        assert response.text == ""
    for downloaded in downloads:
        assert downloaded.status_code == 303
        assert downloaded.headers["location"] == "/"
    # followed by the page's script, never by the user: a redirect would save the page
    assert ticket.status_code == 404


def test_a_session_is_built_once_and_kept_across_reloads(app: _HelloApp) -> None:
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        _type_name(client, app.session_views[0], "Bob")

        page = client.get("/").text

    assert len(app.session_views) == 1
    assert 'value="Bob"' in page


#: every session is already idle for too long by its next request
_SHORT_LIVED = WebSettings(session_ttl=0.0)


def test_an_idle_session_expires() -> None:
    app = _HelloApp(_SHORT_LIVED)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        expired_view = app.session_views[0]

        response = client.post(
            f"/widget/{_field_id(expired_view.form.name)}",
            data={"value": "x", "event": "input"},
        )
        client.get("/")

    assert response.headers["hx-refresh"] == "true"
    assert expired_view.form.name.text == ""
    assert len(app.session_views) == 2  # the reload started a fresh session


def test_a_session_outlives_the_server_s_clock_stepping_back(
    client: TestClient, main_view: HelloMainView, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the cookie was signed at the page's load; then the clock steps back, e.g. at a sync
    stepped_back = time.time() - 5
    monkeypatch.setattr(time, "time", lambda: stepped_back)

    response = client.post(
        f"/widget/{_field_id(main_view.form.name)}", data={"value": "Alice", "event": "input"}
    )

    assert "hx-refresh" not in response.headers  # no reload into a new session
    assert main_view.form.name.text == "Alice"


def test_a_session_that_expires_cancels_its_jobs() -> None:
    canceled = threading.Event()

    def work(job: Job[None, None]) -> None:
        if not job.sleep(30):
            canceled.set()

    class WorkingApp(_HelloApp):
        @override
        def setup_session(self, main_view: HelloMainView) -> None:
            super().setup_session(main_view)
            main_view.jobs.start(work)

    with _Browser(WorkingApp(_SHORT_LIVED).create_starlette_app()) as client:
        client.get("/")
        client.get("/jobs")  # finds the session expired, and starts no other

    assert canceled.wait(10)


def test_a_full_server_refuses_new_sessions_but_keeps_its_own() -> None:
    """Requests without a cookie, which anyone can send, can't push out a user's session."""
    app = _HelloApp(WebSettings(max_sessions=2))
    web = app.create_starlette_app()
    with _Browser(web) as alice, _Browser(web) as bob, _Browser(web) as carol:
        alice.get("/")
        bob.get("/")
        alice_view, bob_view = app.session_views

        refused = carol.get("/")
        refused_page = carol.get("/results")  # a page's address too

        assert refused.status_code == 503
        assert refused_page.status_code == 503
        assert len(app.session_views) == 2  # no main view built for it
        _type_name(alice, alice_view, "Alice")  # the live sessions still work
        assert alice_view.form.name.text == "Alice"
        # Exit ends Bob's session, which leaves room for Carol's
        bob.post(f"/widget/{_action_id(bob_view.file_menu.exit_app)}", data={"event": "triggered"})
        assert carol.get("/").status_code == 200
        assert len(app.session_views) == 3


class _ReleasedModel(Model):
    """A session's model, which records that the store released it."""

    def __init__(self) -> None:
        super().__init__()
        self.is_released = False

    @override
    def close(self) -> None:
        self.is_released = True


class _CountedModel(Model):
    """A session's model, which counts how many times it's closed."""

    def __init__(self) -> None:
        super().__init__()
        self.closes = 0

    @override
    def close(self) -> None:
        self.closes += 1


class _SessionStoreMachine(RuleBasedStateMachine):
    """A store of 3 sessions in memory and 1 on disk, used in any order.

    Idle 5 seconds, a session goes to disk; 10 seconds, it ends. The sessions as it
    should keep them: each live one with when it was last used, and each one on disk with
    the name it held and when it was last used.
    """

    TTL, MOST, IDLE, MOST_SAVED = 10.0, 3, 5.0, 1
    ids = Bundle("ids")

    def __init__(self) -> None:
        super().__init__()
        self.clock = _Clock()
        self.patched = mock.patch.object(session_module, "time", self.clock)
        self.patched.start()
        self.store = SessionStore(
            lambda: (HelloMainView(), _ReleasedModel()),
            ttl=self.TTL,
            max_sessions=self.MOST,
            hibernation=Hibernation(self.IDLE, self.MOST_SAVED),
        )
        self.live: dict[str, tuple[WebSession, float]] = {}
        self.on_disk: dict[str, tuple[str, float]] = {}
        #: the sessions freed: ended, or saved to disk
        self.freed: list[WebSession] = []
        self.made: set[str] = set()

    def _expire(self) -> None:
        for session_id, (session, used) in list(self.live.items()):
            if self.clock.now - used >= self.TTL:
                del self.live[session_id]
                self.freed.append(session)
        for session_id, (_name, used) in list(self.on_disk.items()):
            if self.clock.now - used >= self.TTL:
                del self.on_disk[session_id]

    # the user's name: one a new session doesn't have, which only its saved state brings back
    @rule(target=ids, name=st.sampled_from(["Alice", "Bob"]))
    def create(self, name: str) -> Any:
        self._expire()
        created = self.store.get_or_create(None)
        if len(self.live) >= self.MOST:  # full: refused, the live ones kept
            assert created is None
            return multiple()
        assert created is not None
        session_id, session = created
        assert session_id not in self.live
        assert isinstance(session.main_view, HelloMainView)
        session.main_view.form.name.text = name
        self.live[session_id] = (session, self.clock.now)
        self.made.add(session_id)
        return session_id

    @rule(session_id=st.one_of(ids, st.just("forged")))
    def get(self, session_id: str) -> None:
        self._expire()
        got = self.store.get(session_id)
        if session_id in self.live:  # the same session, its idle time from now
            session = self.live[session_id][0]
            assert got is session
            self.live[session_id] = (session, self.clock.now)
        elif session_id in self.on_disk and len(self.live) < self.MOST:
            # built again, with the user's name, and in memory
            assert got is not None
            assert isinstance(got.main_view, HelloMainView)
            assert got.main_view.form.name.text == self.on_disk.pop(session_id)[0]
            self.live[session_id] = (got, self.clock.now)
        else:  # ended, never made, or no room to wake it
            assert got is None

    # a page's request: its cookie's session, else a new one
    @rule(target=ids, session_id=st.one_of(ids, st.just("forged")))
    def get_or_create(self, session_id: str) -> Any:
        self._expire()
        found = self.store.get_or_create(session_id)
        if session_id in self.live:  # the same session, its idle time from now
            session = self.live[session_id][0]
            assert found == (session_id, session)
            self.live[session_id] = (session, self.clock.now)
            return multiple()
        if session_id in self.on_disk:
            # woken, if there's room; else refused, never replaced by a new session
            if len(self.live) >= self.MOST:
                assert found is None
                return multiple()
            assert found is not None
            assert found[0] == session_id
            assert isinstance(found[1].main_view, HelloMainView)
            assert found[1].main_view.form.name.text == self.on_disk.pop(session_id)[0]
            self.live[session_id] = (found[1], self.clock.now)
            return multiple()
        # ended, or never made: a new one, if there's room
        if len(self.live) >= self.MOST:
            assert found is None
            return multiple()
        assert found is not None
        new_id, session = found
        assert new_id not in self.made
        self.live[new_id] = (session, self.clock.now)
        self.made.add(new_id)
        return new_id

    @rule(session_id=ids)
    def drop(self, session_id: str) -> None:
        self.store.drop(session_id)
        if session_id in self.live:
            self.freed.append(self.live.pop(session_id)[0])

    @rule()
    def hibernate(self) -> None:
        self._expire()
        idle = [
            session_id
            for session_id, (_session, used) in self.live.items()
            if self.clock.now - used >= self.IDLE
        ]
        self.store.hibernate_idle()
        saved = [session_id for session_id in idle if not self.store.is_at_hand(session_id)]
        # those idle, while there's room on disk; the others still in memory
        assert len(saved) == min(len(idle), self.MOST_SAVED - len(self.on_disk))
        assert all(self.store.is_at_hand(session_id) for session_id in self.live.keys() - idle)
        for session_id in saved:
            session, used = self.live.pop(session_id)
            assert isinstance(session.main_view, HelloMainView)
            self.on_disk[session_id] = (session.main_view.form.name.text, used)
            self.freed.append(session)

    # mostly less than the timeout: sessions used, then idle, then used again
    @rule(seconds=st.sampled_from([1.0, 4.0, 6.0, 9.0, 10.0]))
    def wait(self, seconds: float) -> None:
        self.clock.now += seconds

    @invariant()
    def freed_sessions_alone_are_released(self) -> None:
        # dropped or saved at once; expired once the store is used again
        self._expire()
        self.store.get("forged")  # used: it drops the expired ones

        def released(session: WebSession) -> bool:
            assert isinstance(session.model, _ReleasedModel)
            return session.model.is_released

        assert all(released(session) for session in self.freed)
        assert not any(released(session) for session, _used in self.live.values())
        # on disk until they expire, then gone
        for session_id in self.made:
            assert self.store.is_at_hand(session_id) is (session_id not in self.on_disk)

    @override
    def teardown(self) -> None:
        self.store.close_all()
        self.patched.stop()


TestASessionStoreUsedInAnyOrder = _SessionStoreMachine.TestCase
TestASessionStoreUsedInAnyOrder.settings = settings(max_examples=100, stateful_step_count=20)


def test_a_store_saves_its_idle_sessions_while_it_has_room_and_wakes_them_as_they_were() -> None:
    """A run of `_SessionStoreMachine` pinned: Hypothesis's CI profile may not draw it."""
    machine = _SessionStoreMachine()
    try:
        alice = machine.create("Alice")
        bob = machine.create("Bob")
        machine.wait(6.0)
        machine.hibernate()  # one of them: the disk has room for one
        machine.freed_sessions_alone_are_released()
        carol = machine.create("Carol")
        machine.create("Dave")
        machine.get(alice)  # not woken: the memory is full
        machine.get(bob)
        machine.drop(carol)
        machine.get(alice)  # woken as it was
        machine.get(bob)
        machine.wait(6.0)
        machine.hibernate()
        machine.wait(4.0)
        machine.freed_sessions_alone_are_released()  # expired on disk too
    finally:
        machine.teardown()


@define_view
class _HoldingMainView(MainView):
    """A session holding, on demand, each thing that a study doesn't save."""

    console: ConsoleView = Factory(ConsoleView)
    upload: FileUploadView = Factory(FileUploadView)
    notes: SourceTableView = Factory(SourceTableView)
    question: DialogView = Factory(DialogView)


@define_view
class _KeptByTheAppMainView(_HoldingMainView):
    """A session that the app keeps in memory, e.g. holding an object a callback built."""

    @override
    def can_hibernate(self) -> bool:
        return False


def _hold_nothing(_session: WebSession, _stack: contextlib.ExitStack, _tmp_path: Path) -> None:
    pass


def _hold_a_job(session: WebSession, stack: contextlib.ExitStack, _tmp_path: Path) -> None:
    may_end = threading.Event()
    jobs = session.main_view.jobs

    def end() -> None:
        may_end.set()
        for _ in range(200):  # until its thread is over
            if not jobs.has_workers:
                return
            time.sleep(0.05)

    stack.callback(end)
    jobs.start(lambda _job: may_end.wait(10))


def _hold_a_download(session: WebSession, _stack: contextlib.ExitStack, _tmp_path: Path) -> None:
    session.main_view.download("report.txt", b"made by the app")


def _hold_a_question(session: WebSession, _stack: contextlib.ExitStack, _tmp_path: Path) -> None:
    assert isinstance(session.main_view, _HoldingMainView)
    session.main_view.question.open()


def _hold_an_upload(session: WebSession, _stack: contextlib.ExitStack, tmp_path: Path) -> None:
    assert isinstance(session.main_view, _HoldingMainView)
    path = tmp_path / "data.csv"
    path.write_text("a\n1\n")
    session.main_view.upload.take_file(UploadedFile("data.csv", 4, "text/csv", path))


def _hold_a_new_source(session: WebSession, _stack: contextlib.ExitStack, _tmp_path: Path) -> None:
    assert isinstance(session.main_view, _HoldingMainView)
    session.main_view.notes.source = ListSource(_Note, {"text": "Note"}, [_Note("from a file")])


def _hold_output(session: WebSession, _stack: contextlib.ExitStack, _tmp_path: Path) -> None:
    assert isinstance(session.main_view, _HoldingMainView)
    session.main_view.console.append("solver started\n")


def _hold_a_request(session: WebSession, stack: contextlib.ExitStack, _tmp_path: Path) -> None:
    stack.enter_context(session.held())  # e.g. an upload still arriving


@pytest.mark.parametrize(
    ("main_view_type", "hold", "is_kept"),
    [
        (_HoldingMainView, _hold_nothing, False),
        (_HoldingMainView, _hold_a_job, True),
        (_HoldingMainView, _hold_a_download, True),
        (_HoldingMainView, _hold_a_question, True),
        (_HoldingMainView, _hold_an_upload, True),
        (_HoldingMainView, _hold_a_new_source, True),
        (_HoldingMainView, _hold_output, True),
        (_HoldingMainView, _hold_a_request, True),
        (_KeptByTheAppMainView, _hold_nothing, True),
    ],
)
def test_an_idle_session_stays_in_memory_while_it_holds_what_a_study_doesn_t(
    main_view_type: type[_HoldingMainView],
    hold: Callable[[WebSession, contextlib.ExitStack, Path], None],
    is_kept: bool,
    tmp_path: Path,
) -> None:
    clock = _Clock()
    with mock.patch.object(session_module, "time", clock):
        store = SessionStore(
            lambda: (main_view_type(), None),
            ttl=60.0,
            max_sessions=1,
            hibernation=Hibernation(5.0, 10),
        )
        created = store.get_or_create(None)
        assert created is not None
        session_id, session = created
        with contextlib.ExitStack() as stack:
            hold(session, stack, tmp_path)
            clock.now += 6.0
            store.hibernate_idle()
            kept = store.is_at_hand(session_id)
        store.close_all()

    assert kept is is_kept


def test_a_session_is_idle_from_the_end_of_its_last_long_request() -> None:
    clock = _Clock()
    with mock.patch.object(session_module, "time", clock):
        store = SessionStore(
            lambda: (HelloMainView(), None),
            ttl=60.0,
            max_sessions=1,
            hibernation=Hibernation(5.0, 10),
        )
        created = store.get_or_create(None)
        assert created is not None
        session_id, session = created
        with session.held():  # e.g. a large upload
            clock.now += 6.0
        store.hibernate_idle()
        kept = store.is_at_hand(session_id)
        clock.now += 5.0
        store.hibernate_idle()
        saved = not store.is_at_hand(session_id)
    store.close_all()

    assert kept
    assert saved


def test_a_session_doesn_t_expire_while_a_long_request_holds_it() -> None:
    clock = _Clock()
    with mock.patch.object(session_module, "time", clock):
        store = SessionStore(lambda: (HelloMainView(), None), ttl=60.0, max_sessions=2)
        created = store.get_or_create(None)
        assert created is not None
        session_id, session = created
        with session.held():  # e.g. a large download
            clock.now += 61.0
            store.get_or_create(None)  # another session's request: the store drops the idle
        clock.now += 59.0  # idle from the download's end
        kept = store.get(session_id)
    store.close_all()

    assert kept is session


def _watched_threading() -> tuple[types.SimpleNamespace, threading.Event]:
    """Get a `threading` for the store whose events say when a request waits on one."""
    waiting = threading.Event()

    class WatchedEvent(threading.Event):
        @override
        def wait(self, timeout: float | None = None) -> bool:
            waiting.set()
            return super().wait(timeout)

    return types.SimpleNamespace(Lock=threading.Lock, Event=WatchedEvent), waiting


class _SlowSavedModel(Model):
    """A model with data, whose save waits for the test."""

    data_name = "data.txt"

    def __init__(self) -> None:
        super().__init__()
        self.saving = threading.Event()
        self.may_save = threading.Event()
        self.saves = 0
        self.is_closed = False

    @override
    def save_data(self, path: Path) -> None:
        self.saves += 1
        self.saving.set()
        assert self.may_save.wait(10)
        path.write_text("data")

    @override
    def open_data(self, path: Path) -> None:
        assert path.read_text() == "data"

    @override
    def close(self) -> None:
        self.is_closed = True


def test_a_request_during_the_save_of_an_idle_session_keeps_it_in_memory() -> None:
    watched, waiting = _watched_threading()
    clock = _Clock()
    model = _SlowSavedModel()
    with (
        mock.patch.object(session_module, "time", clock),
        mock.patch.object(session_module, "threading", watched),
    ):
        store = SessionStore(
            lambda: (HelloMainView(), model),
            ttl=60.0,
            max_sessions=1,
            hibernation=Hibernation(5.0, 10),
        )
        created = store.get_or_create(None)
        assert created is not None
        session_id, session = created
        clock.now += 6.0
        sweep = threading.Thread(target=store.hibernate_idle)
        sweep.start()
        assert model.saving.wait(10)
        got: list[WebSession | None] = []
        request = threading.Thread(target=lambda: got.append(store.get(session_id)))
        request.start()
        assert waiting.wait(10)  # the request waits for the save
        model.may_save.set()
        sweep.join(10)
        request.join(10)
        store.hibernate_idle()  # used just now: not idle any more

    assert got == [session]
    assert store.is_at_hand(session_id)
    assert not model.is_closed
    store.close_all()
    assert model.is_closed


def test_two_requests_for_a_session_on_disk_build_it_once() -> None:
    watched, waiting = _watched_threading()
    clock = _Clock()
    builds: list[HelloMainView] = []
    may_build = threading.Event()

    def build() -> tuple[MainView, Model | None]:
        if len(builds) > 0:  # the wake's
            assert may_build.wait(10)
        builds.append(HelloMainView())
        return builds[-1], None

    with (
        mock.patch.object(session_module, "time", clock),
        mock.patch.object(session_module, "threading", watched),
    ):
        store = SessionStore(build, ttl=60.0, max_sessions=1, hibernation=Hibernation(5.0, 10))
        created = store.get_or_create(None)
        assert created is not None
        session_id, _session = created
        clock.now += 6.0
        store.hibernate_idle()
        got: list[WebSession | None] = []
        first = threading.Thread(target=lambda: got.append(store.get(session_id)))
        first.start()
        second = threading.Thread(target=lambda: got.append(store.get(session_id)))
        second.start()
        assert waiting.wait(10)  # one waits for the other's wake
        may_build.set()
        first.join(10)
        second.join(10)
        store.close_all()

    assert len(builds) == 2
    assert len(got) == 2
    assert got[0] is got[1] is not None


def test_an_idle_session_that_fails_to_save_stays_in_memory_and_isn_t_tried_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingModel(_SlowSavedModel):
        @override
        def save_data(self, path: Path) -> None:
            self.saves += 1
            raise OSError(errno.ENOSPC, "No space left on device", str(path))

    clock = _Clock()
    model = FailingModel()
    with mock.patch.object(session_module, "time", clock):
        store = SessionStore(
            lambda: (HelloMainView(), model),
            ttl=60.0,
            max_sessions=1,
            hibernation=Hibernation(5.0, 10),
        )
        created = store.get_or_create(None)
        assert created is not None
        session_id, session = created
        clock.now += 6.0
        with caplog.at_level(logging.ERROR, logger="COMPOSEUI"):
            store.hibernate_idle()
        clock.now += 6.0
        store.hibernate_idle()

        assert store.get(session_id) is session
    store.close_all()
    assert model.saves == 1
    assert "Can't save an idle session" in caplog.text


class _UnopenableModel(_SlowSavedModel):
    """A model whose data saves, then fails to open, e.g. a file the disk lost."""

    @override
    def save_data(self, path: Path) -> None:
        path.write_text("data")

    @override
    def open_data(self, path: Path) -> None:
        msg = f"can't open {path.name}"
        raise RuntimeError(msg)


@pytest.mark.parametrize("fails_to", ["build", "open"])
def test_a_session_that_fails_to_wake_is_gone_and_its_next_request_starts_anew(
    fails_to: str,
) -> None:
    clock = _Clock()
    models: list[_SlowSavedModel] = []

    def build() -> tuple[MainView, Model | None]:
        if len(models) == 1 and fails_to == "build":  # e.g. a database the app can't reach
            msg = "can't open data.txt"
            raise RuntimeError(msg)
        models.append(_UnopenableModel())
        return HelloMainView(), models[-1]

    with mock.patch.object(session_module, "time", clock):
        store = SessionStore(build, ttl=60.0, max_sessions=1, hibernation=Hibernation(5.0, 10))
        created = store.get_or_create(None)
        assert created is not None
        session_id, _session = created
        clock.now += 6.0
        store.hibernate_idle()

        with pytest.raises(RuntimeError, match=r"can't open data\.txt"):
            store.get(session_id)
        assert store.get(session_id) is None
    store.close_all()
    assert all(model.is_closed for model in models)  # the woken one's too


def test_a_session_on_disk_keeps_its_uploads_until_the_server_stops() -> None:
    clock = _Clock()
    with mock.patch.object(session_module, "time", clock):
        store = SessionStore(
            lambda: (DataFileMainView(), None),
            ttl=60.0,
            max_sessions=1,
            hibernation=Hibernation(5.0, 10),
        )
        created = store.get_or_create(None)
        assert created is not None
        session_id, session = created
        assert isinstance(session.main_view, DataFileMainView)
        measurements = session.main_view.form.measurements
        _pick_file(session, _part(measurements, "field").widget_id, "first.csv", b"first")
        path = measurements.path
        assert path is not None
        clock.now += 6.0
        store.hibernate_idle()
        on_disk = not store.is_at_hand(session_id)
        woken = store.get(session_id)
        clock.now += 6.0
        store.hibernate_idle()  # to disk again, as the server stops
        store.close_all()

    assert on_disk
    assert woken is not None
    assert isinstance(woken.main_view, DataFileMainView)
    assert woken.main_view.form.measurements.path == path
    assert not path.exists()


#: sessions saved to disk once idle: the sweep's interval too, on the real clock
_IDLE = WebSettings(session_idle=0.05)


class _IdleGuestbookApp(WebModelApplication[HelloMainView, _ReleasedModel]):
    """The hello app with a model, its sessions saved to disk once idle on the test's clock."""

    def __init__(
        self,
        build_model: Callable[[], _ReleasedModel] = _ReleasedModel,
        settings: WebSettings = _IDLE,
    ) -> None:
        super().__init__(build_main_view=HelloMainView, build_model=build_model, settings=settings)
        self.session_views: list[HelloMainView] = []
        self.models: list[_ReleasedModel] = []

    @override
    def setup_model(self, main_view: HelloMainView, model: _ReleasedModel) -> None:
        main_view.status_bar.timeout = 0
        self.session_views.append(main_view)
        self.models.append(model)


def _wait_until_released(model: _ReleasedModel) -> None:
    """Wait until the server's sweep saves the model's session to disk, which frees it."""
    for _ in range(200):
        if model.is_released:
            return
        time.sleep(0.05)


def _wait_until_saved(app: _IdleGuestbookApp) -> None:
    _wait_until_released(app.models[0])


def test_an_idle_session_goes_to_disk_and_its_page_reloads_into_it_as_it_was() -> None:
    app = _IdleGuestbookApp()
    clock = _Clock()
    with (
        mock.patch.object(session_module, "time", clock),
        _Browser(app.create_starlette_app()) as browser,
    ):
        page = browser.get("/").text
        tag = re.search(rf'name="{SESSION_TAG_FIELD}" value="([0-9a-f]+)"', page)
        assert tag is not None
        _type_name(browser, app.session_views[0], "Bob")
        clock.now += 1.0
        _wait_until_saved(app)
        # the page that the saved session served, as it posts its next event
        response = browser.post(
            f"/widget/{_field_id(app.session_views[0].form.name)}",
            data={"value": "Bobby", "event": "input"},
            headers={SESSION_TAG_HEADER: tag[1]},
        )
        reloaded = browser.get("/").text

    assert response.headers["hx-refresh"] == "true"
    assert 'value="Bob"' in reloaded
    assert len(app.session_views) == 2  # built again, and opened


class _UnclosableModel(_ReleasedModel):
    """A model that fails to close, e.g. a database that another program locked."""

    @override
    def close(self) -> None:
        super().close()
        msg = "the database is locked"
        raise RuntimeError(msg)


def test_a_model_that_fails_to_close_leaves_its_session_on_disk_and_the_server_saving(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _IdleGuestbookApp(_UnclosableModel)
    web = app.create_starlette_app()
    clock = _Clock()
    # one server's lifespan, so one sweep: Bob's browser starts none of its own
    bob = _Browser(web)
    with mock.patch.object(session_module, "time", clock), _Browser(web) as alice:
        alice.get("/")
        _type_name(alice, app.session_views[0], "Alice")
        clock.now += 1.0
        with caplog.at_level(logging.ERROR, logger="COMPOSEUI"):
            _wait_until_saved(app)
            reopened = alice.get("/").text
            bob.get("/")
            clock.now += 1.0
            _wait_until_released(app.models[-1])  # the sweep saves Bob's too
            saved = app.models[-1].is_released  # before the server stops, which releases them

    assert 'value="Alice"' in reopened
    assert saved
    assert "Can't save the idle sessions to disk." in caplog.text


def test_a_full_server_keeps_a_session_on_disk_for_its_browser() -> None:
    """A browser whose session waits on disk gets no new session that would take its cookie.

    Even when a slot frees just after the server found none: e.g. the sweep saves another
    session then. Its lookup and a new session are one decision.
    """
    app = _IdleGuestbookApp(settings=attrs.evolve(_IDLE, max_sessions=1))
    web = app.create_starlette_app()
    store: SessionStore = web.state.sessions
    clock = _Clock()
    lookup = store.get

    def get_then_free_a_slot(session_id: Any) -> WebSession | None:
        found = lookup(session_id)
        if found is None:  # the sweep saves Bob's session meanwhile
            clock.now += 1.0
            store.hibernate_idle()
        return found

    bob = _Browser(web)
    with mock.patch.object(session_module, "time", clock), _Browser(web) as alice:
        alice.get("/")
        _type_name(alice, app.session_views[0], "Alice")
        clock.now += 1.0
        _wait_until_saved(app)
        bob.get("/")  # takes the only room in memory
        with mock.patch.object(store, "get", get_then_free_a_slot):
            refused = alice.get("/")
        clock.now += 1.0
        store.hibernate_idle()  # Bob's session to disk: room for Alice's
        reopened = alice.get("/").text

    assert refused.status_code == 503
    assert len(app.session_views) == 3  # Alice's, Bob's, then Alice's woken
    assert 'value="Alice"' in reopened


def test_a_session_used_while_another_is_saved_stays_in_memory() -> None:
    clock = _Clock()
    models: list[_SlowSavedModel] = []

    def build() -> tuple[MainView, Model | None]:
        models.append(_SlowSavedModel())
        return HelloMainView(), models[-1]

    with mock.patch.object(session_module, "time", clock):
        store = SessionStore(build, ttl=60.0, max_sessions=2, hibernation=Hibernation(5.0, 10))
        first = store.get_or_create(None)
        second = store.get_or_create(None)
        assert first is not None
        assert second is not None
        clock.now += 6.0
        sweep = threading.Thread(target=store.hibernate_idle)
        sweep.start()
        assert models[0].saving.wait(10)  # the first one's save
        used = store.get(second[0])  # a click on the second one's page
        models[0].may_save.set()
        models[1].may_save.set()
        sweep.join(10)

        assert used is second[1]
        assert not store.is_at_hand(first[0])
        assert store.is_at_hand(second[0])
    store.close_all()


@define_view
class _LoadedNotesMainView(MainView):
    """A large table whose source the app gives again on each `loaded`, as a study opens."""

    notes: SourceTableView = Factory(SourceTableView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loaded.connect(self._show_notes)

    def _show_notes(self) -> None:
        self.notes.source = ListSource(_Note, {"text": "Note"}, [_Note("from the study")])


class _IdleNotesApp(WebModelApplication[_LoadedNotesMainView, _ReleasedModel]):
    """`_LoadedNotesMainView` served, its sessions saved to disk once idle on the test's clock."""

    def __init__(self) -> None:
        super().__init__(
            build_main_view=_LoadedNotesMainView,
            build_model=_ReleasedModel,
            settings=_IDLE,
        )
        self.session_views: list[_LoadedNotesMainView] = []
        self.models: list[_ReleasedModel] = []

    @override
    def setup_model(self, main_view: _LoadedNotesMainView, model: _ReleasedModel) -> None:
        self.session_views.append(main_view)
        self.models.append(model)


@pytest.mark.parametrize("loads_by", ["wake", "new"])
def test_a_session_whose_table_source_a_study_gives_again_goes_to_disk_again(
    loads_by: str,
) -> None:
    app = _IdleNotesApp()
    clock = _Clock()
    with (
        mock.patch.object(session_module, "time", clock),
        _Browser(app.create_starlette_app()) as browser,
    ):
        browser.get("/")
        if loads_by == "wake":
            clock.now += 1.0
            _wait_until_released(app.models[0])
            browser.get("/")  # opens the study: a new source
        else:
            new = app.session_views[0].file_menu.new
            browser.post(f"/widget/{_action_id(new)}", data={"event": "triggered"})
        clock.now += 1.0
        _wait_until_released(app.models[-1])
        saved = app.models[-1].is_released  # before the server stops, which releases them all

    assert saved


_STARTS = itertools.count()


@define_view
class _NumberedMainView(MainView):
    """A main view whose field starts with another value at each build, as a date would."""

    number: LabelRowIntInputView = attrs.Factory(lambda: LabelRowIntInputView(value=next(_STARTS)))


def test_a_session_saved_while_idle_keeps_a_value_that_its_field_starts_with() -> None:
    clock = _Clock()
    with mock.patch.object(session_module, "time", clock):
        store = SessionStore(
            lambda: (_NumberedMainView(), None),
            ttl=60.0,
            max_sessions=1,
            hibernation=Hibernation(5.0, 10),
        )
        created = store.get_or_create(None)
        assert created is not None
        session_id, session = created
        assert isinstance(session.main_view, _NumberedMainView)
        started = session.main_view.number.value
        clock.now += 6.0
        store.hibernate_idle()
        woken = store.get(session_id)
    store.close_all()

    assert woken is not session
    assert woken is not None
    assert isinstance(woken.main_view, _NumberedMainView)
    assert woken.main_view.number.value == started


def test_a_failed_session_setup_closes_its_model_and_a_retry_owns_its_own() -> None:
    models: list[_CountedModel] = []
    failures = [True, True, True, False]

    def build_model() -> _CountedModel:
        models.append(_CountedModel())
        return models[-1]

    def setup_model(_main_view: HelloMainView, _model: _CountedModel) -> None:
        if failures.pop(0):
            msg = "the setup failed"
            raise RuntimeError(msg)

    class App(WebModelApplication[HelloMainView, _CountedModel]):
        pass

    app = App(build_main_view=HelloMainView, build_model=build_model, setup_model=setup_model)
    with TestClient(app.create_starlette_app(), raise_server_exceptions=False) as client:
        for _ in range(3):
            assert client.get("/").status_code == 500
        assert [model.closes for model in models] == [1, 1, 1]
        assert client.get("/").status_code == 200
        assert models[-1].closes == 0
    assert [model.closes for model in models] == [1, 1, 1, 1]


class _UnrenderableMainView(HelloMainView):
    @override
    def render(self, renderer_type: RendererType) -> None:
        msg = "no renderer for it"
        raise RuntimeError(msg)


@pytest.mark.parametrize("has_model", [True, False])
def test_a_session_failing_to_render_closes_its_model_if_it_has_one(*, has_model: bool) -> None:
    model = _CountedModel() if has_model else None
    store = SessionStore(lambda: (_UnrenderableMainView(), model), ttl=10.0, max_sessions=1)
    with pytest.raises(RuntimeError, match="no renderer"):
        store.get_or_create(None)
    assert model is None or model.closes == 1


def test_a_failed_setup_of_a_session_without_a_model_keeps_its_own_error() -> None:
    class App(WebApplication[HelloMainView]):
        @override
        def setup_session(self, main_view: HelloMainView) -> None:
            msg = "the setup failed"
            raise RuntimeError(msg)

    app = App(build_main_view=HelloMainView)
    with (
        TestClient(app.create_starlette_app()) as client,
        pytest.raises(RuntimeError, match="the setup failed"),
    ):
        client.get("/")


def test_a_session_used_expires_its_timeout_after_its_last_use() -> None:
    clock = _Clock()
    with mock.patch.object(session_module, "time", clock):
        store = SessionStore(lambda: (HelloMainView(), None), ttl=10, max_sessions=1)
        created = store.get_or_create(None)
        assert created is not None
        session_id, session = created

        clock.now = 9
        assert store.get(session_id) is session
        clock.now = 18  # 18 seconds since it was made, 9 since it was used
        assert store.get(session_id) is session
        clock.now = 28
        assert store.get(session_id) is None


def test_a_saved_session_opens_only_under_an_id_the_server_makes(
    app: _HelloApp, tmp_path: Path
) -> None:
    saved = tmp_path / "saved"
    saved.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "study").write_text("{}")
    sessions: SessionStore = app.create_starlette_app(saved_sessions=saved).state.sessions

    # e.g. a cookie signed with the key, and so trusted: still never a path elsewhere
    assert sessions.get("../outside") is None
    assert (outside / "study").exists()
    # an id the server could have made, but saved by none: e.g. a crashed process's
    assert sessions.get("a" * 43) is None
    sessions.drop("a" * 43)  # e.g. by two requests at once, each told it closed
    assert app.session_views == []


class _SlowGreetingApp(_HelloApp):
    """A greeting whose message times out while the request that showed it still runs."""

    def __init__(self) -> None:
        super().__init__()
        self.messages_seen_by_the_request: list[str] = []
        self.timer_waiting = threading.Event()

    @override
    def setup_session(self, main_view: HelloMainView) -> None:
        super().setup_session(main_view)
        main_view.status_bar.timeout = 0.05

        # connected after the greeting, so it runs once "Hello, ...!" is shown
        def slow_callback(_text: str) -> None:
            assert self.timer_waiting.wait(10)
            self.messages_seen_by_the_request.append(main_view.status_bar.message)

        main_view.form.name.text_edited.connect(slow_callback)


def test_a_message_timer_waits_for_the_request_holding_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _SlowGreetingApp()
    starlette_app = app.create_starlette_app()
    with _Browser(starlette_app) as client:
        client.get("/")
        main_view = app.session_views[0]
        session = _session_of(starlette_app, client)
        lock = session.lock

        class WatchedLock:
            def __enter__(self) -> None:
                if not lock.acquire(blocking=False):
                    if isinstance(threading.current_thread(), threading.Timer):
                        app.timer_waiting.set()  # the timer found the request holding the lock
                    lock.acquire()

            def __exit__(self, *_exc: object) -> None:
                lock.release()

        monkeypatch.setattr(session, "lock", WatchedLock())

        _type_name(client, main_view, "Bob")

        # the timer couldn't touch the tree mid-request: the clear waited for the lock
        assert app.messages_seen_by_the_request == ["Hello, Bob!"]
        deadline = time.monotonic() + 2
        while main_view.status_bar.message and time.monotonic() < deadline:
            time.sleep(0.01)
        assert main_view.status_bar.message == ""


def _session_tag(page: str) -> str:
    """Get the session that `page` names, for its script's requests and in Save's form."""
    script = re.search(r'data-session="([0-9a-f]+)"', page)
    save = re.search(rf'name="{SESSION_TAG_FIELD}" value="([0-9a-f]+)"', page)
    assert script is not None
    assert save is not None
    assert script[1] == save[1]
    return script[1]


def test_a_page_of_an_ended_session_reloads_rather_than_act_on_the_new_one(
    app: _HelloApp, main_view: HelloMainView, client: TestClient
) -> None:
    ended_tag = _session_tag(client.get("/").text)
    client.post(f"/widget/{_action_id(main_view.file_menu.exit_app)}", data={"event": "triggered"})
    current_tag = _session_tag(client.get("/").text)  # e.g. another tab: the cookie's new session
    _, new_view = app.session_views
    # an id that the ended page shows can name a view of the new session: `id()` reuses them
    field_id = _field_id(new_view.form.name)
    save_id = _action_id(new_view.file_menu.save)
    saves = _count(new_view.file_menu.save.triggered)

    stale = client.post(
        f"/widget/{field_id}",
        data={"value": "x", "event": "input"},
        headers={SESSION_TAG_HEADER: ended_tag},
    )
    # Save's form, which carries no header
    stale_save = client.post(
        "/state/download",
        data={"trigger": save_id, SESSION_TAG_FIELD: ended_tag},
        follow_redirects=False,
    )
    current = client.post(
        f"/widget/{field_id}",
        data={"value": "y", "event": "input"},
        headers={SESSION_TAG_HEADER: current_tag},
    )
    current_save = client.post(
        "/state/download", data={"trigger": save_id, SESSION_TAG_FIELD: current_tag}
    )

    assert stale.headers["hx-refresh"] == "true"
    assert stale_save.headers["location"] == "/"  # the tab goes to the cookie's session
    assert "hx-refresh" not in current.headers
    assert "attachment" in current_save.headers["content-disposition"]
    assert new_view.form.name.text == "y"
    assert len(saves) == 1


def _views_under(view: View) -> Iterator[View]:
    yield view
    for child_view in view.children_views:
        yield from _views_under(child_view)


@pytest.mark.parametrize("main_view_type", _MAIN_VIEW_TYPES)
def test_a_session_makes_only_the_signals_something_connects(
    main_view_type: type[MainView], tmp_path: Path
) -> None:
    """A view's signal is made on its first read: walking the views must not read them all."""
    view = main_view_type()
    session = WebSession(view)  # built, wired and rendered
    session.page_html()
    view.set_language("fr")
    view.save_state(tmp_path / f"study{view.extension}")
    view.reset_state()

    unconnected = [
        f"{type(each).__name__}.{name}"
        for each in _views_under(view)
        for name, signal in made_signals(each)
        # what the test checks is internal: no public API tells a signal's callbacks
        if len(signal._callbacks) == 0  # noqa: SLF001
    ]
    assert unconnected == []
    session.close()
