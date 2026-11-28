"""Tests of the users that a login proxy names (`WebSettings.user_header`, `MainView.user`)."""

from __future__ import annotations

import asyncio
import base64
import functools
import secrets
import sys
import threading
import time
from typing import TYPE_CHECKING

import attrs
import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from typing_extensions import override

from composeui.core.application import WebSettings
from composeui.core.client import User
from composeui.core.view import ButtonView, DialogKind, DialogView, child, define_view
from composeui.webcore.webapplication import WebApplication
from examples.webhello import HelloMainView
from tests.webcore.support import (
    _action_id,
    _Browser,
    _field_id,
    _find,
    _HelloApp,
    _swapped,
    _type_name,
    _widget_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    from starlette.types import ASGIApp, Message

    from composeui.core.jobs import Job

_USERS = WebSettings(
    user_header="Remote-User", user_name_header="Remote-Name", user_email_header="Remote-Email"
)


def _cookie_data(cookie: str) -> str:
    """Get the text of Starlette's session cookie: its data, before its signature."""
    data = cookie.split(".", maxsplit=1)[0]
    return base64.b64decode(data + "=" * (-len(data) % 4)).decode("utf-8")


@define_view
class _UserNamedMainView(HelloMainView):
    """The hello app, its name field filled with its user as it is built."""

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.form.name.text = "" if self.user is None else self.user.id


class _UserNamedApp(WebApplication[_UserNamedMainView]):
    """The app of `_UserNamedMainView`, keeping each session's main view."""

    def __init__(self) -> None:
        super().__init__(build_main_view=_UserNamedMainView, settings=_USERS)
        self.session_views: list[_UserNamedMainView] = []

    @override
    def setup_session(self, main_view: _UserNamedMainView) -> None:
        main_view.status_bar.timeout = 0
        self.session_views.append(main_view)


def _answer(app: ASGIApp, headers: list[tuple[bytes, bytes]]) -> tuple[int, set[bytes]]:
    """Send a page's request with these raw headers, as uvicorn passes them.

    Get the answer's status and the names of its headers.

    Not through the test client, which sends a header's text again as UTF-8.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), *headers],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    async def request() -> None:
        await app(scope, receive, send)

    asyncio.run(request())
    status: int = sent[0]["status"]
    return status, {name for name, _ in sent[0]["headers"]}


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ([(b"remote-user", b"ada")], 200),
        ([], 403),
        ([(b"remote-user", b"")], 403),
        # a proxy that adds its header beside the browser's, rather than replace it
        ([(b"remote-user", b"ada"), (b"remote-user", b"grace")], 403),
        ([(b"remote-user", b"\xff")], 403),
        # the browser's name or email beside the proxy's: either may come first
        ([(b"remote-user", b"ada"), (b"remote-name", b"x"), (b"remote-name", b"y")], 403),
        ([(b"remote-user", b"ada"), (b"remote-email", b"x"), (b"remote-email", b"y")], 403),
    ],
    ids=["one", "none", "empty", "two", "not-utf8", "two-names", "two-emails"],
)
def test_only_a_request_that_names_one_user_is_served(
    headers: list[tuple[bytes, bytes]], status: int
) -> None:
    app = _HelloApp(_USERS)

    sent, names = _answer(app.create_starlette_app(), headers)

    assert sent == status
    # a refusal too: another site's frame gets no page to show
    assert {b"content-security-policy", b"x-frame-options"} <= names
    # no session built for nobody
    assert [view.user for view in app.session_views] == ([User(id="ada")] if status == 200 else [])


@pytest.mark.parametrize(
    ("headers", "user"),
    [
        (
            [
                (b"remote-user", b"ada"),
                (b"remote-name", "Ada Lövelace".encode()),
                (b"remote-email", b"ada@example.org"),
            ],
            User(id="ada", name="Ada Lövelace", email="ada@example.org"),
        ),
        ([(b"remote-user", b"ada"), (b"remote-name", b""), (b"remote-email", b"")], User(id="ada")),
        # a name in Latin-1, which an IdP may send: no name, but the user still gets in
        (
            [(b"remote-user", b"ada"), (b"remote-name", b"L\xf6velace")],
            User(id="ada"),
        ),
    ],
    ids=["all", "empty", "not-utf8"],
)
def test_the_user_s_name_and_email_come_from_their_headers(
    headers: list[tuple[bytes, bytes]], user: User
) -> None:
    app = _HelloApp(_USERS)

    sent, _ = _answer(app.create_starlette_app(), headers)

    assert sent == 200
    assert [view.user for view in app.session_views] == [user]


def test_each_user_of_a_browser_gets_their_own_session_and_browser_id() -> None:
    app = _HelloApp(_USERS)
    with _Browser(app.create_starlette_app(), {"Remote-User": "Ada Lovelace"}) as browser:
        browser.get("/")
        ada = app.session_views[0]
        _type_name(browser, ada, "Bob")
        same_user = browser.get("/").text
        # the proxy logged another user in, in the same browser: the cookie is Ada's
        refused = browser.post(
            f"/_composeui/widget/{_field_id(ada.form.name)}",
            data={"value": "Eve", "event": "input"},
            headers={"Remote-User": "grace"},
        )
        other_user = browser.get("/", headers={"Remote-User": "grace"}).text
        cookie = browser.cookies["session"]

    assert 'value="Bob"' in same_user
    assert refused.headers["hx-refresh"] == "true"  # the page reloads, Ada's session kept
    assert ada.form.name.text == "Bob"
    assert 'value="Bob"' not in other_user
    ada, grace = app.session_views
    assert (ada.user, grace.user) == (User(id="Ada Lovelace"), User(id="grace"))
    assert grace.browser_id != ada.browser_id
    # signed, not encrypted: anyone who has the cookie reads it
    assert "grace" not in _cookie_data(cookie)


@pytest.mark.parametrize(
    ("next_settings", "user", "keeps_it"),
    [
        (_USERS, "ada", True),
        (_USERS, "grace", False),
        # the login taken away: no request gets a user's save
        (WebSettings(), None, False),
    ],
    ids=["same-user", "other-user", "no-login"],
)
@pytest.mark.parametrize("server", ["session-folder", "reload"])
def test_a_saved_session_opens_for_its_own_user_only(
    tmp_path: Path, server: str, next_settings: WebSettings, user: str | None, *, keeps_it: bool
) -> None:
    folder = tmp_path / "sessions"
    key = secrets.token_urlsafe(32)

    def serve(settings: WebSettings) -> tuple[_HelloApp, Starlette]:
        if server == "reload":
            # a process of a `--reload` server, which saves its sessions for the next one
            app = _HelloApp(settings)
            return app, app.create_starlette_app(saved_sessions=tmp_path, secret_key=key)
        app = _HelloApp(attrs.evolve(settings, session_folder=folder))
        return app, app.create_starlette_app()

    first, starlette_app = serve(_USERS)
    with _Browser(starlette_app, {"Remote-User": "ada"}) as browser:
        browser.get("/")
        _type_name(browser, first.session_views[0], "Bob")
        cookie = browser.cookies["session"]

    second, starlette_app = serve(next_settings)
    # the proxy gives the user's email now: the session woken takes it
    headers = {} if user is None else {"Remote-User": user, "Remote-Email": f"{user}@example.org"}
    with _Browser(starlette_app, headers) as browser:
        browser.cookies.set("session", cookie)
        page = browser.get("/").text

    assert ('value="Bob"' in page) is keeps_it
    assert second.session_views[0].user == (
        None if user is None else User(id=user, email=f"{user}@example.org")
    )


def test_a_saved_session_that_a_poll_wakes_takes_the_user_s_headers_of_the_poll(
    tmp_path: Path,
) -> None:
    """Not only the page: any request of the session wakes it, built again for its user."""
    settings = attrs.evolve(_USERS, session_folder=tmp_path)
    first = _HelloApp(settings)
    with _Browser(first.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        browser.get("/")
        _type_name(browser, first.session_views[0], "Bob")
        cookie = browser.cookies["session"]

    second = _HelloApp(settings)
    headers = {"Remote-User": "ada", "Remote-Name": "Ada"}
    with _Browser(second.create_starlette_app(), headers) as browser:
        browser.cookies.set("session", cookie)
        browser.get("/_composeui/jobs")

    (main_view,) = second.session_views
    assert main_view.form.name.text == "Bob"  # her session, not a new one
    assert main_view.user == User(id="ada", name="Ada")


def test_new_builds_the_initial_view_for_the_session_s_own_user() -> None:
    app = _UserNamedApp()
    with _Browser(app.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        browser.get("/")
        (main_view,) = app.session_views
        browser.post(
            f"/_composeui/widget/{_action_id(main_view.file_menu.new)}", data={"event": "triggered"}
        )

    assert main_view.form.name.text == "ada"


def test_a_reload_keeps_what_the_user_typed_in_a_field_that_starts_with_their_name(
    tmp_path: Path,
) -> None:
    """The field's initial value, the user's name, is the same code: no edit to take."""
    key = secrets.token_urlsafe(32)
    first = _UserNamedApp()
    # a process of a `--reload` server, then the next one
    with _Browser(
        first.create_starlette_app(saved_sessions=tmp_path, secret_key=key), {"Remote-User": "ada"}
    ) as browser:
        browser.get("/")
        _type_name(browser, first.session_views[0], "Bob")
        cookie = browser.cookies["session"]

    second = _UserNamedApp()
    with _Browser(
        second.create_starlette_app(saved_sessions=tmp_path, secret_key=key), {"Remote-User": "ada"}
    ) as browser:
        browser.cookies.set("session", cookie)
        browser.get("/")

    assert second.session_views[0].form.name.text == "Bob"


@pytest.mark.parametrize("header", ["", "Remote User", "Rémote-User"])
@pytest.mark.parametrize(
    ("setting", "settings"),
    [
        ("user_header", lambda header: WebSettings(user_header=header)),
        (
            "user_name_header",
            lambda header: WebSettings(user_header="Remote-User", user_name_header=header),
        ),
        (
            "user_email_header",
            lambda header: WebSettings(user_header="Remote-User", user_email_header=header),
        ),
    ],
    ids=["user", "name", "email"],
)
def test_a_user_header_that_names_no_header_is_refused(
    setting: str, settings: Callable[[str], WebSettings], header: str
) -> None:
    with pytest.raises(ValueError, match=f"{setting}=.* isn't the name of a header"):
        settings(header)


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (lambda: WebSettings(user_email_header="Remote-Email"), "needs a user_header"),
        (
            lambda: WebSettings(user_header="Remote-User", user_name_header="remote-user"),
            "of user_header too",
        ),
        (
            lambda: WebSettings(
                user_header="Remote-User",
                user_name_header="Remote-Name",
                user_email_header="REMOTE-NAME",
            ),
            "of user_name_header too",
        ),
    ],
    ids=["no-user-header", "name-is-the-user", "email-is-the-name"],
)
def test_a_name_or_email_header_that_isn_t_its_own_is_refused(
    settings: Callable[[], WebSettings], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        settings()


_LOG_OUT = attrs.evolve(_USERS, logout_url="/oauth2/sign_out?rd=%2F")


@pytest.mark.parametrize(
    ("settings", "headers", "shown"),
    [
        (
            _LOG_OUT,
            {"Remote-User": "ada", "Remote-Name": "<b>Ada</b>", "Remote-Email": "ada@example.org"},
            ["<b>Ada</b>", "ada@example.org", "Log out"],
        ),
        # no name: the user's id; no email: no line for it
        (_LOG_OUT, {"Remote-User": "ada"}, ["ada", "Log out"]),
        # a login, but no address to log out at: nothing to offer
        (_USERS, {"Remote-User": "ada"}, None),
    ],
    ids=["name-and-email", "id-alone", "no-logout-url"],
)
def test_the_header_shows_the_user_and_log_out_with_a_logout_url(
    settings: WebSettings, headers: dict[str, str], shown: list[str] | None
) -> None:
    with _Browser(_HelloApp(settings).create_starlette_app(), headers) as browser:
        page = browser.get("/").text

    menu = _find(page, "cui-user-menu")
    if shown is None:
        assert menu is None
        return
    assert menu is not None
    # the proxy's text as it is: shown, not run as markup
    assert menu.text == "".join(shown)


def test_log_out_sends_the_page_to_the_logout_url_and_keeps_the_session() -> None:
    app = _HelloApp(_LOG_OUT)
    with _Browser(app.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        browser.get("/")
        _type_name(browser, app.session_views[0], "Bob")
        answer = browser.post("/_composeui/log-out")
        # the proxy logs her in again: her session is as she left it
        page = browser.get("/").text
        typed = browser.post(
            f"/_composeui/widget/{_field_id(app.session_views[0].form.name)}",
            data={"value": "Bo", "event": "input"},
        )

    assert answer.headers["hx-redirect"] == "/oauth2/sign_out?rd=%2F"
    assert 'value="Bob"' in page
    assert "hx-redirect" not in typed.headers  # the page left once: it stays now
    assert len(app.session_views) == 1


def test_log_out_without_its_session_goes_to_the_logout_url() -> None:
    """E.g. the session expired: no app's code is left to run."""
    app = _HelloApp(_LOG_OUT)
    with _Browser(app.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        answer = browser.post("/_composeui/log-out")

    assert answer.headers["hx-redirect"] == "/oauth2/sign_out?rd=%2F"
    assert app.session_views == []


@define_view
class _LeavingMainView(HelloMainView):
    """Logs the user out from a button of its own."""

    leave: ButtonView = child(ButtonView, text="Leave")

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.leave.clicked.connect(self.log_out)


class _LeavingApp(WebApplication[_LeavingMainView]):
    def __init__(self, settings: WebSettings) -> None:
        super().__init__(build_main_view=_LeavingMainView, settings=settings)
        self.session_views: list[_LeavingMainView] = []

    @override
    def setup_session(self, main_view: _LeavingMainView) -> None:
        self.session_views.append(main_view)


@pytest.mark.parametrize(
    ("settings", "redirect"),
    [(_LOG_OUT, "/oauth2/sign_out?rd=%2F"), (_USERS, None)],
    ids=["logout-url", "no-logout-url"],
)
def test_an_app_logs_the_user_out_from_its_own_button(
    settings: WebSettings, redirect: str | None
) -> None:
    app = _LeavingApp(settings)
    with _Browser(app.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        browser.get("/")
        (main_view,) = app.session_views
        answer = browser.post(
            f"/_composeui/widget/{_widget_id(main_view.leave.renderer)}", data={"event": "click"}
        )

    assert answer.status_code == 200
    assert answer.headers.get("hx-redirect") == redirect


def test_the_log_out_route_is_not_found_without_a_logout_url() -> None:
    app = _HelloApp(_USERS)
    with _Browser(app.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        browser.get("/")
        answer = browser.post("/_composeui/log-out")

    assert answer.status_code == 404
    assert "hx-redirect" not in answer.headers


@define_view
class _ConfirmedLogOutMainView(HelloMainView):
    """Asks before Log out; ends the session too, or not, as `ends_session` says."""

    confirm_log_out: DialogView = child(DialogView, title="Log out?", kind=DialogKind.CONFIRM)
    ends_session: bool = False

    @override
    def on_log_out(self) -> None:
        self.confirm_log_out.ask(self._leave)

    def _leave(self) -> None:
        if self.ends_session:
            self.close()
        self.log_out()


class _ConfirmedLogOutApp(WebApplication[_ConfirmedLogOutMainView]):
    def __init__(self, *, ends_session: bool) -> None:
        super().__init__(
            build_main_view=lambda: _ConfirmedLogOutMainView(ends_session=ends_session),
            settings=_LOG_OUT,
        )
        self.session_views: list[_ConfirmedLogOutMainView] = []

    @override
    def setup_session(self, main_view: _ConfirmedLogOutMainView) -> None:
        self.session_views.append(main_view)


@pytest.mark.parametrize("ends_session", [False, True], ids=["keeps-session", "ends-session"])
def test_an_app_asks_before_log_out_and_logs_out_once_the_user_agrees(
    *, ends_session: bool
) -> None:
    app = _ConfirmedLogOutApp(ends_session=ends_session)
    with _Browser(app.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        browser.get("/")
        (main_view,) = app.session_views
        _type_name(browser, main_view, "Bob")
        asked = browser.post("/_composeui/log-out")
        answer = f"/_composeui/widget/{_widget_id(main_view.confirm_log_out.renderer)}"
        canceled = browser.post(answer, data={"event": "reject"})
        browser.post("/_composeui/log-out")
        agreed = browser.post(answer, data={"event": "accept"})
        page = browser.get("/").text

    assert "hx-redirect" not in asked.headers
    dialog_id = _widget_id(main_view.confirm_log_out.renderer)
    assert "hidden" not in _swapped(asked.text, dialog_id).attributes  # asked: shown
    assert "hx-redirect" not in canceled.headers
    assert agreed.headers["hx-redirect"] == "/oauth2/sign_out?rd=%2F"
    # closed: the page she comes back to is a new session's
    assert ('value="Bob"' in page) is not ends_session
    assert len(app.session_views) == (2 if ends_session else 1)


#: what holds the job of `_SavedLogOutMainView` until the test lets it end
_SAVE_RELEASE = threading.Event()


#: a None for each time `on_log_out` of `_SavedLogOutMainView` ran
_LOG_OUTS: list[None] = []


def _save(_job: Job[None, None]) -> None:
    assert _SAVE_RELEASE.wait(30)


@define_view
class _SavedLogOutMainView(HelloMainView):
    """Logs out once a job, e.g. a save to the app's database, is over."""

    @override
    def on_log_out(self) -> None:
        _LOG_OUTS.append(None)
        job = self.jobs.start(_save)
        job.finished.connect(lambda _result: self.log_out())


class _SavedLogOutApp(WebApplication[_SavedLogOutMainView]):
    def __init__(self) -> None:
        super().__init__(build_main_view=_SavedLogOutMainView, settings=_LOG_OUT)
        self.session_views: list[_SavedLogOutMainView] = []

    @override
    def setup_session(self, main_view: _SavedLogOutMainView) -> None:
        self.session_views.append(main_view)


def test_log_out_from_a_job_s_callback_leaves_with_the_poll_that_brings_it() -> None:
    app = _SavedLogOutApp()
    with _Browser(app.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        browser.get("/")
        _SAVE_RELEASE.clear()
        try:
            clicked = browser.post("/_composeui/log-out")
        finally:
            _SAVE_RELEASE.set()
        left = _poll_until_redirect(browser)

    assert "hx-redirect" not in clicked.headers
    assert left == "/oauth2/sign_out?rd=%2F"


def _poll_until_redirect(browser: TestClient) -> str | None:
    """Poll as the page does while the jobs run, until an answer sends it away."""
    poll = browser.get("/_composeui/jobs")
    for _ in range(600):
        if "hx-redirect" in poll.headers:
            break
        time.sleep(0.05)
        poll = browser.get("/_composeui/jobs")
    redirect: str | None = poll.headers.get("hx-redirect")
    return redirect


def test_a_second_log_out_while_the_first_one_s_job_runs_does_nothing() -> None:
    """Its job's log out would wait in the session, and send the user back from the proxy."""
    app = _SavedLogOutApp()
    with _Browser(app.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        browser.get("/")
        (main_view,) = app.session_views
        _LOG_OUTS.clear()
        _SAVE_RELEASE.clear()
        try:
            browser.post("/_composeui/log-out")
            second = browser.post("/_composeui/log-out")  # nothing seems to happen
        finally:
            _SAVE_RELEASE.set()
        left = _poll_until_redirect(browser)
        # back from the proxy: the page, then a click, stay
        back = browser.get("/", follow_redirects=False)
        typed = browser.post(
            f"/_composeui/widget/{_field_id(main_view.form.name)}",
            data={"value": "Bob", "event": "input"},
        )
        clicks_before = len(_LOG_OUTS)
        # Log out is over: a new one runs again
        _SAVE_RELEASE.clear()
        try:
            browser.post("/_composeui/log-out")
        finally:
            _SAVE_RELEASE.set()
        left_again = _poll_until_redirect(browser)

    assert second.status_code == 200
    assert "hx-redirect" not in second.headers
    assert left == "/oauth2/sign_out?rd=%2F"
    assert back.status_code == 200
    assert "hx-redirect" not in typed.headers
    assert clicks_before == 1  # the second click didn't run `on_log_out`
    assert len(_LOG_OUTS) == 2
    assert left_again == "/oauth2/sign_out?rd=%2F"


@pytest.mark.parametrize("request_kind", ["page", "fragment"])
def test_log_out_from_a_job_s_callback_leaves_with_the_next_request_after_it(
    request_kind: str,
) -> None:
    """E.g. the user reloads the page, or a status bar fetches itself, before a poll."""
    app = _SavedLogOutApp()
    with _Browser(app.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        browser.get("/")
        (main_view,) = app.session_views
        where = (
            "/"
            if request_kind == "page"
            else f"/_composeui/widget/{_widget_id(main_view.status_bar.renderer)}"
        )
        _SAVE_RELEASE.clear()
        try:
            browser.post("/_composeui/log-out")
        finally:
            _SAVE_RELEASE.set()
        # its result waits for the session's next request, as no poll fetches it
        for _ in range(600):
            if not main_view.jobs.has_workers:
                break
            time.sleep(0.05)
        assert not main_view.jobs.has_workers
        loaded = browser.get(where, follow_redirects=False)
        again = browser.get(where, follow_redirects=False)

    if where == "/":
        assert loaded.status_code == 303
        assert loaded.headers["location"] == "/oauth2/sign_out?rd=%2F"
    else:
        assert loaded.headers["hx-redirect"] == "/oauth2/sign_out?rd=%2F"
    # once: the user back from the proxy gets the page
    assert again.status_code == 200
    assert "hx-redirect" not in again.headers


@define_view
class _FrenchMainView(HelloMainView):
    french: ButtonView = child(ButtonView, text="Français")

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.french.clicked.connect(lambda: self.set_language("fr"))


class _FrenchApp(WebApplication[_FrenchMainView]):
    def __init__(self) -> None:
        super().__init__(build_main_view=_FrenchMainView, settings=_LOG_OUT)
        self.session_views: list[_FrenchMainView] = []

    @override
    def setup_session(self, main_view: _FrenchMainView) -> None:
        self.session_views.append(main_view)


def test_the_user_menu_follows_the_language() -> None:
    app = _FrenchApp()
    views = app.session_views
    with _Browser(app.create_starlette_app(), {"Remote-User": "ada"}) as browser:
        browser.get("/")
        body = browser.post(
            f"/_composeui/widget/{_widget_id(views[0].french.renderer)}", data={"event": "click"}
        ).text

    assert "Se déconnecter" in _swapped(body, "cui-user-menu").text


@pytest.mark.parametrize(
    "url", ["/oauth2/sign_out", "/logout?rd=%2F", "https://login.example.org/logout?a=1"]
)
def test_a_logout_url_is_a_path_or_an_http_url(url: str) -> None:
    assert WebSettings(user_header="Remote-User", logout_url=url).logout_url == url


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (lambda: WebSettings(logout_url="/oauth2/sign_out"), "needs a user_header"),
        *(
            (
                functools.partial(WebSettings, user_header="Remote-User", logout_url=url),
                "isn't a path of the server nor an http or https URL",
            )
            for url in (
                "javascript:alert(1)",
                "oauth2/sign_out",
                "//login.example.org/logout",
                "https:///logout",
                "ftp://login.example.org/logout",
                "/log out",
                "/déconnexion",
                "/logout\r\nSet-Cookie: a=b",
                "/\\login.example.org/logout",
            )
        ),
    ],
)
def test_a_logout_url_that_the_page_can_t_go_to_is_refused(
    settings: Callable[[], WebSettings], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        settings()
