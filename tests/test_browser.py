"""The web backend in a real browser: what only a browser can show.

The HTTP tests in `test_webrenderer.py` check the markup; these check what the page's
scripts and htmx do with it. Opt in with `make browser-test`, which needs the `browser`
dependency group and a Chromium from `uv run --group browser playwright install chromium`;
without them, these tests are skipped.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pytest

pytest.importorskip("starlette")
pytest.importorskip("playwright.sync_api")

import uvicorn
from playwright.sync_api import Error, expect, sync_playwright

from composeui.webcore.webapplication import WebApplication
from examples.pipeform import PipeMainView
from examples.webhello import HelloApp, HelloMainView
from tests.pages import PagesMainView

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Browser, Locator, Page, Route
    from starlette.applications import Starlette

pytestmark = pytest.mark.browser

#: how long the status bar shows a message, kept short so its auto-clear is quick to see
_MESSAGE_TIMEOUT = 0.5


class _BrowserHelloApp(HelloApp):
    def setup_session(self, main_view: HelloMainView) -> None:
        main_view.status_bar.timeout = _MESSAGE_TIMEOUT


@contextlib.contextmanager
def _serve(app: Starlette) -> Iterator[str]:
    """Serve `app` on a free local port while the block runs; yield its base url."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            pytest.fail("the server didn't start")
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join()


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    """Serve the hello app for the whole module."""
    with _serve(_BrowserHelloApp().create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def pipe_base_url() -> Iterator[str]:
    """Serve the pipe form, whose checks span several fields, for the whole module."""
    with _serve(WebApplication(build_main_view=PipeMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def pages_base_url() -> Iterator[str]:
    """Serve an app with two pages, for the whole module."""
    with _serve(WebApplication(build_main_view=PagesMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Error as error:
            pytest.skip(f"no Chromium for Playwright: {error.message.splitlines()[0]}")
        yield browser
        browser.close()


@pytest.fixture
def page(browser: Browser, base_url: str) -> Iterator[Page]:
    """Open a page in a fresh context: its own cookies, so its own session."""
    context = browser.new_context(base_url=base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def pipe_page(browser: Browser, pipe_base_url: str) -> Iterator[Page]:
    """Open the pipe form like `page`, in a session of its own."""
    context = browser.new_context(base_url=pipe_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def pages_page(browser: Browser, pages_base_url: str) -> Iterator[Page]:
    """Open the app with two pages like `page`, in a session of its own."""
    context = browser.new_context(base_url=pages_base_url)
    page = context.new_page()
    yield page
    context.close()


def _posted(page: Page) -> object:
    """Wait for the page's next widget POST to be answered."""
    return page.expect_response(
        lambda response: response.request.method == "POST" and "/widget/" in response.url
    )


def test_typing_keeps_the_caret_where_the_user_put_it(page: Page) -> None:
    page.goto("/")
    name = page.get_by_label("Name")
    with _posted(page):
        name.press_sequentially("Alce")
    name.press("ArrowLeft")
    name.press("ArrowLeft")
    with _posted(page):
        name.press("i")
    # the response updated the page (the greeting) but left the field alone
    expect(page.locator("footer")).to_have_text("Hello, Alice!")
    expect(name).to_have_value("Alice")
    expect(name).to_be_focused()
    expect(name).to_have_js_property("selectionStart", 3)


def test_alt_shift_runs_a_menu_shortcut(page: Page) -> None:
    page.goto("/")
    name = page.get_by_label("Name")
    with _posted(page):
        name.press_sequentially("Alice")
    # New is Ctrl+N on the desktop: browsers keep that one, so it's Alt+Shift+N here
    with _posted(page):
        page.keyboard.press("Alt+Shift+KeyN")
    expect(name).to_have_value("")


def test_a_field_is_invalid_exactly_while_its_log_shows_an_error(page: Page) -> None:
    page.goto("/")
    name = page.get_by_label("Name")
    expect(name).to_have_attribute("aria-invalid", "true")  # "A name is mandatory"
    with _posted(page):
        name.press_sequentially("A")
    expect(name).not_to_have_attribute("aria-invalid", "true")
    with _posted(page):
        name.press("Backspace")
    expect(name).to_have_attribute("aria-invalid", "true")


def test_the_page_needs_nothing_from_another_host(page: Page, base_url: str) -> None:
    app_host = urlsplit(base_url).netloc
    elsewhere: list[str] = []

    def block_other_hosts(route: Route) -> None:
        if urlsplit(route.request.url).netloc == app_host:
            route.continue_()
        else:
            elsewhere.append(route.request.url)
            route.abort()

    page.route("**/*", block_other_hosts)
    page.goto("/")
    page.wait_for_load_state("networkidle")

    assert elsewhere == []
    assert page.evaluate("typeof htmx") == "object"
    # styled by the app's own stylesheet: the body has daisyUI's background, not none
    background = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert background not in ("", "rgba(0, 0, 0, 0)", "transparent")


def test_the_status_bar_clears_itself_once_its_message_times_out(page: Page) -> None:
    page.goto("/")
    status_bar = page.locator("footer")
    with _posted(page):
        page.get_by_label("Name").press_sequentially("Alice")
    expect(status_bar).to_have_text("Hello, Alice!")
    # nothing else is sent: the bar asks for its own state once the message has expired
    expect(status_bar).to_have_text("", timeout=(_MESSAGE_TIMEOUT + 5) * 1000)


def test_the_theme_menu_overrides_the_browser_until_set_back_to_system(page: Page) -> None:
    def background() -> object:
        return page.evaluate("getComputedStyle(document.body).backgroundColor")

    def option(theme: str) -> Locator:
        """Open the Theme menu and return its `theme` item."""
        page.get_by_role("button", name="Theme").click()
        return page.get_by_role("button", name=theme)

    page.emulate_media(color_scheme="light")
    page.goto("/")
    light = background()
    expect(option("System")).to_have_attribute("aria-pressed", "true")

    page.get_by_role("button", name="Dark").click()  # from the menu still open
    dark = background()
    assert dark != light
    # the choice outlives a reload, and wins over the browser's light preference
    page.reload()
    assert background() == dark
    expect(option("Dark")).to_have_attribute("aria-pressed", "true")

    page.get_by_role("button", name="System").click()
    page.reload()
    assert background() == light
    # following the browser again: its switch to dark shows at once
    page.emulate_media(color_scheme="dark")
    assert background() == dark


def test_a_failing_form_check_marks_the_fields_it_names(pipe_page: Page) -> None:
    """The page marks a field from its row's log, as the field itself isn't swapped."""

    def border(field: Locator) -> object:
        return field.evaluate("field => getComputedStyle(field).borderColor")

    pipe_page.goto("/")
    main_radius, incident_radius = pipe_page.get_by_label("Radius").all()[:2]
    main_width = pipe_page.get_by_label("Width").first
    expect(main_radius).not_to_have_attribute("aria-invalid", "true")
    valid_border = border(main_radius)

    # below the incident radius, once left: the check naming both radii fails
    main_radius.press("Control+a")
    main_radius.press_sequentially("5")
    main_radius.press("Tab")
    for field in (main_radius, incident_radius):
        expect(field).to_have_attribute("aria-invalid", "true")
        assert border(field) != valid_border
    expect(main_width).not_to_have_attribute("aria-invalid", "true")  # not involved

    main_radius.press("Control+a")
    main_radius.press_sequentially("60")
    main_radius.press("Tab")
    for field in (main_radius, incident_radius):
        expect(field).not_to_have_attribute("aria-invalid", "true")
    assert border(main_radius) == valid_border


def test_checking_and_unchecking_the_box_reaches_the_server(pipe_page: Page) -> None:
    """An unchecked box posts no value: htmx leaves it out, as a form would."""
    pipe_page.goto("/")
    insulated = pipe_page.get_by_role("checkbox", name="Insulated pipe")
    thickness = pipe_page.get_by_label("Insulation Thickness")
    expect(thickness).to_be_disabled()

    with _posted(pipe_page):
        insulated.check()
    expect(thickness).to_be_enabled()

    with _posted(pipe_page):
        insulated.uncheck()
    expect(thickness).to_be_disabled()
    expect(insulated).not_to_be_checked()


def test_back_and_forward_go_through_the_pages_shown(pages_page: Page, pages_base_url: str) -> None:
    page = pages_page
    page.goto("/")
    expect(page).to_have_url(f"{pages_base_url}/inputs")
    name = page.get_by_role("textbox")
    with _posted(page):
        name.press_sequentially("pipe")
    total = page.get_by_text("Total: 0")
    expect(total).to_be_hidden()

    with _posted(page):
        page.get_by_role("link", name="Results").click()
    expect(page).to_have_url(f"{pages_base_url}/results")
    expect(total).to_be_visible()
    expect(name).to_be_hidden()
    expect(page.get_by_role("link", name="Results")).to_have_attribute("aria-current", "page")

    page.go_back()
    expect(page).to_have_url(f"{pages_base_url}/inputs")
    expect(name).to_be_visible()
    expect(name).to_have_value("pipe")  # the server's state, not a stale copy
    expect(total).to_be_hidden()

    page.go_forward()
    expect(page).to_have_url(f"{pages_base_url}/results")
    expect(total).to_be_visible()
