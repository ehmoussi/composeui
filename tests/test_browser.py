"""The web backend in a real browser: what only a browser can show.

The HTTP tests in `test_webrenderer.py` check the markup; these check what the page's
scripts and htmx do with it. Opt in with `make browser-test`, which needs the `browser`
dependency group and a Chromium from `uv run --group browser playwright install chromium`;
without them, these tests are skipped.
"""

from __future__ import annotations

import contextlib
import io
import re
import secrets
import socket
import struct
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import pytest

pytest.importorskip("starlette")
pytest.importorskip("playwright.sync_api")

import uvicorn
from playwright.sync_api import Browser, Error, expect, sync_playwright
from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route as StarletteRoute

from composeui.core import chartimage
from composeui.webcore.webapplication import WebApplication
from examples.batman import BatmanMainView
from examples.pipechart import PipeChartMainView
from examples.pipeform import PipeMainView
from examples.taskview import TASK_COUNT, TaskMainView
from examples.webhello import HelloApp, HelloMainView
from tests.bookings import BookingMainView
from tests.buildings import SiteMainView, SitePlanMainView
from tests.charts import ChartPagesMainView
from tests.console import MAX_LINES, RunMainView
from tests.datafiles import DataFileMainView
from tests.dialogs import DialogsMainView
from tests.expander import RecordMainView
from tests.formdialog import PipeMainView as EditedPipeMainView
from tests.grid import GridMainView
from tests.horizontal import ButtonsMainView, HorizontalMainView
from tests.listview import PIPES, PipesMainView
from tests.maps import AutoMapMainView, MapMainView
from tests.markdown import HelpMainView
from tests.pages import PagesMainView, WidePageMainView
from tests.sidebar import SidebarMainView
from tests.splitter import SplitterMainView, VerticalSplitterMainView
from tests.studyfiles import StudyFileMainView, StudyFilesTableMainView
from tests.tables import (
    CellWidgetsMainView,
    DataFilesTableMainView,
    EditableTableMainView,
    MillionRowsMainView,
    SortedRoomsMainView,
)
from tests.tabs import TabsMainView
from tests.vertical import VerticalMainView
from tests.workers import WorkersMainView

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

    from playwright.sync_api import (
        BrowserContext,
        ConsoleMessage,
        FilePayload,
        FloatRect,
        Locator,
        Page,
        Route,
    )
    from starlette.requests import Request

pytestmark = pytest.mark.browser

#: how long the status bar shows a message, kept short so its auto-clear is quick to see
_MESSAGE_TIMEOUT = 0.5


#: the help of the hello app's name
_NAME_HELP = "As you'd like to be greeted"


class _BrowserHelloApp(HelloApp):
    def setup_session(self, main_view: HelloMainView) -> None:
        main_view.status_bar.timeout = _MESSAGE_TIMEOUT
        # the name's field then described by its help and its log, its name still "Name"
        main_view.form.name.help = _NAME_HELP


@contextlib.contextmanager
def _serve(app: Starlette, port: int | None = None) -> Generator[str, None, None]:
    """Serve `app` on `port`, else a free one, while the block runs; yield its base url."""
    if port is None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            # ty misbinds pytest's decorated helpers; the public exception keeps the outcome.
            reason = "the server didn't start"
            raise pytest.fail.Exception(reason)
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
def million_base_url() -> Iterator[str]:
    """Serve an app with a large table of a million rows, for the whole module."""
    app = WebApplication(build_main_view=MillionRowsMainView).create_starlette_app()
    with _serve(app) as url:
        yield url


