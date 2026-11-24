"""Tests of the web backend's defenses: a post's origin, the headers, another session."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from starlette.testclient import TestClient

from composeui.core.view import (
    StreamContent,
)
from composeui.webcore.headers import POLICY
from composeui.webcore.icons import icon_url

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO


from tests.webcore.support import (
    _action_id,
    _Browser,
    _count,
    _element,
    _field_id,
    _HelloApp,
    _type_name,
)


def test_a_browser_cannot_reach_another_sessions_widgets(app: _HelloApp) -> None:
    web = app.create_starlette_app()
    with _Browser(web) as alice, _Browser(web) as mallory:
        alice.get("/")
        mallory.get("/")
        alice_view = app.session_views[0]

        # widget ids are guessable (`id()`-based): they must only resolve per session
        alice_field = _field_id(alice_view.form.name)
        response = mallory.post(
            f"/_composeui/widget/{alice_field}", data={"value": "x", "event": "input"}
        )

        assert response.status_code == 404
        assert alice_view.form.name.text == ""
        # while the very same id still works for its own session
        _type_name(alice, alice_view, "Alice")
        assert alice_view.form.name.text == "Alice"


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        # same site, not same origin: another port on localhost, a sibling subdomain
        {"Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "none"},
        {"Origin": "http://evil.example"},
        {"Origin": "http://testserver:9000"},
        {"Origin": "null"},  # e.g. a sandboxed frame
        {"Referer": "http://evil.example/page"},
        {},  # nothing proves where it comes from
    ],
)
def test_a_post_from_another_origin_is_refused(app: _HelloApp, headers: dict[str, str]) -> None:
    with TestClient(app.create_starlette_app()) as browser:
        browser.get("/")  # the session's cookie, which the browser sends along anyway
        (main_view,) = app.session_views
        save = main_view.file_menu.save
        saved = _count(save.triggered)
        field_id = _field_id(main_view.form.name)

        responses = [
            browser.post(
                f"/_composeui/widget/{field_id}",
                data={"value": "x", "event": "input"},
                headers=headers,
            ),
            browser.post(
                "/_composeui/state/download", data={"trigger": _action_id(save)}, headers=headers
            ),
            browser.post("/_composeui/state", files={"file": ("s.hello", b"{}")}, headers=headers),
            browser.post(
                f"/_composeui/widget/{field_id}/file",
                files={"file": ("a.txt", b"a")},
                headers=headers,
            ),
        ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert main_view.form.name.text == ""
    assert saved == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-origin"},
        # older browsers: no Fetch Metadata, but the request's origin
        {"Origin": "http://testserver"},
        {"Referer": "http://testserver/"},
    ],
)
def test_a_post_from_the_app_s_own_page_is_served(app: _HelloApp, headers: dict[str, str]) -> None:
    with TestClient(app.create_starlette_app()) as browser:
        browser.get("/")
        (session_view,) = app.session_views

        response = browser.post(
            f"/_composeui/widget/{_field_id(session_view.form.name)}",
            data={"value": "Ada", "event": "input"},
            headers=headers,
        )

    assert response.status_code == 200
    assert session_view.form.name.text == "Ada"


def test_the_session_cookie_stays_off_cross_site_posts_and_away_from_scripts(
    app: _HelloApp,
) -> None:
    """A cross-site post carries no cookie, a page's script can't read it, no subdomain gets it."""
    with _Browser(app.create_starlette_app()) as browser:
        cookie = browser.get("/").headers["set-cookie"]

    attributes: dict[str, str] = {}
    for part in cookie.split(";")[1:]:
        name, _, value = part.strip().lower().partition("=")
        attributes[name] = value
    assert attributes["samesite"] in {"lax", "strict"}
    assert "httponly" in attributes
    assert "domain" not in attributes


def test_every_response_carries_the_security_headers(app: _HelloApp, tmp_path: Path) -> None:
    """Another site's frame would get the user's clicks past the origin check."""
    icon = tmp_path / "logo.svg"
    icon.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    icon_address = icon_url(str(icon))
    assert icon_address is not None
    with _Browser(app.create_starlette_app()) as browser:
        responses = [browser.get("/")]
        (main_view,) = app.session_views
        responses += [
            browser.get(f"/_composeui/widget/{_field_id(main_view.form.name)}"),
            browser.get("/_composeui/state"),
            browser.get("/_composeui/static/htmx.min.js"),
            browser.get(icon_address),  # with a policy of its own
            browser.get("/_composeui/widget/any/picture"),  # with a policy of its own once found
            browser.get("/_composeui/reload?instance=any"),  # only a `--reload` server's
            browser.get("/_composeui/download/any"),  # no such file
            browser.get("/_composeui/style/theme.css"),  # no theme
            browser.get("/_composeui/style/files/studio.css"),  # no style folder
            browser.post("/_composeui/state", headers={"Sec-Fetch-Site": "cross-site"}),  # refused
        ]

        def fails(_sink: BinaryIO) -> None:
            msg = "source gone"
            raise ValueError(msg)

        # streamed as written, or failed before its first bytes
        main_view.download("rows.csv", StreamContent(lambda sink: sink.write(b"a,b\n")))
        main_view.download("failed.csv", StreamContent(fails))
        written, failed = [
            a["href"] or ""
            for tag, a in _element(browser.get("/").text, "cui-downloads").descendants
            if tag == "a"
        ]
        streamed = [browser.head(written), browser.get(written), browser.get(failed)]
        responses += streamed
        # a new tab's redirect to a page the app opens: no `Referer` reaches that page
        main_view.open_url("https://example.org/help")
        (tab,) = [
            a["href"] or ""
            for tag, a in _element(browser.get("/").text, "cui-downloads").descendants
            if tag == "a"
        ]
        opened = browser.get(tab, follow_redirects=False)
        responses.append(opened)

    assert opened.status_code == 303

    assert [response.status_code for response in streamed] == [200, 200, 500]

    for response in responses:
        assert response.headers["x-frame-options"] == "DENY"
        assert POLICY in response.headers.get_list("content-security-policy")
        assert response.headers.get_list("x-content-type-options") == ["nosniff"]
        assert response.headers["referrer-policy"] == "same-origin"
