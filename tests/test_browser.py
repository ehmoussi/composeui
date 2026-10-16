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
from examples.pipechart import PipeChartMainView
from examples.pipeform import PipeMainView
from examples.taskview import TASK_COUNT, TaskMainView
from examples.webhello import HelloApp, HelloMainView
from tests.charts import ChartPagesMainView
from tests.dialogs import DialogsMainView
from tests.grid import GridMainView
from tests.horizontal import ButtonsMainView, HorizontalMainView
from tests.pages import PagesMainView, WidePageMainView
from tests.tables import EditableTableMainView
from tests.vertical import VerticalMainView

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Browser, FloatRect, Locator, Page, Route
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


class _QuickTasksApp(WebApplication[TaskMainView]):
    """The task example, its tasks short enough for a test to wait for them."""

    def __init__(self) -> None:
        super().__init__(build_main_view=TaskMainView)

    def setup_session(self, main_view: TaskMainView) -> None:
        main_view.config.min_duration.value = main_view.config.max_duration.value = 1


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
def dialogs_base_url() -> Iterator[str]:
    """Serve an app asking to confirm an edit, for the whole module."""
    with _serve(WebApplication(build_main_view=DialogsMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def horizontal_base_url() -> Iterator[str]:
    """Serve an app with tables side by side, for the whole module."""
    app = WebApplication(build_main_view=HorizontalMainView).create_starlette_app()
    with _serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def buttons_base_url() -> Iterator[str]:
    """Serve an app with rows of buttons packed at either end, for the whole module."""
    with _serve(WebApplication(build_main_view=ButtonsMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def wide_page_base_url() -> Iterator[str]:
    """Serve an app with a wide page and no router, for the whole module."""
    with _serve(WebApplication(build_main_view=WidePageMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def vertical_base_url() -> Iterator[str]:
    """Serve an app with a table above its button, for the whole module."""
    app = WebApplication(build_main_view=VerticalMainView).create_starlette_app()
    with _serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def grid_base_url() -> Iterator[str]:
    """Serve an app with views in a grid, for the whole module."""
    with _serve(WebApplication(build_main_view=GridMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def places_base_url() -> Iterator[str]:
    """Serve an app with a table whose notes are editable, for the whole module."""
    app = WebApplication(build_main_view=EditableTableMainView).create_starlette_app()
    with _serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def tasks_base_url() -> Iterator[str]:
    """Serve the task example, whose tasks run in threads, for the whole module."""
    with _serve(_QuickTasksApp().create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def chart_base_url() -> Iterator[str]:
    """Serve the pipe chart example, for the whole module."""
    app = WebApplication(build_main_view=PipeChartMainView).create_starlette_app()
    with _serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def chart_pages_base_url() -> Iterator[str]:
    """Serve an app with a chart on its second page, for the whole module."""
    app = WebApplication(build_main_view=ChartPagesMainView).create_starlette_app()
    with _serve(app) as url:
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


@pytest.fixture
def dialogs_page(browser: Browser, dialogs_base_url: str) -> Iterator[Page]:
    """Open the app asking to confirm an edit like `page`, in a session of its own."""
    context = browser.new_context(base_url=dialogs_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def horizontal_page(browser: Browser, horizontal_base_url: str) -> Iterator[Page]:
    """Open the app with tables side by side like `page`, in a session of its own."""
    context = browser.new_context(base_url=horizontal_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def places_page(browser: Browser, places_base_url: str) -> Iterator[Page]:
    """Open the app with an editable table like `page`, in a session of its own."""
    context = browser.new_context(base_url=places_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def buttons_page(browser: Browser, buttons_base_url: str) -> Iterator[Page]:
    """Open the app with rows of buttons like `page`, in a session of its own."""
    context = browser.new_context(base_url=buttons_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def wide_page(browser: Browser, wide_page_base_url: str) -> Iterator[Page]:
    """Open the app with a wide page like `page`, in a session of its own."""
    context = browser.new_context(base_url=wide_page_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def vertical_page(browser: Browser, vertical_base_url: str) -> Iterator[Page]:
    """Open the app with a table above its button like `page`, in a session of its own."""
    context = browser.new_context(base_url=vertical_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def grid_page(browser: Browser, grid_base_url: str) -> Iterator[Page]:
    """Open the app with views in a grid like `page`, in a session of its own."""
    context = browser.new_context(base_url=grid_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def tasks_page(browser: Browser, tasks_base_url: str) -> Iterator[Page]:
    """Open the task example like `page`, in a session of its own."""
    context = browser.new_context(base_url=tasks_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def chart_page(browser: Browser, chart_base_url: str) -> Iterator[Page]:
    """Open the pipe chart example like `page`, in a session of its own."""
    context = browser.new_context(base_url=chart_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def chart_pages_page(browser: Browser, chart_pages_base_url: str) -> Iterator[Page]:
    """Open the app with a chart on its second page like `page`, in a session of its own."""
    context = browser.new_context(base_url=chart_pages_base_url)
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


def test_the_main_column_is_as_wide_as_the_shown_page_lets_it(pages_page: Page) -> None:
    page = pages_page
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto("/")
    main = page.get_by_role("main")
    narrow = main.bounding_box()
    assert narrow is not None

    with _posted(page):
        page.get_by_role("link", name="Results").click()
    expect(page.get_by_text("Total: 0")).to_be_visible()
    wide = main.bounding_box()
    assert wide is not None
    assert wide["width"] > narrow["width"]

    with _posted(page):
        page.get_by_role("link", name="Inputs").click()
    expect(page.get_by_role("textbox")).to_be_visible()
    assert main.bounding_box() == narrow


def test_a_wide_page_with_no_router_widens_the_main_column(
    wide_page: Page, pages_page: Page
) -> None:
    for page in (wide_page, pages_page):
        page.set_viewport_size({"width": 1600, "height": 900})
        page.goto("/")
    wide = wide_page.get_by_role("main").bounding_box()
    narrow = pages_page.get_by_role("main").bounding_box()  # on its narrow first page
    assert wide is not None
    assert narrow is not None
    assert wide["width"] > narrow["width"]


def test_a_dialog_opens_as_a_modal_and_closes_on_its_answer(dialogs_page: Page) -> None:
    page = dialogs_page
    page.goto("/")
    name = page.get_by_text("Ada")
    dialog = page.get_by_role("dialog", name="Clear the name")
    expect(dialog).to_be_hidden()

    with _posted(page):
        page.keyboard.press("Alt+Shift+KeyL")  # the Clear action
    expect(dialog).to_be_visible()
    expect(dialog).to_have_js_property("open", value=True)
    clear = dialog.get_by_role("button", name="Clear")
    expect(clear).to_be_focused()

    with _posted(page):
        page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(name).to_be_visible()

    with _posted(page):
        page.keyboard.press("Alt+Shift+KeyL")
    with _posted(page):
        clear.click()
    expect(dialog).to_be_hidden()
    expect(name).to_be_hidden()


def _box(locator: Locator) -> FloatRect:
    """Where `locator`'s element is on the page, now."""
    box = locator.bounding_box()
    assert box is not None
    return box


def test_a_horizontal_view_shares_the_row_by_stretch(horizontal_page: Page) -> None:
    page = horizontal_page
    page.set_viewport_size({"width": 1000, "height": 600})
    page.goto("/")
    narrow = page.get_by_role("table").filter(has_text="Narrow").bounding_box()
    wide = page.get_by_role("table").filter(has_text="Wide").bounding_box()
    assert narrow is not None
    assert wide is not None

    assert narrow["y"] == wide["y"]
    assert narrow["x"] + narrow["width"] < wide["x"]
    assert wide["width"] == pytest.approx(3 * narrow["width"], rel=0.02)
    # the hidden table takes no share: the two shown span the row, inset alike both sides
    assert wide["x"] + wide["width"] == pytest.approx(1000 - narrow["x"], abs=1)


def test_a_narrow_horizontal_view_stacks_its_views(horizontal_page: Page) -> None:
    page = horizontal_page
    narrow = page.get_by_role("table").filter(has_text="Narrow")
    wide = page.get_by_role("table").filter(has_text="Wide")
    page.set_viewport_size({"width": 500, "height": 600})
    page.goto("/")

    narrow_box, wide_box = _box(narrow), _box(wide)
    # in order, one above the other, each as wide as the row
    assert wide_box["y"] > narrow_box["y"] + narrow_box["height"]
    assert (wide_box["x"], wide_box["width"]) == (narrow_box["x"], narrow_box["width"])

    page.set_viewport_size({"width": 1000, "height": 600})
    narrow_box, wide_box = _box(narrow), _box(wide)
    assert narrow_box["y"] == wide_box["y"]
    assert wide_box["width"] == pytest.approx(3 * narrow_box["width"], rel=0.02)


def test_buttons_with_no_share_pack_at_their_row_s_start_or_end(buttons_page: Page) -> None:
    page = buttons_page
    page.set_viewport_size({"width": 1000, "height": 600})
    page.goto("/")
    boxes = {}
    for name in ("Add", "Remove", "Cancel", "Save"):
        box = page.get_by_role("button", name=name).bounding_box()
        assert box is not None
        boxes[name] = box
    add, remove, cancel, save = boxes.values()

    # as wide as their text, side by side
    assert add["width"] < 200
    assert 0 < remove["x"] - (add["x"] + add["width"]) < 40
    # each row spans the column: one starts where the other ends
    assert cancel["x"] > remove["x"] + remove["width"]
    assert save["x"] + save["width"] == pytest.approx(1000 - add["x"], abs=1)


def test_a_vertical_view_stacks_its_views_at_its_top(vertical_page: Page) -> None:
    page = vertical_page
    page.set_viewport_size({"width": 1000, "height": 600})
    page.goto("/")
    table = page.get_by_role("table").filter(has_text="Short").bounding_box()
    button = page.get_by_role("button", name="Add").bounding_box()
    tall = page.get_by_role("table").filter(has_text="Tall").bounding_box()
    assert table is not None
    assert button is not None
    assert tall is not None

    assert table["y"] == tall["y"]
    # the views are apart by the row's gap between its cells, nothing more
    assert button["y"] - (table["y"] + table["height"]) == pytest.approx(
        tall["x"] - (table["x"] + table["width"]), abs=1
    )
    # next to a taller table, the column's spare height is left below its views
    assert button["y"] + button["height"] < tall["y"] + tall["height"]


def test_a_grid_view_places_its_views_in_equally_wide_columns(grid_page: Page) -> None:
    page = grid_page
    page.set_viewport_size({"width": 1000, "height": 600})
    page.goto("/")
    first = page.get_by_role("table").filter(has_text="First").bounding_box()
    button = page.get_by_role("button", name="Add").bounding_box()
    spanning = page.get_by_role("table").filter(has_text="Spanning").bounding_box()
    assert first is not None
    assert button is not None
    assert spanning is not None
    # within 2px: a table is inset in its cell by its border, the button isn't
    gap = (spanning["width"] - 3 * first["width"]) / 2

    assert first["y"] == pytest.approx(button["y"], abs=1)
    assert gap > 0
    # the hidden table's column is kept: the button is in the third one
    assert button["x"] - first["x"] == pytest.approx(2 * (first["width"] + gap), abs=2)
    # as wide as its text, unlike the table filling its column
    assert button["width"] < first["width"] / 2
    # the next row starts below the taller of the views above it, spanning the columns
    assert spanning["y"] - (first["y"] + first["height"]) == pytest.approx(gap, abs=2)
    assert spanning["x"] + spanning["width"] == pytest.approx(1000 - first["x"], abs=1)


def test_a_narrow_grid_view_stacks_its_views_row_by_row(grid_page: Page) -> None:
    page = grid_page
    tables = page.get_by_role("table")
    views = (
        tables.filter(has_text="First"),
        page.get_by_role("button", name="Add"),
        tables.filter(has_text="Spanning"),
    )
    page.set_viewport_size({"width": 500, "height": 600})
    page.goto("/")

    first, button, spanning = (_box(view) for view in views)
    # in order, one above the other, at the column's start, the tables as wide as it
    assert first["y"] + first["height"] < button["y"]
    assert button["y"] + button["height"] < spanning["y"]
    assert button["x"] == pytest.approx(first["x"], abs=1)
    assert spanning["width"] == first["width"]

    page.set_viewport_size({"width": 1000, "height": 600})
    first, button, spanning = (_box(view) for view in views)
    # back in their cells
    assert first["y"] == pytest.approx(button["y"], abs=1)
    assert spanning["width"] > 2 * first["width"]


def test_a_table_row_is_selected_by_click_or_enter_and_keeps_the_focus(
    horizontal_page: Page,
) -> None:
    page = horizontal_page
    page.goto("/")
    north, south = (page.get_by_role("row", name=name) for name in ("North", "South"))

    with _posted(page):
        north.click()
    expect(north).to_have_attribute("aria-current", "true")
    # htmx binds the swapped rows' triggers once the swap has settled
    expect(page.locator(".htmx-added")).to_have_count(0)

    south.focus()
    with _posted(page):
        page.keyboard.press("Enter")
    expect(south).to_have_attribute("aria-current", "true")
    expect(north).not_to_have_attribute("aria-current", "true")
    # the table was swapped back, the row that had the focus keeps it
    expect(south).to_be_focused()


def test_a_double_click_or_f2_edits_a_cell_keeping_what_is_typed_through_a_swap(
    places_page: Page,
) -> None:
    page = places_page
    page.goto("/")
    lake = page.get_by_role("row").filter(has_text="Lake")
    note = lake.get_by_label("Note")
    # a slow network: the double click's own clicks, selecting the row, are answered
    # only once the user has started typing
    held: list[Route] = []

    def hold_selections(route: Route) -> None:
        if "event=select" in (route.request.post_data or ""):
            held.append(route)
        else:
            route.continue_()

    page.route("**/widget/*", hold_selections)
    with _posted(page):
        lake.get_by_text("Calm").dblclick()
    # the field comes focused, its text selected: typing replaces it
    expect(note).to_be_focused()
    note.press_sequentially("Windy")
    with _posted(page):
        for route in held:
            route.continue_()
    page.unroute("**/widget/*")

    # the table came back with the row selected, the field as the user left it
    expect(lake).to_have_attribute("aria-current", "true")
    expect(note).to_have_value("Windy")
    expect(note).to_be_focused()
    # htmx binds the swapped field's trigger once the swap has settled
    expect(page.locator(".htmx-added")).to_have_count(0)
    with _posted(page):
        note.press("Enter")
    expect(note).to_have_count(0)
    expect(lake).to_contain_text("Windy")

    # F2 on the row edits its note too; Escape leaves it as it was
    expect(page.locator(".htmx-added")).to_have_count(0)
    lake.focus()
    with _posted(page):
        page.keyboard.press("F2")
    expect(note).to_be_focused()
    expect(page.locator(".htmx-added")).to_have_count(0)
    note.press_sequentially("Foggy")
    with _posted(page):
        note.press("Escape")
    expect(note).to_have_count(0)
    expect(lake).to_contain_text("Windy")


def test_a_row_clicked_before_the_last_click_is_answered_shows_selected(
    horizontal_page: Page,
) -> None:
    page = horizontal_page
    page.goto("/")
    north, south = (page.get_by_role("row", name=name) for name in ("North", "South"))
    # a slow network: both clicks are posted before either is answered
    held: list[Route] = []

    def hold(route: Route) -> None:
        held.append(route)

    page.route("**/widget/*", hold)
    for row in (north, south):
        with page.expect_request("**/widget/*"):
            row.click()
    # the first answer swaps the table, replacing the row the second click came from
    for route in held:
        with _posted(page):
            route.continue_()
    page.unroute("**/widget/*")

    expect(south).to_have_attribute("aria-current", "true")
    expect(north).not_to_have_attribute("aria-current", "true")


def test_the_language_menu_sets_the_page_s_language_and_title(pipe_page: Page) -> None:
    pipe_page.goto("/")
    html = pipe_page.locator("html")
    expect(html).to_have_attribute("lang", "en")

    pipe_page.get_by_text("Language", exact=True).click()
    with _posted(pipe_page):
        pipe_page.get_by_text("Français", exact=True).click()

    expect(html).to_have_attribute("lang", "fr")
    expect(pipe_page).to_have_title("Formulaire de conduite")
    expect(pipe_page.get_by_role("heading", name="Formulaire de conduite")).to_be_visible()
    expect(pipe_page.get_by_label("Matériau")).to_be_visible()


def test_the_page_follows_tasks_running_in_threads_until_they_end(tasks_page: Page) -> None:
    tasks_page.goto("/")
    with _posted(tasks_page):
        tasks_page.get_by_role("button", name="Run").click()
    # as the click left them: the jobs' results wait for its response to be done
    expect(tasks_page.get_by_role("cell", name="Running")).to_have_count(TASK_COUNT)
    # nothing else is sent: the page asks for what the jobs changed while they run
    expect(tasks_page.get_by_text(f"{TASK_COUNT} of {TASK_COUNT} tasks done")).to_be_visible(
        timeout=10_000
    )
    expect(tasks_page.get_by_role("progressbar")).to_have_attribute("value", str(TASK_COUNT))
    expect(tasks_page.get_by_role("button", name="Run")).to_be_enabled()


def _x_range(page: Page) -> list[float]:
    """Get the x range of the page's one chart."""
    x_range: list[float] = page.evaluate(
        "(() => { const [chart] = charts.values();"
        " return [chart.scales.x.min, chart.scales.x.max]; })()"
    )
    return x_range


def test_a_chart_draws_its_series_with_their_legend(chart_page: Page) -> None:
    chart_page.goto("/")
    chart_page.get_by_role("button", name="Add Curve").click()

    figure = chart_page.locator("figure")
    expect(figure.locator("canvas")).to_have_count(1)
    expect(figure.locator(".u-legend")).to_contain_text("D = 50 mm")
    expect(figure.locator(".u-legend")).to_contain_text("Flow Rate (L/s)")
    expect(figure.get_by_role("img")).to_have_attribute(
        "aria-label", "Pressure Drop: D = 50 mm against Flow Rate (L/s)"
    )


def test_the_chart_script_loads_only_once_a_chart_shows(page: Page, chart_pages_page: Page) -> None:
    page.goto("/")
    expect(page.locator("#app")).to_be_visible()
    assert page.evaluate("typeof uPlot") == "undefined"

    chart_pages_page.goto("/notes")
    chart_pages_page.wait_for_function("typeof uPlot !== 'undefined'")
    # its page hidden: no width to draw at yet
    figure = chart_pages_page.locator("figure")
    expect(figure.locator("canvas")).to_have_count(0)

    chart_pages_page.get_by_role("link", name="Chart").click()

    expect(figure.locator("canvas")).to_have_count(1)
    expect(figure.locator(".u-legend")).to_contain_text("Inlet")


def test_a_swapped_chart_is_destroyed_and_keeps_the_zoom(chart_page: Page) -> None:
    chart_page.goto("/")
    add = chart_page.get_by_role("button", name="Add Curve")
    add.click()
    expect(chart_page.locator(".u-legend")).to_contain_text("D = 50 mm")
    chart_page.evaluate("charts.values().next().value.setScale('x', {min: 0.5, max: 1})")

    chart_page.get_by_label("Diameter (mm)").fill("80")
    with _posted(chart_page):
        add.click()

    expect(chart_page.locator(".u-legend")).to_contain_text("D = 80 mm")
    # one chart, the old one gone with its legend
    expect(chart_page.locator(".uplot")).to_have_count(1)
    expect(chart_page.locator(".u-legend")).to_have_count(1)
    assert chart_page.evaluate("charts.size") == 1
    assert _x_range(chart_page) == [0.5, 1]


def test_the_chart_follows_the_theme(chart_page: Page) -> None:
    chart_page.emulate_media(color_scheme="light")
    chart_page.goto("/")
    chart_page.get_by_role("button", name="Add Curve").click()
    expect(chart_page.locator(".u-legend")).to_contain_text("D = 50 mm")
    chart_page.evaluate("charts.values().next().value.setScale('x', {min: 0.5, max: 1})")
    canvas = chart_page.locator("figure canvas")
    light = canvas.evaluate("canvas => canvas.toDataURL()")

    chart_page.get_by_role("button", name="Theme").click()
    chart_page.get_by_role("button", name="Dark").click()

    assert canvas.evaluate("canvas => canvas.toDataURL()") != light
    expect(chart_page.locator(".uplot")).to_have_count(1)
    assert _x_range(chart_page) == [0.5, 1]  # rebuilt at the same zoom


def test_the_chart_follows_its_element_s_width(chart_page: Page) -> None:
    chart_page.set_viewport_size({"width": 1200, "height": 900})
    chart_page.goto("/")
    canvas = chart_page.locator("figure canvas")
    expect(canvas).to_have_count(1)
    wide = canvas.bounding_box()

    chart_page.set_viewport_size({"width": 600, "height": 900})

    assert wide is not None
    chart_page.wait_for_function(
        "width => document.querySelector('figure canvas').getBoundingClientRect().width < width",
        arg=wide["width"],
    )
    plot = chart_page.locator("[data-chart]").bounding_box()
    narrow = canvas.bounding_box()
    assert plot is not None
    assert narrow is not None
    assert narrow["width"] <= plot["width"]