@pytest.fixture
def million_page(browser: Browser, million_base_url: str) -> Iterator[Page]:
    """Open the app with a large table like `page`, in a session of its own."""
    context = browser.new_context(base_url=million_base_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture(scope="module")
def grid_base_url() -> Iterator[str]:
    """Serve an app with views in a grid, for the whole module."""
    with _serve(WebApplication(build_main_view=GridMainView).create_starlette_app()) as url:
        yield url


class _PlacesApp(WebApplication[EditableTableMainView]):
    """Places whose notes are editable; the status bar names each place the user opens."""

    def __init__(self) -> None:
        super().__init__(build_main_view=EditableTableMainView)

    def setup_session(self, main_view: EditableTableMainView) -> None:
        main_view.status_bar.timeout = 0
        places = main_view.places

        def show_opened(row: int) -> None:
            main_view.status_bar.show_message(f"Opened {places.rows[row][0]}")

        places.row_activated.connect(show_opened)


@pytest.fixture(scope="module")
def run_base_url() -> Iterator[str]:
    """Serve an app writing a run's output to a console, for the whole module."""
    with _serve(WebApplication(build_main_view=RunMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def places_base_url() -> Iterator[str]:
    """Serve an app with a table whose notes are editable, for the whole module."""
    with _serve(_PlacesApp().create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def variables_base_url() -> Iterator[str]:
    """Serve an app with a table of cell widgets, for the whole module."""
    app = WebApplication(build_main_view=CellWidgetsMainView).create_starlette_app()
    with _serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def rooms_base_url() -> Iterator[str]:
    """Serve an app with a table sorted and filtered by every column, for the whole module.

    The notes count the rooms selected: a change to one table brings the other along.
    """

    class RoomsApp(WebApplication[SortedRoomsMainView]):
        def setup_session(self, main_view: SortedRoomsMainView) -> None:
            def count(rows: list[int]) -> None:
                main_view.notes.rows = [[f"{len(rows)} selected"]]

            main_view.rooms.selection_changed.connect(count)

    app = RoomsApp(build_main_view=SortedRoomsMainView).create_starlette_app()
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
def workers_base_url() -> Iterator[str]:
    """Serve an app with a slider, for the whole module."""
    with _serve(WebApplication(build_main_view=WorkersMainView).create_starlette_app()) as url:
        yield url


def _french_booking() -> BookingMainView:
    view = BookingMainView()
    view.set_language("fr")
    return view


@pytest.fixture(scope="module")
def bookings_base_url() -> Iterator[str]:
    """Serve an app with a date input, in French, for the whole module."""
    with _serve(WebApplication(build_main_view=_french_booking).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def data_files_base_url() -> Iterator[str]:
    """Serve an app with a file path field, for the whole module."""
    with _serve(WebApplication(build_main_view=DataFileMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def study_files_base_url() -> Iterator[str]:
    """Serve an app with a file path field listing the server's files, for the whole module."""
    with _serve(WebApplication(build_main_view=StudyFileMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def study_files_table_base_url() -> Iterator[str]:
    """Serve an app whose table's path cells list the server's files, for the whole module."""
    app = WebApplication(build_main_view=StudyFilesTableMainView).create_starlette_app()
    with _serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def data_files_table_base_url() -> Iterator[str]:
    """Serve an app with a table of file paths, for the whole module."""
    app = WebApplication(build_main_view=DataFilesTableMainView).create_starlette_app()
    with _serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def site_base_url() -> Iterator[str]:
    """Serve an app with a tree, for the whole module."""
    with _serve(WebApplication(build_main_view=SiteMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def site_plan_base_url() -> Iterator[str]:
    """Serve an app with a tree beside a plan in a splitter, for the whole module."""
    with _serve(WebApplication(build_main_view=SitePlanMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def records_base_url() -> Iterator[str]:
    """Serve an app with a record's details in an expander, for the whole module."""
    with _serve(WebApplication(build_main_view=RecordMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def splitter_base_url() -> Iterator[str]:
    """Serve an app with a study beside its result in a splitter, for the whole module."""
    with _serve(WebApplication(build_main_view=SplitterMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def vertical_splitter_base_url() -> Iterator[str]:
    """Serve an app with a chart above its table in a splitter, for the whole module."""
    app = WebApplication(build_main_view=VerticalSplitterMainView).create_starlette_app()
    with _serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def sidebar_base_url() -> Iterator[str]:
    """Serve an app with a sidebar beside two pages, for the whole module."""
    with _serve(WebApplication(build_main_view=SidebarMainView).create_starlette_app()) as url:
        yield url


class _PipesApp(WebApplication[PipesMainView]):
    """Pipes listed an expander each, two to start with."""

    def __init__(self) -> None:
        super().__init__(build_main_view=PipesMainView)

    def setup_session(self, main_view: PipesMainView) -> None:
        main_view.pipes.items = PIPES


@pytest.fixture(scope="module")
def pipes_base_url() -> Iterator[str]:
    """Serve an app listing pipes, an expander each, for the whole module."""
    with _serve(_PipesApp().create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def tabs_base_url() -> Iterator[str]:
    """Serve an app with a pipe's details in tabs, for the whole module."""
    with _serve(WebApplication(build_main_view=TabsMainView).create_starlette_app()) as url:
        yield url


@pytest.fixture(scope="module")
def edited_pipe_base_url() -> Iterator[str]:
    """Serve an app editing a pipe in a form dialog, for the whole module."""
    app = WebApplication(build_main_view=EditedPipeMainView).create_starlette_app()
    with _serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Error as error:
            reason = f"no Chromium for Playwright: {error.message.splitlines()[0]}"
            raise pytest.skip.Exception(reason) from error
        yield browser
        browser.close()


@pytest.fixture(autouse=True)
def _no_policy_violation(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail a test whose page did something its policy refused (`headers.py`).

    The browser only reports it, so a script or a style the policy blocks would otherwise
    just quietly not work. A frame refused to another site is the policy at work.
    """
    violations: list[str] = []
    new_context = Browser.new_context

    def record(message: ConsoleMessage) -> None:
        if "Content Security Policy" in message.text and "frame-ancestors" not in message.text:
            violations.append(message.text)

    def checked_context(browser: Browser, **kwargs: Any) -> BrowserContext:
        context = new_context(browser, **kwargs)
        context.on("console", record)
        return context

    monkeypatch.setattr(Browser, "new_context", checked_context)
    yield
    assert violations == []


def test_map_draws_and_keeps_the_viewport_after_swaps(browser: Browser) -> None:
    app = WebApplication(build_main_view=MapMainView).create_starlette_app()
    with _serve(app) as url, browser.new_context(base_url=url) as context:
        page = context.new_page()
        errors: list[str] = []
        requests: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.goto("/")
        region = page.get_by_role("region", name="Pickup locations")
        expect(region.locator("canvas")).to_be_visible()
        expect(region).to_have_attribute("aria-busy", "false")
        image = pytest.importorskip("PIL.Image")
        pixels = image.open(io.BytesIO(region.locator("canvas").screenshot())).convert("RGB")
        red, green, blue = pixels.getpixel((pixels.width // 2, pixels.height // 2))
        assert blue > green > red
        region.locator("canvas").click()
        expect(page.get_by_text("Clicked 40.73, -73.98")).to_be_visible()
        region.focus()
        region.press("+")
        expect(page.get_by_text("Zoom 12")).to_be_visible()
        _moved_map(page, region)
        region.locator("canvas").click()
        expect(page.get_by_text("Clicked 48.86, 2.35")).to_be_visible()
        region.focus()
        region.press("+")
        expect(page.get_by_text("Zoom 13")).to_be_visible()
        page.get_by_role("button", name="Clear points").click()
        expect(page.get_by_text("Points cleared")).to_be_visible()
        region.focus()
        region.press("+")
        expect(page.get_by_text("Zoom 14")).to_be_visible()
        position = page.get_by_text(re.compile("^Zoom 14;"))
        previous = position.inner_text()
        bounds = region.bounding_box()
        assert bounds is not None
        x, y = bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 60, y + 30, steps=5)
        page.mouse.up()
        expect(position).not_to_have_text(previous)
        assert errors == []
        assert all(request.startswith(url) for request in requests)
        assert sum("/static/deckgl.min.js" in request for request in requests) == 1


def test_map_fits_loaded_points_and_resizes_without_pinning_the_viewport(browser: Browser) -> None:
    image = pytest.importorskip("PIL.Image")
    app = WebApplication(build_main_view=AutoMapMainView).create_starlette_app()
    with (
        _serve(app) as url,
        browser.new_context(base_url=url, viewport={"width": 1000, "height": 800}) as context,
    ):
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("/")
        region = page.get_by_role("region", name="Pickup locations")
        canvas = region.locator("canvas")
        expect(canvas).to_be_visible()
        canvas.click()
        expect(page.get_by_text(re.compile(r"Clicked -?0\.00, -?0\.00"))).to_be_visible()
        _moved_map(page, region)
        canvas.click()
        expect(page.get_by_text("Clicked 48.86, 2.35")).to_be_visible()

        def assert_fitted() -> None:
            pixels = image.open(io.BytesIO(canvas.screenshot())).convert("RGB")
            colors = pixels.load()
            dots = [
                (x, y)
                for y in range(pixels.height)
                for x in range(pixels.width)
                if colors[x, y][2] > colors[x, y][1] + 30 and colors[x, y][1] > colors[x, y][0] + 10
            ]
            assert dots
            left = min(x for x, _y in dots)
            right = pixels.width - 1 - max(x for x, _y in dots)
            top = min(y for _x, y in dots)
            bottom = pixels.height - 1 - max(y for _x, y in dots)
            assert min(left, right, top, bottom) >= 28
            assert min(left, right, top, bottom) <= 36

        _eventually(assert_fitted)
        page.set_viewport_size({"width": 420, "height": 800})
        _eventually(assert_fitted)  # once redrawn at its new size
        canvas.click()
        expect(page.get_by_text("Clicked 48.86, 2.35")).to_be_visible()
        region.focus()
        region.press("+")
        position = page.get_by_text(re.compile("^Zoom "))
        expect(position).to_be_visible()
        chosen_zoom = int(position.inner_text().split(";")[0].split()[1])
        page.get_by_role("button", name="Clear points").click()
        expect(page.get_by_text("Points cleared")).to_be_visible()
        canvas.click()
        expect(page.get_by_text("Clicked 48.86, 2.35")).to_be_visible()
        region.focus()
        region.press("+")
        expect(page.get_by_text(f"Zoom {chosen_zoom + 1};")).to_be_visible()
        assert errors == []


def test_map_renders_osm_tiles_with_attribution_and_an_origin_referrer(browser: Browser) -> None:
    image = pytest.importorskip("PIL.Image")
    tile = io.BytesIO()
    image.new("RGB", (256, 256), (80, 160, 80)).save(tile, format="PNG")

    def build_view() -> MapMainView:
        view = MapMainView()
        view.map.tiles = True
        return view

    app = WebApplication(build_main_view=build_view)
    with _serve(app.create_starlette_app()) as url, browser.new_context(base_url=url) as context:
        page = context.new_page()
        errors: list[str] = []
        referrers: list[str | None] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )

        def serve_tile(route: Route) -> None:
            referrers.append(route.request.headers.get("referer"))
            assert "cookie" not in route.request.headers
            route.fulfill(
                content_type="image/png",
                body=tile.getvalue(),
                headers={"Access-Control-Allow-Origin": "*"},
            )

        page.route("https://tile.openstreetmap.org/**", serve_tile)
        page.goto("/")
        region = page.get_by_role("region", name="Pickup locations")
        expect(region).to_have_attribute("aria-busy", "false")
        expect(page.get_by_role("link", name="© OpenStreetMap contributors")).to_be_visible()
        assert errors == []
        pixels = image.open(io.BytesIO(region.locator("canvas").screenshot())).convert("RGB")
        assert pixels.getpixel((10, 10)) == (80, 160, 80)
        assert len(referrers) > 0
        assert set(referrers) == {url + "/"}
        assert errors == []


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
def rooms_page(browser: Browser, rooms_base_url: str) -> Iterator[Page]:
    """Open the app with a sorted, filtered table like `page`, in a session of its own."""
    context = browser.new_context(base_url=rooms_base_url)
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
def variables_page(browser: Browser, variables_base_url: str) -> Iterator[Page]:
    """Open the app with a table of cell widgets like `page`, in a session of its own."""
    context = browser.new_context(base_url=variables_base_url)
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


def _posted(page: Page) -> contextlib.AbstractContextManager[object]:
    """Wait for the page's next widget POST to be answered."""
    return page.expect_response(
        lambda response: response.request.method == "POST" and "/widget/" in response.url
    )


def _intercept_file_choosers(page: Page) -> None:
    """Have Playwright catch the page's file pickers from now on, before one opens.

    `expect_file_chooser` asks for them without waiting for the browser's answer: a picker
    opened right after would be the browser's own, never reported.
    """
    page.on("filechooser", lambda _chooser: None)


def _passes(check: Callable[[], None]) -> bool:
    try:
        check()
    except AssertionError:
        return False
    return True


def _eventually(check: Callable[[], None]) -> None:
    """Run `check` until it passes, as `expect` does: e.g. a canvas once redrawn."""
    deadline = time.monotonic() + 5
    while not _passes(check):
        if time.monotonic() > deadline:
            check()  # its own error, telling what failed
        time.sleep(0.1)


def _moved_map(page: Page, region: Locator) -> None:
    """Move the map with its button, until the page draws it at its new center."""
    with _posted(page):
        page.get_by_role("button", name="Move map").click()
    # a click reads its point on the map as drawn: Paris, once the answer is swapped in
    expect(region).to_have_attribute("data-map", re.compile(r'"latitude":48\.8'))


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


def test_save_downloads_the_state_and_leaves_the_page(page: Page) -> None:
    page.goto("/")
    name = page.get_by_label("Name")
    with _posted(page):
        name.press_sequentially("Alice")

    # Save posts the page's form: the answer is a download, so the page stays
    with page.expect_download() as download_info:
        page.keyboard.press("Alt+Shift+KeyS")

    download = download_info.value
    assert download.suggested_filename.endswith(".hello")
    assert "Alice" in Path(download.path()).read_text()
    expect(name).to_have_value("Alice")


def test_save_right_after_typing_saves_the_value_typed(page: Page) -> None:
    # the field's post, sent as Save takes the focus, held on its way to the server
    page.add_init_script(
        "const send = XMLHttpRequest.prototype.send;"
        "XMLHttpRequest.prototype.send = function (body) {"
        "  if (typeof body === 'string' && body.includes('Alice')) {"
        "    setTimeout(() => send.call(this, body), 500);"
        "  } else {"
        "    send.call(this, body);"
        "  }"
        "};"
    )
    page.goto("/")

    page.get_by_label("Name").fill("Alice")
    with page.expect_download() as download_info:
        page.get_by_role("button", name="Save").click()

    # saved after the field's post, which left first
    assert "Alice" in Path(download_info.value.path()).read_text()


def test_a_reload_server_s_page_reloads_on_its_session_once_the_server_restarts(
    browser: Browser, tmp_path: Path
) -> None:
    app = _BrowserHelloApp()
    key = secrets.token_urlsafe(32)

    def serve(port: int | None = None) -> contextlib.AbstractContextManager[str]:
        # a process of a `--reload` server
        return _serve(app.create_starlette_app(saved_sessions=tmp_path, secret_key=key), port)

    with serve() as base_url:
        context = browser.new_context(base_url=base_url)
        page = context.new_page()
        page.goto("/")
        with _posted(page):
            page.get_by_label("Name").press_sequentially("Bob")
    # stopped, e.g. for a change: the page's asks fail meanwhile, and are asked again
    with serve(urlsplit(base_url).port), page.expect_event("load"):
        pass  # the next process answers an ask: the page reloads by itself

    # the server's page, the session the previous process left
    expect(page.get_by_label("Name")).to_have_value("Bob")
    expect(page.locator("footer")).to_have_text("Hello, Bob!")
    context.close()


def test_a_form_posted_from_another_port_is_refused(page: Page, base_url: str) -> None:
    """Same site (the cookie goes along), not same origin: the server refuses it."""
    page.goto("/")
    post_url = f"{base_url}{page.get_by_label('Name').get_attribute('hx-post')}"
    parts = urlsplit(base_url)
    other = f"http://{parts.hostname}:{(parts.port or 80) + 1}/"
    # a page that only exists in the browser, on another port of the same host
    attack = (
        f'<form method="post" action="{post_url}">'
        '<input name="event" value="input"><input name="value" value="Mallory"></form>'
        "<script>document.forms[0].submit()</script>"
    )
    page.route(other, lambda route: route.fulfill(content_type="text/html", body=attack))

    with page.expect_response(post_url) as response_info:
        page.goto(other)

    assert response_info.value.status == 403
    page.goto(base_url)
    expect(page.get_by_label("Name")).to_have_value("")


def test_another_site_cannot_show_the_app_in_a_frame(page: Page, base_url: str) -> None:
    def framing(_request: Request) -> HTMLResponse:
        return HTMLResponse(f'<iframe src="{base_url}/"></iframe>')

    # a real server: Chromium blocks a frame of a local address in a page without one
    with _serve(Starlette(routes=[StarletteRoute("/", framing)])) as other:
        with page.expect_response(f"{base_url}/") as response_info:
            page.goto(other)

        assert response_info.value.status == 200  # sent, but not shown
        # the browser shows its own error page in the frame, not the app
        (frame,) = page.main_frame.child_frames
        expect(frame.locator("#app")).to_have_count(0)


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


def test_the_help_button_opens_the_help_beside_it_by_click_or_keyboard(page: Page) -> None:
    page.goto("/")
    name = page.get_by_label("Name")
    button = page.get_by_role("button", name="Help")
    help_text = page.get_by_text(_NAME_HELP)
    expect(help_text).to_be_hidden()
    # closed, it still describes the field, before its message
    expect(name).to_have_accessible_description(f"{_NAME_HELP} A name is mandatory")

    button.click()

    expect(help_text).to_be_visible()
    button_box, help_box = button.bounding_box(), help_text.bounding_box()
    assert button_box is not None
    assert help_box is not None
    # right beside it, on its right while there is room, never over it
    assert button_box["x"] + button_box["width"] <= help_box["x"]
    assert help_box["x"] < button_box["x"] + 3 * button_box["width"]
    assert help_box["y"] < button_box["y"] + button_box["height"] / 2
    assert button_box["y"] + button_box["height"] / 2 < help_box["y"] + help_box["height"]
    page.keyboard.press("Escape")
    expect(help_text).to_be_hidden()
    name.focus()
    page.keyboard.press("Shift+Tab")  # the button is just before the field
    expect(button).to_be_focused()
    page.keyboard.press("Enter")
    expect(help_text).to_be_visible()


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
    # the menu closed: the focus it kept open left it
    assert page.evaluate("document.activeElement === document.body")
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


@pytest.fixture
def help_page(browser: Browser) -> Iterator[Page]:
    """Open an app showing a picked Markdown file, in a session of its own."""
    app = WebApplication(build_main_view=HelpMainView).create_starlette_app()
    with _serve(app) as url:
        context = browser.new_context(base_url=url)
        yield context.new_page()
        context.close()


def test_a_picked_file_is_uploaded_and_shown(help_page: Page, tmp_path: Path) -> None:
    page = help_page
    _intercept_file_choosers(page)
    page.goto("/")
    markdown = page.locator(".cui-markdown")
    expect(markdown.get_by_role("heading", name="Help")).to_be_visible()
    notes = tmp_path / "notes.md"
    notes.write_text("# Notes\n\n- a picked file\n", encoding="utf-8")

    # its shortcut opens the browser's picker, which offers Markdown files
    with page.expect_file_chooser() as chooser:
        page.keyboard.press("Alt+Shift+KeyH")  # Ctrl+H, on the web
    with _posted(page):
        chooser.value.set_files(notes)
    expect(markdown.get_by_role("heading", name="Notes")).to_be_visible()
    expect(markdown.get_by_text("a picked file")).to_be_visible()
    # emptied once sent: picking the same file again uploads it again
    picker = page.locator('input[type="file"][accept=".md,.markdown"]')
    expect(picker).to_have_value("")
    notes.write_text("# Notes again\n", encoding="utf-8")
    with _posted(page):
        picker.set_input_files(notes)
    expect(markdown.get_by_role("heading", name="Notes again")).to_be_visible()


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

    # Escape as soon as it shows: it posts all the same
    with _posted(page):
        page.keyboard.press("Alt+Shift+KeyL")
    expect(dialog).to_be_visible()
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


class _BusyDialogsApp(WebApplication[DialogsMainView]):
    """The dialogs app, its dialog disabled: its answer would be ignored."""

    def __init__(self) -> None:
        super().__init__(build_main_view=DialogsMainView)

    def setup_session(self, main_view: DialogsMainView) -> None:
        main_view.confirm_clear.is_enabled = False


def test_escape_leaves_a_disabled_dialog_open(browser: Browser) -> None:
    with _serve(_BusyDialogsApp().create_starlette_app()) as url:
        context = browser.new_context(base_url=url)
        page = context.new_page()
        page.goto("/")
        dialog = page.get_by_role("dialog", name="Clear the name")
        with _posted(page):
            page.keyboard.press("Alt+Shift+KeyL")
        expect(dialog).to_be_visible()

        # the browser refuses only the first `cancel`, then closes it all the same
        for _ in range(3):
            page.keyboard.press("Escape")
            expect(dialog).to_have_js_property("open", value=True)
        expect(dialog).to_be_visible()
        context.close()


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
        # the view's own: the header has a Save button too
        box = page.locator("main").get_by_role("button", name=name).bounding_box()
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


def test_a_sidebar_retracts_beside_the_pages_and_is_a_drawer_on_a_phone(
    browser: Browser, sidebar_base_url: str
) -> None:
    context = browser.new_context(base_url=sidebar_base_url)
    page = context.new_page()
    create = page.get_by_role("button", name="Create")
    toggle = page.get_by_role("button", name="Sidebar")

    page.set_viewport_size({"width": 1200, "height": 600})
    page.goto("/")
    expect(create).to_be_visible()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    submit = page.get_by_role("button", name="Submit")
    assert _box(create)["x"] + _box(create)["width"] < _box(submit)["x"]
    page.get_by_role("link", name="Results").click()
    expect(page.get_by_text("Total: 0")).to_be_visible()
    expect(create).to_be_visible()  # whatever the page

    # retracted by its button, as the server is told: a reload shows it retracted
    with _posted(page):
        toggle.click()
    expect(create).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    page.reload()
    expect(create).to_be_hidden()
    with _posted(page):
        toggle.click()
    expect(create).to_be_visible()
    expect(toggle).to_have_attribute("aria-expanded", "true")

    page.set_viewport_size({"width": 400, "height": 700})
    expect(create).to_be_hidden()
    toggle.click()
    expect(create).to_be_visible()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Escape")
    expect(create).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(toggle).to_be_focused()
    toggle.click()
    expect(create).to_be_visible()
    page.mouse.click(390, 400)  # beside the drawer, on the page it covers
    expect(create).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    context.close()


def test_a_list_view_adds_and_deletes_items_leaving_the_others_alone(
    browser: Browser, pipes_base_url: str
) -> None:
    context = browser.new_context(base_url=pipes_base_url)
    page = context.new_page()
    page.goto("/")
    titles = page.locator("summary")
    expect(titles).to_have_text(["Main line", "Return"])
    with _posted(page):
        page.get_by_text("Main line").click()
    expect(page.get_by_text("Length: 12 m")).to_be_visible()

    with _posted(page):
        page.get_by_role("button", name="Add a pipe").click()
    # put in first, the others as the user left them (the response leaves them out)
    expect(titles).to_have_text(["Feed", "Main line", "Return"])
    expect(page.get_by_text("Length: 12 m")).to_be_visible()

    with _posted(page):
        page.get_by_text("Feed").click()
    expect(page.get_by_text("Length: 1 m")).to_be_visible()
    feed = page.locator("details").filter(has_text="Feed")
    with _posted(page):
        feed.get_by_role("button", name="Delete").click()  # the new item's own
    expect(titles).to_have_text(["Main line", "Return"])
    expect(page.locator("footer")).to_have_text("Deleted Feed")
    context.close()


def test_a_tab_view_shows_the_tab_picked_by_a_click_or_the_arrow_keys(
    browser: Browser, tabs_base_url: str
) -> None:
    context = browser.new_context(base_url=tabs_base_url)
    page = context.new_page()
    page.goto("/")
    details, history, notes = (
        page.get_by_role("tab", name=name) for name in ("Details", "History", "Notes")
    )
    length, created = page.get_by_text("Length: 12 m"), page.get_by_text("Created on Monday")
    expect(details).to_have_attribute("aria-selected", "true")
    expect(length).to_be_visible()
    expect(created).to_be_hidden()

    with _posted(page):
        history.click()
    expect(created).to_be_visible()
    expect(length).to_be_hidden()
    page.reload()  # the server's page: on the tab picked, as the server was told
    expect(history).to_have_attribute("aria-selected", "true")
    expect(created).to_be_visible()

    history.focus()
    with _posted(page):
        page.keyboard.press("ArrowRight")
    expect(notes).to_be_focused()
    expect(page.get_by_text("Insulated in 2024")).to_be_visible()
    with _posted(page):
        page.keyboard.press("ArrowRight")  # past the last tab, the first
    expect(details).to_be_focused()
    expect(details).to_have_attribute("aria-selected", "true")
    expect(length).to_be_visible()
    page.reload()
    expect(length).to_be_visible()
    context.close()


def test_a_form_dialog_s_ok_follows_its_form_as_the_user_types(
    browser: Browser, edited_pipe_base_url: str
) -> None:
    context = browser.new_context(base_url=edited_pipe_base_url)
    page = context.new_page()
    page.goto("/")
    dialog = page.get_by_role("dialog", name="Edit the pipe")
    name = dialog.get_by_label("Name")
    ok = dialog.get_by_role("button", name="OK")

    with _posted(page):
        page.get_by_role("button", name="Edit").click()
    expect(dialog).to_be_visible()
    expect(name).to_have_value("Main line")
    expect(ok).to_be_enabled()

    with _posted(page):
        name.fill("")  # answered before the next edit, whose answer the next block waits for
    with _posted(page):
        name.press_sequentially("R")  # a debounced edit at a time
    with _posted(page):
        name.press("Backspace")
    expect(ok).to_be_disabled()
    expect(dialog).to_be_visible()  # left open as the user has it
    with _posted(page):
        name.press_sequentially("Return")
    expect(ok).to_be_enabled()
    expect(name).to_have_value("Return")
    with _posted(page):
        ok.click()
    expect(dialog).to_be_hidden()
    expect(page.get_by_text("Return, 12 m")).to_be_visible()

    with _posted(page):
        page.get_by_role("button", name="Edit").click()
    expect(dialog).to_be_visible()
    with _posted(page):
        page.keyboard.press("Escape")  # Cancel
    expect(dialog).to_be_hidden()
    expect(page.get_by_text("Return, 12 m")).to_be_visible()
    context.close()


def test_an_expander_tells_the_server_it_was_opened_or_closed(
    browser: Browser, records_base_url: str
) -> None:
    context = browser.new_context(base_url=records_base_url)
    page = context.new_page()
    page.goto("/")
    title = page.get_by_text("Pipe A")
    edit = page.get_by_role("button", name="Edit")
    expect(edit).to_be_hidden()

    with _posted(page):
        title.click()
    expect(edit).to_be_visible()
    page.reload()  # the server's page: open, as the server was told
    expect(edit).to_be_visible()

    with _posted(page):
        title.press("Enter")
    expect(edit).to_be_hidden()
    page.reload()
    expect(edit).to_be_hidden()
    context.close()


def test_a_splitter_border_dragged_or_moved_by_keys_shares_the_width_beside_it(
    browser: Browser, splitter_base_url: str
) -> None:
    context = browser.new_context(base_url=splitter_base_url)
    page = context.new_page()
    page.set_viewport_size({"width": 1200, "height": 700})
    page.goto("/")
    panes = page.locator("[data-pane]")
    borders = page.get_by_role("separator", name="Resize the panes")
    expect(panes.nth(0)).to_contain_text("Study 1")
    study, settings, result = (_box(panes.nth(index)) for index in range(3))
    # their shares, 1:1:2, of a page too narrow: the small two held at 12rem, to be read
    assert study["width"] == pytest.approx(192, abs=1)
    assert settings["width"] == pytest.approx(192, abs=1)
    assert result["width"] > study["width"]

    border = _box(borders.last)
    middle = (border["x"] + border["width"] / 2, border["y"] + border["height"] / 2)
    page.mouse.move(*middle)
    page.mouse.down()
    page.mouse.move(middle[0] + 40, middle[1], steps=5)
    with _posted(page):
        page.mouse.up()
    dragged = _box(panes.nth(1))
    assert dragged["width"] == pytest.approx(settings["width"] + 40, abs=1)
    expect(borders.last).to_be_focused()
    with _posted(page):
        borders.last.press("ArrowLeft")
    page.reload()  # the server's page: shared as the server was told
    reloaded = _box(panes.nth(1))
    assert reloaded["width"] == pytest.approx(dragged["width"] - 16, abs=2)

    page.set_viewport_size({"width": 500, "height": 700})  # stacked, without borders
    expect(borders).to_have_count(0)
    expect(panes.nth(1)).to_be_visible()
    assert _box(panes.nth(1))["y"] > _box(panes.first)["y"]
    context.close()


def test_a_vertical_splitter_border_dragged_or_moved_by_keys_shares_the_height(
    browser: Browser, vertical_splitter_base_url: str
) -> None:
    context = browser.new_context(base_url=vertical_splitter_base_url)
    page = context.new_page()
    page.set_viewport_size({"width": 500, "height": 900})  # narrow: still one above the other
    page.goto("/")
    panes = page.locator("[data-pane]")
    border = page.get_by_role("separator", name="Resize the panes")
    chart, table = _box(panes.first), _box(panes.last)
    assert chart["height"] == pytest.approx(2 * table["height"], abs=2)
    assert table["y"] > chart["y"]

    line = _box(border)
    middle = (line["x"] + line["width"] / 2, line["y"] + line["height"] / 2)
    page.mouse.move(*middle)
    page.mouse.down()
    page.mouse.move(middle[0], middle[1] - 80, steps=5)
    with _posted(page):
        page.mouse.up()
    dragged = _box(panes.first)
    assert dragged["height"] == pytest.approx(chart["height"] - 80, abs=1)
    with _posted(page):
        border.press("ArrowDown")
    page.reload()  # the server's page: shared as the server was told
    # the server keeps whole percents: within half of one, of 488px
    assert _box(panes.first)["height"] == pytest.approx(dragged["height"] + 16, abs=3)
    context.close()


def test_a_slider_shows_its_value_beside_the_track_as_tall_as_a_text_field(
    browser: Browser, workers_base_url: str
) -> None:
    context = browser.new_context(base_url=workers_base_url)
    page = context.new_page()
    page.goto("/")
    slider = page.get_by_role("slider", name="Workers")
    value = page.locator("output")
    expect(value).to_have_text("5")
    field, track, shown = _box(page.get_by_label("Retries")), _box(slider), _box(value)
    # the slider's row as tall as the text field's: its track centered where the text is
    assert _box(slider.locator(".."))["height"] == field["height"]
    assert track["y"] + track["height"] / 2 == pytest.approx(
        shown["y"] + shown["height"] / 2, abs=1
    )
    assert shown["x"] >= track["x"] + track["width"]  # on the track's right

    with _posted(page):
        slider.press("End")
    expect(value).to_have_text("14")
    assert _box(value) == shown  # its slot as wide whatever the value: the track keeps its length
    expect(slider).to_be_focused()  # never swapped back
    context.close()


def test_a_console_keeps_its_last_lines_at_its_end_unless_the_user_scrolled_up(
    browser: Browser, run_base_url: str
) -> None:
    context = browser.new_context(base_url=run_base_url)
    page = context.new_page()
    page.goto("/")
    console = page.locator("pre")
    run = page.get_by_role("button", name="Run")

    def is_at_end() -> bool:
        return bool(
            console.evaluate("box => box.scrollTop + box.clientHeight >= box.scrollHeight - 1")
        )

    with _posted(page):
        run.click()
    expect(console).to_contain_text("Step 30")
    page.wait_for_function(
        "box => box.scrollTop + box.clientHeight >= box.scrollHeight - 1",
        arg=console.element_handle(),
    )
    # the user scrolls up to read: the next run, its oldest lines dropped, leaves it there
    console.hover()
    page.mouse.wheel(0, -10_000)
    expect(console).to_have_attribute("data-scrolled-up", "true")
    with _posted(page):
        run.click()
    # dropped in the pass that would have scrolled
    expect(console.locator("span")).to_have_count(MAX_LINES + 1)
    expect(console).to_contain_text("Step 60")
    expect(console).not_to_contain_text("Ready")
    assert not is_at_end()
    # back at the end: it follows the lines again
    console.hover()  # the click on Run moved the mouse
    page.mouse.wheel(0, 10_000)
    expect(console).to_have_attribute("data-scrolled-up", "false")
    with _posted(page):
        run.click()
    expect(console).to_contain_text("Step 90")
    assert is_at_end()
    context.close()


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


def test_a_date_input_s_calendar_names_its_days_in_the_page_s_language_and_picks_one(
    browser: Browser, bookings_base_url: str
) -> None:
    context = browser.new_context(base_url=bookings_base_url)
    page = context.new_page()
    page.goto("/")
    field = page.get_by_label("Arrival")
    expect(field).to_have_value("18/10/2026")
    button = page.get_by_role("button", name="Choisir une date")
    calendar = page.locator("calendar-date")

    button.click()
    expect(calendar).to_be_visible()
    with _posted(page):
        # its days named in the page's language, French, not the browser's
        calendar.get_by_role("button", name="25 octobre").click()
    expect(field).to_have_value("25/10/2026")
    expect(calendar).to_be_hidden()
    expect(button).to_be_focused()  # back where it was, through the field's swap

    button.press("Enter")
    # opened on the date, focused, so the arrows move from it
    expect(calendar.get_by_role("button", name="25 octobre")).to_be_focused()
    page.keyboard.press("ArrowRight")
    expect(calendar.get_by_role("button", name="26 octobre")).to_be_focused()
    with _posted(page):
        page.keyboard.press("Enter")
    expect(field).to_have_value("26/10/2026")
    button.press("Enter")
    expect(calendar.get_by_role("button", name="26 octobre")).to_be_focused()
    page.keyboard.press("ArrowRight")
    expect(calendar.get_by_role("button", name="27 octobre")).to_be_focused()
    page.keyboard.press("Escape")  # closed, nothing picked
    expect(calendar).to_be_hidden()
    expect(field).to_have_value("26/10/2026")
    context.close()


def test_a_date_input_s_calendar_opened_before_cally_loads_ends_up_focused_in_its_language(
    browser: Browser, bookings_base_url: str
) -> None:
    context = browser.new_context(base_url=bookings_base_url)
    page = context.new_page()
    held: list[Route] = []

    def hold(route: Route) -> None:
        held.append(route)  # answered only once the calendar is open

    # Cally held back, as on a slow network
    page.route("**/static/cally.js*", hold)
    page.goto("/", wait_until="domcontentloaded")  # not the load, which waits for Cally
    button = page.get_by_role("button", name="Choisir une date")
    button.click()
    calendar = page.locator("calendar-date")
    expect(calendar).to_be_visible()
    assert page.evaluate("customElements.get('calendar-date') === undefined")

    held[0].continue_()
    # once loaded, as a calendar opened then: on the date, focused, named in French
    expect(calendar.get_by_role("button", name="18 octobre")).to_be_focused()
    context.close()


def test_a_file_picked_in_the_browser_s_picker_is_uploaded_its_copy_s_path_shown(
    browser: Browser, data_files_base_url: str
) -> None:
    context = browser.new_context(base_url=data_files_base_url)
    page = context.new_page()
    _intercept_file_choosers(page)
    page.goto("/")
    field = page.get_by_label("Measurements")
    with page.expect_file_chooser() as chooser, _posted(page):
        page.get_by_role("button", name="Choose a file").click()
        payload: FilePayload = {"name": "flows.csv", "mimeType": "text/csv", "buffer": b"1,2"}
        chooser.value.set_files(files=[payload])
    expect(field).to_have_value(re.compile(r"flows\.csv$"))
    context.close()


def test_a_file_of_the_server_is_picked_in_the_list_its_folders_open_in_place(
    browser: Browser, study_files_base_url: str
) -> None:
    context = browser.new_context(base_url=study_files_base_url)
    page = context.new_page()
    page.goto("/")
    field = page.get_by_label("Study")
    browse = page.get_by_role("button", name="Choose a file")
    with _posted(page):
        browse.click()
    files = page.get_by_role("dialog", name="Choose a file")
    expect(files).to_be_visible()

    # a folder shows its files in the dialog, swapped open again, the focus in it
    with _posted(page):
        files.get_by_role("button", name="locales").click()
    parent = files.get_by_role("button", name="Parent folder")
    expect(parent).to_be_visible()
    expect(files.locator(":focus")).to_have_count(1)
    with _posted(page):
        parent.click()
    with _posted(page):
        files.get_by_role("button", name="studyfiles.py").click()

    expect(files).to_have_count(0)
    expect(field).to_have_value(re.compile(r"studyfiles\.py$"))
    expect(browse).to_be_focused()  # back where it was
    with _posted(page):
        browse.click()
    expect(files).to_be_visible()
    with _posted(page):
        page.keyboard.press("Escape")
    expect(files).to_have_count(0)
    context.close()


def test_a_folder_of_the_server_is_chosen_in_the_list_its_button_focused_again(
    browser: Browser, study_files_base_url: str
) -> None:
    context = browser.new_context(base_url=study_files_base_url)
    page = context.new_page()
    page.goto("/")
    results = page.get_by_label("Results")
    browse = page.get_by_role("button", name="Choose a folder")
    expect(browse).to_have_count(1)  # Scratch, without roots, has none: it's typed
    with _posted(page):
        browse.click()
    folders = page.get_by_role("dialog", name="Choose a folder")
    with _posted(page):
        folders.get_by_role("button", name="locales").click()
    expect(folders.get_by_role("button", name="Parent folder")).to_be_focused()

    with _posted(page):
        folders.get_by_role("button", name="Choose this folder").click()

    expect(folders).to_have_count(0)
    expect(results).to_have_value(re.compile(r"locales$"))
    expect(browse).to_be_focused()
    context.close()


def test_a_path_to_save_to_is_picked_with_the_name_typed_a_file_replaced_once_agreed(
    browser: Browser, study_files_base_url: str
) -> None:
    context = browser.new_context(base_url=study_files_base_url)
    page = context.new_page()
    page.goto("/")
    report = page.get_by_label("Report")
    browse = page.get_by_role("button", name="Save as")
    with _posted(page):
        browse.click()
    files = page.get_by_role("dialog", name="Save as")
    name = files.get_by_label("File name")

    # a new file: Enter saves it, its extension added, the "…" button focused again
    name.fill("summary")
    with _posted(page):
        name.press("Enter")
    expect(files).to_have_count(0)
    expect(report).to_have_value(re.compile(r"summary\.py$"))
    expect(browse).to_be_focused()
    # a file that exists: replaced once the user agrees
    with _posted(page):
        browse.click()
    with _posted(page):
        files.get_by_role("button", name="studyfiles.py").click()
    expect(name).to_have_value("studyfiles.py")
    with _posted(page):
        files.get_by_role("button", name="Save", exact=True).click()
    expect(files.get_by_role("alert")).to_contain_text("studyfiles.py already exists")
    with _posted(page):
        files.get_by_role("button", name="Replace").click()
    expect(files).to_have_count(0)
    expect(report).to_have_value(re.compile(r"studyfiles\.py$"))
    context.close()


def test_a_file_of_the_server_is_picked_for_a_table_s_cell_its_button_focused_again(
    browser: Browser, study_files_table_base_url: str
) -> None:
    context = browser.new_context(base_url=study_files_table_base_url)
    page = context.new_page()
    page.goto("/")
    commands = page.get_by_role("row").filter(has_text="Commands")
    with _posted(page):
        commands.get_by_role("button", name="File: Choose a file").click()
    files = page.get_by_role("dialog", name="Choose a file")
    expect(files).to_be_visible()

    with _posted(page):
        files.get_by_role("button", name="studyfiles.py").click()

    expect(files).to_have_count(0)
    # the row picked for, not another, shows the path
    expect(commands).to_contain_text(re.compile(r"studyfiles\.py"))
    expect(page.get_by_role("row").filter(has_text="Mesh")).not_to_contain_text("studyfiles")
    expect(commands.get_by_role("button", name="File: Choose a file")).to_be_focused()
    context.close()


def test_a_file_picked_by_a_table_cell_s_button_is_uploaded_its_copy_s_path_shown(
    browser: Browser, data_files_table_base_url: str
) -> None:
    context = browser.new_context(base_url=data_files_table_base_url)
    page = context.new_page()
    _intercept_file_choosers(page)
    page.goto("/")
    levels = page.get_by_role("row").filter(has_text="Levels")
    with page.expect_file_chooser() as chooser, _posted(page):
        levels.get_by_role("button", name="File: Choose a file").click()
        payload: FilePayload = {"name": "levels.csv", "mimeType": "text/csv", "buffer": b"3"}
        chooser.value.set_files(files=[payload])
    # the row picked, not another, shows the copy's path
    expect(levels).to_contain_text(re.compile(r"levels\.csv"))
    expect(page.get_by_role("row").filter(has_text="Flows")).not_to_contain_text("levels")
    context.close()


def test_a_tree_node_keeps_the_focus_through_the_swap_its_toggle_or_selection_brings(
    browser: Browser, site_base_url: str
) -> None:
    context = browser.new_context(base_url=site_base_url)
    page = context.new_page()
    page.goto("/")
    toggle = page.get_by_role("button", name="Building B", expanded=False)
    lobby = page.get_by_role("button", name="Lobby")
    expect(lobby).to_have_count(0)  # collapsed

    toggle.focus()
    with _posted(page):
        page.keyboard.press("Enter")
    expanded = page.get_by_role("button", name="Building B", expanded=True)
    expect(expanded).to_be_focused()
    expect(page.locator(".htmx-added")).to_have_count(0)

    # past the node's own button and its child's arrow, onto its child, then selected
    for _ in range(3):
        page.keyboard.press("Tab")
    with _posted(page):
        page.keyboard.press("Enter")
    selected = page.locator("[aria-current=true]")
    expect(selected).to_have_text("Floor 1")
    expect(selected).to_be_focused()
    context.close()


def test_a_splitter_keeps_each_pane_wide_enough_to_read_a_tree_cutting_its_labels_short(
    browser: Browser, site_plan_base_url: str
) -> None:
    context = browser.new_context(base_url=site_plan_base_url)
    page = context.new_page()
    page.set_viewport_size({"width": 1200, "height": 700})
    page.goto("/")
    tree, plan = page.locator("[data-pane]").first, page.locator("[data-pane]").last
    border = page.get_by_role("separator", name="Resize the panes")
    park = page.get_by_role("button", name="Underground car park, level 2")
    expect(park).to_be_visible()

    def drag_border_to(x: float) -> None:
        line = _box(border)
        middle = (line["x"] + line["width"] / 2, line["y"] + line["height"] / 2)
        page.mouse.move(*middle)
        page.mouse.down()
        page.mouse.move(x, middle[1], steps=5)
        with _posted(page):
            page.mouse.up()

    drag_border_to(0)  # as far as the tree's pane lets it: 12rem
    assert _box(tree)["width"] == pytest.approx(192, abs=1)
    # the label ends in an ellipsis, its mark whole inside the pane
    label = park.get_by_text("Underground car park, level 2")
    assert label.evaluate("label => label.scrollWidth > label.clientWidth")
    mark = _box(park.locator("svg"))
    assert mark["x"] + mark["width"] <= _box(tree)["x"] + _box(tree)["width"]

    drag_border_to(1200)  # and the plan's, on the other side
    assert _box(plan)["width"] == pytest.approx(192, abs=1)
    assert not label.evaluate("label => label.scrollWidth > label.clientWidth")
    context.close()


def test_a_table_s_cell_widgets_change_their_cells_without_selecting_their_row(
    variables_page: Page,
) -> None:
    page = variables_page
    page.goto("/")
    keep_all = page.get_by_role("columnheader").get_by_label("Keep")
    stress = page.get_by_role("row").filter(has_text="Stress")
    length = page.get_by_role("row").filter(has_text="Length")
    # some rows checked: the header's box is partly checked
    expect(keep_all).to_have_js_property("indeterminate", value=True)

    with _posted(page):
        stress.get_by_label("Keep").check()
    expect(keep_all).to_be_checked()
    expect(keep_all).to_have_js_property("indeterminate", value=False)
    with _posted(page):
        length.get_by_label("Role").select_option("Output")
    with _posted(page):
        stress.get_by_role("button", name="Distribution: \u2026").click()
    with _posted(page):
        length.get_by_role("button", name="doc").click()
    # the widgets took their clicks: no row is selected
    expect(page.locator("tr[aria-current]")).to_have_count(0)
    expect(length.get_by_label("Role")).to_have_value("Output")

    # the header's box unchecks every row, keeping the focus
    with _posted(page):
        keep_all.uncheck()
    boxes = page.get_by_role("cell").get_by_label("Keep")
    expect(boxes).to_have_count(2)
    for box in boxes.all():
        expect(box).not_to_be_checked()
    expect(keep_all).to_be_focused()


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


def test_a_double_click_or_enter_opens_a_table_row_once_selected_unless_it_edits(
    places_page: Page,
) -> None:
    page = places_page
    page.goto("/")
    lake, harbour = (page.get_by_role("row").filter(has_text=name) for name in ("Lake", "Harbour"))
    status_bar = page.locator("footer")

    with _posted(page):
        lake.get_by_text("Lake").dblclick()
    expect(status_bar).to_have_text("Opened Lake")
    expect(lake).to_have_attribute("aria-current", "true")
    expect(page.locator(".htmx-added")).to_have_count(0)

    harbour.focus()
    with _posted(page):
        page.keyboard.press("Enter")
    expect(status_bar).to_have_text("Opened Harbour")
    expect(harbour).to_have_attribute("aria-current", "true")
    expect(page.locator(".htmx-added")).to_have_count(0)

    # a double click on a note edits it, and Enter in its field opens nothing
    with _posted(page):
        lake.get_by_text("Calm").dblclick()
    note = lake.get_by_label("Note")
    expect(note).to_be_focused()
    with _posted(page):
        note.press("Enter")
    expect(note).to_have_count(0)
    expect(status_bar).to_have_text("Opened Harbour")


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
    expect(tasks_page.get_by_role("progressbar")).to_have_attribute(
        "value", str(TASK_COUNT), timeout=10_000
    )
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
        "aria-label", "Pressure Drop: D = 50 mm against Flow Rate (L/s); Pump: 20 kPa"
    )


def test_the_chart_script_loads_only_once_a_chart_shows(page: Page, chart_pages_page: Page) -> None:
    page.goto("/")
    expect(page.locator("#app")).to_be_visible()
    assert page.evaluate("typeof uPlot") == "undefined"

    chart_pages_page.goto("/notes")
    chart_pages_page.wait_for_function("typeof uPlot !== 'undefined'")
    # its page hidden: no width to draw at yet
    figure = chart_pages_page.locator("figure").filter(has_text="Pressure")
    expect(figure.locator("canvas")).to_have_count(0)

    chart_pages_page.get_by_role("link", name="Chart").click()

    expect(figure.locator("canvas")).to_have_count(1)
    expect(figure.locator(".u-legend")).to_contain_text("Inlet")


def test_a_click_sees_the_value_typed_before_it_though_it_reaches_the_server_first(
    chart_page: Page,
) -> None:
    # the field's post, sent as the click takes the focus, held on its way to the server
    chart_page.add_init_script(
        "const send = XMLHttpRequest.prototype.send;"
        "XMLHttpRequest.prototype.send = function (body) {"
        "  if (typeof body === 'string' && body.includes('80')) {"
        "    setTimeout(() => send.call(this, body), 500);"
        "  } else {"
        "    send.call(this, body);"
        "  }"
        "};"
    )
    chart_page.goto("/")

    chart_page.get_by_label("Diameter (mm)").fill("80")
    chart_page.get_by_role("button", name="Add Curve").click()

    # handled after the field's post, which left first: the curve of the new diameter
    expect(chart_page.locator(".u-legend")).to_contain_text("D = 80 mm")


def test_a_swapped_chart_is_destroyed_and_keeps_the_zoom(chart_page: Page) -> None:
    chart_page.goto("/")
    add = chart_page.get_by_role("button", name="Add Curve")
    add.click()
    expect(chart_page.locator(".u-legend")).to_contain_text("D = 50 mm")
    chart_page.evaluate("charts.values().next().value.setScale('x', {min: 0.5, max: 1})")

    # the server has the new diameter before the click: the two would else race
    with _posted(chart_page):
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


def test_measurements_are_drawn_as_dots_over_the_curve(chart_page: Page) -> None:
    chart_page.goto("/")
    chart_page.get_by_role("button", name="Add Curve").click()
    expect(chart_page.locator(".u-legend")).to_contain_text("D = 50 mm")

    chart_page.get_by_role("button", name="Add Measurements").click()

    expect(chart_page.locator(".u-legend")).to_contain_text("Measured, D = 50 mm")
    # whether uPlot draws each series' points, and its line
    drawn = chart_page.evaluate(
        "(() => { const chart = charts.values().next().value;"
        " return chart.series.slice(1).map((series, index) =>"
        " [series.points.show(chart, index + 1), series.paths(chart, index + 1, 0, 1) !== null]);"
        " })()"
    )
    assert drawn == [[False, True], [True, False]]


def test_a_bar_chart_draws_its_bars_by_category(chart_pages_page: Page) -> None:
    chart_pages_page.goto("/chart")
    energy = chart_pages_page.locator("figure").filter(has_text="Energy")
    expect(energy.locator("canvas")).to_have_count(1)
    expect(energy.locator(".u-legend")).to_contain_text("Cooling")

    box = energy.locator(".u-over").bounding_box()
    assert box is not None
    # the middle of the bedroom's group: its heating bar, and no cooling
    chart_pages_page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    legend = energy.locator(".u-legend")
    expect(legend).to_contain_text("Bedroom")
    expect(legend).to_contain_text("80 kWh")  # a whole number, as it is: not 80.00


def test_a_log_axis_draws_on_a_log_scale(chart_pages_page: Page) -> None:
    chart_pages_page.goto("/chart")
    decay = chart_pages_page.locator("figure").filter(has_text="Decay")
    expect(decay.locator("canvas")).to_have_count(1)

    scales = decay.locator("[data-chart]").evaluate(
        "element => { const chart = charts.get(element);"
        " return [chart.scales.x.distr, chart.scales.y.distr, chart.scales.x.min > 0]; }"
    )

    assert scales == [3, 3, True]  # uPlot's log scales, from above 0


def _is_near(pixel: str, color: tuple[int, int, int]) -> bool:
    """Whether a canvas' pixel, as "r,g,b", is about `color`."""
    return all(
        abs(int(channel) - expected) <= 16 for channel, expected in zip(pixel.split(","), color)
    )


def test_reference_lines_are_drawn_in_their_styles_in_range(chart_pages_page: Page) -> None:
    chart_pages_page.goto("/chart")
    pressure = chart_pages_page.locator("figure").filter(has_text="Pressure")
    expect(pressure.locator("canvas")).to_have_count(1)

    # the y range, past the data to the lines' 4.6 and 0.6; then the pixels along their rows
    y_range, solid, dotted = pressure.locator("[data-chart]").evaluate(
        "element => { const chart = charts.get(element); const box = chart.bbox;"
        " const row = value => {"
        "   const y = Math.round(chart.valToPos(value, 'y', true));"
        "   const pixels = chart.ctx.getImageData(box.left, y, box.width, 1).data;"
        "   const colors = [];"
        "   for (let i = 0; i < pixels.length; i += 4) colors.push(pixels.slice(i, i + 3).join());"
        "   return colors; };"
        " return [[chart.scales.y.min, chart.scales.y.max], row(4.6), row(0.6)]; }"
    )

    assert y_range[0] <= 0.6
    assert y_range[1] >= 4.6
    # its color, though blended where a line crosses it
    assert all(_is_near(pixel, (208, 48, 48)) for pixel in solid)
    green = [_is_near(pixel, (32, 128, 64)) for pixel in dotted]
    assert any(green)
    assert not all(green)  # dotted


def test_a_step_series_holds_each_value_until_the_next_point(chart_pages_page: Page) -> None:
    chart_pages_page.goto("/chart")
    jobs = chart_pages_page.locator("figure").filter(has_text="Jobs")
    expect(jobs.locator("canvas")).to_have_count(1)
    plot = jobs.locator("[data-chart]")
    # the fill at 3.5 h: under 3 running, held from 2 h to 5 h; a line would be at 2.5
    held, under = plot.evaluate(
        "element => { const chart = charts.get(element);"
        " const pixel = (x, y) => chart.ctx.getImageData("
        "   Math.round(chart.valToPos(x, 'x', true)), Math.round(chart.valToPos(y, 'y', true)),"
        "   1, 1).data.join();"
        " return [pixel(3.5, 2.8), pixel(3.5, 1.8)]; }"
    )
    assert held == under

    x = plot.evaluate("element => charts.get(element).valToPos(4.8, 'x')")
    jobs.locator(".u-over").hover(position={"x": x, "y": 10})

    # the values held at 4.8 h, rather than those of the points nearest it, at 5 h
    legend = jobs.locator(".u-legend")
    # a count, as it is; a series not all whole keeps its trailing zeros
    expect(legend.locator(".u-series").filter(has_text="Running").locator(".u-value")).to_have_text(
        "3"
    )
    expect(legend.locator(".u-series").filter(has_text="Queued").locator(".u-value")).to_have_text(
        "1.000"
    )


def test_the_image_link_follows_the_zoom_and_the_format(chart_page: Page) -> None:
    pytest.importorskip("matplotlib")
    chart_page.goto("/")
    chart_page.get_by_role("button", name="Add Curve").click()
    expect(chart_page.locator(".u-legend")).to_contain_text("D = 50 mm")
    link = chart_page.get_by_role("link", name="Save Image")
    expect(link).to_have_attribute("href", re.compile(r"/image\?format=pdf$"))

    chart_page.evaluate("charts.values().next().value.setScale('x', {min: 0.5, max: 1})")
    chart_page.get_by_label("Image format").select_option("svg")

    expect(link).to_have_attribute("href", re.compile(r"\?format=svg&x_min=0\.5&x_max=1&y_min="))
    with chart_page.expect_download() as download_info:
        link.click()
    download = download_info.value
    assert download.suggested_filename == "Pressure Drop.svg"
    assert "Flow Rate (L/s)" in Path(download.path()).read_text()


def test_without_matplotlib_the_page_draws_a_light_png(
    chart_page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chartimage, "is_available", lambda: False)
    chart_page.emulate_media(color_scheme="dark")
    chart_page.goto("/")
    chart_page.get_by_role("button", name="Add Curve").click()
    expect(chart_page.locator(".u-legend")).to_contain_text("D = 50 mm")
    expect(chart_page.get_by_label("Image format")).to_have_count(0)

    with chart_page.expect_download() as download_info:
        chart_page.get_by_role("button", name="Save Image (PNG)").click()

    download = download_info.value
    assert download.suggested_filename == "Pressure Drop.png"
    content = Path(download.path()).read_bytes()
    assert struct.unpack(">II", content[16:24]) == (1600, 1000)
    # its corner's pixel: white, the light theme's, under the page's dark one
    corner = chart_page.evaluate(
        """async (bytes) => {
            const image = await createImageBitmap(new Blob([new Uint8Array(bytes)]));
            const canvas = new OffscreenCanvas(image.width, image.height);
            const context = canvas.getContext("2d");
            context.drawImage(image, 0, 0);
            return Array.from(context.getImageData(2, 2, 1, 1).data);
        }""",
        list(content),
    )
    assert corner == [255, 255, 255, 255]
    # the off-screen chart is gone
    expect(chart_page.locator("[data-chart-stage]")).to_have_count(0)
    expect(chart_page.locator(".uplot")).to_have_count(1)


@pytest.fixture(scope="module")
def batman_base_url() -> Iterator[str]:
    """Serve the batman example, for the whole module."""
    with _serve(WebApplication(build_main_view=BatmanMainView).create_starlette_app()) as url:
        yield url


def test_a_click_on_the_chart_reaches_the_app(browser: Browser, batman_base_url: str) -> None:
    context = browser.new_context(base_url=batman_base_url)
    page = context.new_page()
    page.goto("/")
    over = page.locator(".u-over")
    expect(over).to_have_count(1)
    point = page.evaluate(
        "(() => { const chart = charts.values().next().value;"
        " return [chart.valToPos(0, 'x'), chart.valToPos(0, 'y')]; })()"
    )

    with _posted(page):
        over.click(position={"x": point[0], "y": point[1]})
    expect(page.get_by_text("I'm Batman")).to_be_visible()

    # dragging zooms, and posts no click
    box = over.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + 10, box["y"] + 10)
    page.mouse.down()
    page.mouse.move(box["x"] + 200, box["y"] + 10, steps=5)
    page.mouse.up()
    page.wait_for_timeout(300)
    expect(page.get_by_text("I'm Batman")).to_be_visible()
    context.close()


def test_the_legend_stays_put_while_the_cursor_moves(chart_page: Page) -> None:
    chart_page.goto("/")
    chart_page.get_by_role("button", name="Add Curve").click()
    chart_page.get_by_role("button", name="Add Measurements").click()
    legend = chart_page.locator(".u-legend")
    expect(legend).to_contain_text("Measured, D = 50 mm")
    box = chart_page.locator(".u-over").bounding_box()
    assert box is not None

    def hover(share: float) -> list[float]:
        """Hover the plot at `share` of its width; get where each legend entry starts."""
        chart_page.mouse.move(box["x"] + box["width"] * share, box["y"] + box["height"] / 2)
        chart_page.wait_for_timeout(50)
        lefts: list[float] = legend.locator(".u-series").evaluate_all(
            "rows => rows.map(row => row.getBoundingClientRect().left)"
        )
        return lefts

    # values of fewer and more digits, and none (a measurement's x not under the cursor)
    shares = (0.02, 0.5, 0.97)
    for share in shares:
        hover(share)
    first = [hover(share) for share in shares]
    again = [hover(share) for share in shares]

    assert first[0] == first[1] == first[2] == again[0]
    # trailing zeros kept: the same digits wherever the cursor is
    expect(legend).to_contain_text(re.compile(r"\d\.\d{3} L/s|\d{2}\.\d{2} L/s"))


def test_the_plot_is_drawn_as_tall_as_the_chart_s_height(
    browser: Browser, batman_base_url: str
) -> None:
    context = browser.new_context(base_url=batman_base_url)
    page = context.new_page()
    page.goto("/")

    canvas = page.locator("figure canvas")
    expect(canvas).to_have_count(1)
    # the plot's element, its axes in it with the canvas
    box = page.locator("[data-chart]").bounding_box()
    assert box is not None
    assert box["height"] == 420
    context.close()


def test_typing_in_a_table_s_search_keeps_the_caret_while_its_rows_update(
    rooms_page: Page,
) -> None:
    page = rooms_page
    page.goto("/")
    search = page.get_by_label("Search")
    with _posted(page):
        search.press_sequentially("Bdroom")
    expect(page.get_by_text("No rows match the filters")).to_be_visible()
    search.press("Home")
    search.press("ArrowRight")
    with _posted(page):
        search.press("e")
    expect(page.get_by_role("row").filter(has_text="Bedroom")).to_have_count(1)
    expect(page.get_by_role("row").filter(has_text="Hall")).to_have_count(0)
    expect(page.get_by_text("1 of 4")).to_be_visible()
    expect(search).to_have_value("Bedroom")
    expect(search).to_be_focused()
    expect(search).to_have_js_property("selectionStart", 2)


def test_the_filter_editor_marks_a_value_it_can_t_take_and_focuses_the_chip_it_adds(
    rooms_page: Page,
) -> None:
    page = rooms_page
    page.goto("/")
    add_filter = page.get_by_role("button", name="+ Filter")
    with _posted(page):
        add_filter.click()
    value = page.get_by_label("Value")
    expect(value).to_be_focused()
    # the hint follows the column picked
    page.get_by_label("Column").select_option(label="Temperature")
    expect(value).to_have_attribute("placeholder", ">=20, 18..24")

    # The swapped form must have its htmx submit handler before Enter submits it.
    expect(page.locator(".htmx-added")).to_have_count(0)
    with _posted(page):
        value.press_sequentially("warm")
        value.press("Enter")
    expect(page.get_by_text('"warm" isn\'t a number')).to_be_visible()
    expect(value).to_have_attribute("aria-invalid", "true")
    expect(value).to_be_focused()

    value.fill("")
    with _posted(page):
        value.press_sequentially(">=20")
        value.press("Enter")
    chip = page.get_by_role("button", name="Temperature: >=20")
    expect(page.get_by_role("row").filter(has_text="Hall")).to_have_count(0)
    # the filter's chip has the focus: Enter opens it again
    expect(chip).to_be_focused()
    with _posted(page):
        page.keyboard.press("Enter")
    expect(value).to_have_value(">=20")

    # Escape closes the editor, changing nothing, the focus on "+ Filter"; focused once
    # the swap has settled, its triggers bound
    expect(value).to_be_focused()
    with _posted(page):
        value.press("Escape")
    expect(value).to_have_count(0)
    expect(add_filter).to_be_focused()
    expect(chip).to_be_visible()


def test_a_table_s_body_swapped_with_another_table_leaves_that_one_whole(
    rooms_page: Page,
) -> None:
    page = rooms_page
    page.goto("/")
    with _posted(page):
        page.get_by_role("row").filter(has_text="Hall").click()
    expect(page.get_by_role("cell", name="1 selected")).to_be_visible()
    # htmx binds the swapped table's triggers once the swap has settled
    expect(page.locator(".htmx-added")).to_have_count(0)
    # hiding the hall deselects it: the rooms' body, then the notes whole, in one answer
    with _posted(page):
        page.get_by_label("Search").press_sequentially("room")
    expect(page.get_by_role("cell", name="0 selected")).to_be_visible()
    expect(page.get_by_role("columnheader", name="Note")).to_be_visible()
    expect(page.get_by_role("row").filter(has_text="Bedroom")).to_have_count(1)


def test_the_filter_editor_s_toggle_shows_for_text_and_hints_at_a_pattern(
    rooms_page: Page,
) -> None:
    page = rooms_page
    page.goto("/")
    with _posted(page):
        page.get_by_role("button", name="+ Filter").click()
    value, pattern = page.get_by_label("Value"), page.get_by_label("Regular expression")
    expect(value).to_have_attribute("placeholder", "contains, =exact, start*, !not")
    page.get_by_title("Regular expression").click()  # the button drawing the checkbox
    expect(pattern).to_be_checked()
    expect(value).to_have_attribute("placeholder", "a regular expression, as Room [1-3]")
    # a number column takes comparisons, not a pattern
    page.get_by_label("Column").select_option(label="Temperature")
    expect(page.get_by_title("Regular expression")).to_be_hidden()
    expect(value).to_have_attribute("placeholder", ">=20, 18..24")
    page.get_by_label("Column").select_option(label="Room")
    with _posted(page):
        value.press_sequentially("^(hall|attic)$")
        value.press("Enter")
    expect(page.get_by_role("button", name="Room matches ^(hall|attic)$")).to_be_focused()
    expect(page.get_by_role("row").filter(has_text="kitchen")).to_have_count(0)
    expect(page.get_by_role("row").filter(has_text="Attic")).to_have_count(1)


def test_a_large_table_draws_the_rows_scrolled_to_keeping_the_focus(
    million_page: Page,
) -> None:
    page = million_page
    page.goto("/")
    # the row at position 3 holds 2 * 2
    row = page.get_by_role("row").filter(has=page.get_by_role("cell", name="4", exact=True))
    with _posted(page):
        row.click()
    expect(row).to_have_attribute("aria-current", "true")
    expect(row).to_be_focused()
    half = page.get_by_role("button", name="Half")
    with _posted(page):
        half.click()
    expect(page.locator("th[aria-sort=ascending]")).to_have_count(1)
    expect(half).to_be_focused()

    frame = page.locator("[data-virtual-scroll]")
    frame.hover()
    with _posted(page):
        page.mouse.wheel(0, 40_000)
    # the rows drawn cover the frame, wherever it was scrolled to, and it stays there
    top = frame.evaluate("frame => frame.scrollTop")
    assert top > 0
    page.wait_for_function(
        """frame => {
            const rows = frame.querySelectorAll("tr[data-window-row]");
            const view = frame.getBoundingClientRect();
            const head = frame.querySelector("thead").getBoundingClientRect().height;
            return rows.length > 0
                && rows[0].getBoundingClientRect().top <= view.top + head
                && rows[rows.length - 1].getBoundingClientRect().bottom >= view.bottom;
        }""",
        arg=frame.element_handle(),
    )
    assert frame.evaluate("frame => frame.scrollTop") == top
    first = page.locator("tr[data-window-row]").first.get_attribute("aria-rowindex")
    assert first is not None
    assert int(first) > 1_000


def test_a_large_table_scrolled_past_its_rows_shows_the_rows_its_scroll_bar_stands_for(
    million_page: Page,
) -> None:
    page = million_page
    page.goto("/")
    frame = page.locator("[data-virtual-scroll]")
    height = page.locator("tr[data-window-row]").first.evaluate(
        "row => row.getBoundingClientRect().height"
    )
    frame.hover()
    # about 10 rows' heights past the 100 rows drawn, where a row's height stands for 2.5:
    # mid-row, not at a row's edge
    with _posted(page):
        page.mouse.wheel(0, 110.2 * height)
    top = frame.evaluate("frame => frame.scrollTop")
    expected = int(100 + (top - 100 * height) / height * 2.5)

    under_headers = frame.evaluate(
        """frame => {
            const view = frame.getBoundingClientRect();
            const head = frame.querySelector("thead").getBoundingClientRect().height;
            const row = document.elementFromPoint(view.left + 20, view.top + head + 2)
                .closest("tr[data-window-row]");
            return row === null ? null : Number(row.getAttribute("aria-rowindex")) - 2;
        }"""
    )
    assert under_headers == expected
    assert frame.evaluate("frame => frame.scrollTop") == top  # the frame didn't jump


def _clipboard_becomes(page: Page, text: str) -> bool:
    """Wait, in the page, for the clipboard to hold `text`: the page writes it once answered.

    Its item, given during Ctrl+C, gets its text from the answer: written a moment after.
    """
    return bool(
        page.evaluate(
            """async text => {
                for (let tries = 0; tries < 100; tries++) {
                    if (await navigator.clipboard.readText() === text) return true;
                    await new Promise(resolve => requestAnimationFrame(resolve));
                }
                return false;
            }""",
            text,
        )
    )


def test_ctrl_c_writes_a_large_table_s_selected_row_to_the_clipboard(
    browser: Browser, million_base_url: str
) -> None:
    context = browser.new_context(
        base_url=million_base_url, permissions=["clipboard-read", "clipboard-write"]
    )
    page = context.new_page()
    page.goto("/")
    page.evaluate("navigator.clipboard.writeText('kept')")  # what the user copied before
    # no row selected: nothing to copy, the clipboard keeps its text
    page.get_by_role("button", name="Value").focus()
    with _posted(page):
        page.keyboard.press("ControlOrMeta+c")
    expect(page.locator("[data-copied]")).to_have_text("")
    assert page.evaluate("navigator.clipboard.readText()") == "kept"
    # the row at position 3 holds 2 * 2, then its half
    row = page.get_by_role("row").filter(has=page.get_by_role("cell", name="4", exact=True))
    with _posted(page):
        row.click()
    with _posted(page):
        page.keyboard.press("ControlOrMeta+c")
    expect(page.locator("[data-copied]")).to_have_text("4\t1.0")
    assert _clipboard_becomes(page, "4\t1.0")
    context.close()
