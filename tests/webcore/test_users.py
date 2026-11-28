"""Tests of the users that a login proxy names (`WebSettings.user_header`, `MainView.user`)."""

from __future__ import annotations

import asyncio
import base64
import secrets
import sys
from typing import TYPE_CHECKING

import attrs
import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from typing_extensions import override

from composeui.core.application import WebSettings
from composeui.core.client import User
from composeui.core.view import define_view
from composeui.webcore.webapplication import WebApplication
from examples.webhello import HelloMainView
from tests.webcore.support import _action_id, _Browser, _field_id, _HelloApp, _type_name

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from starlette.applications import Starlette
    from starlette.types import ASGIApp, Message

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
