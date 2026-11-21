"""Tests of the web page: its frame, its static files, its icons and its stylesheet."""

from __future__ import annotations

import hashlib
import os
import re
import sys

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from typing import TYPE_CHECKING

from composeui.core.registry import RendererType
from composeui.core.view import (
    ButtonVariant,
    ButtonView,
    ChartView,
    LogType,
    LogView,
    MainView,
    PageWidth,
    TreeView,
)
from composeui.webcore.changes import collect_dirty
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import (
    WebRenderer,
    render_dirty,
)
from tests.buildings import styled_site
from tests.webcore.support import (
    _action_id,
    _Browser,
    _element,
    _field_id,
    _find,
    _icon_url,
    _swapped,
    _widget_id,
)

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient

    from examples.pipeform import PipeMainView
    from examples.webhello import HelloMainView
    from tests.toolbar import ToolBarMainView


def test_page_shows_the_form_and_docks_an_empty_status_bar(
    main_view: HelloMainView, client: TestClient
) -> None:
    response = client.get("/")

    assert response.status_code == 200
    page = response.text
    assert "<title>Hello ComposeUI</title>" in page
    assert '<meta name="viewport"' in page
    assert re.search(r"<h1[^>]*>Hello ComposeUI</h1>", page)
    name = _element(page, _field_id(main_view.form.name))
    assert name.attributes["placeholder"] == "Type your name..."
    status_bar = _element(page, _widget_id(main_view.status_bar.renderer))
    classes = set((status_bar.attributes["class"] or "").split())
    assert status_bar.tag == "footer"
    assert status_bar.text == ""
    assert status_bar.descendants == []
    # a status line docked at the bottom, not a coloured callout showing even when empty
    assert {"fixed", "inset-x-0", "bottom-0"} <= classes
    assert "alert" not in classes


@pytest.mark.parametrize(
    ("width", "expected_class"),
    [
        (PageWidth.NARROW, "max-w-3xl"),
        (PageWidth.WIDE, "max-w-6xl"),
        (PageWidth.FULL, "max-w-none"),
    ],
)
def test_main_view_sets_the_web_content_width_without_a_page(
    monkeypatch: pytest.MonkeyPatch, width: PageWidth, expected_class: str
) -> None:
    monkeypatch.setattr(MainView, "width", width)
    app = WebApplication(build_main_view=MainView)
    with _Browser(app.create_starlette_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    main = re.search(r'<main class="([^"]+)"', response.text)
    assert main is not None
    assert expected_class in main[1].split()


def test_the_browser_never_shows_a_stale_copy_of_the_page(
    main_view: HelloMainView, client: TestClient
) -> None:
    """After a server restart, a reload must show the server's state, not the browser's.

    Without these, Firefox reused the old page (no cache header) or refilled every field
    of the fresh one with what was typed before, next to messages about empty fields.
    """
    page = client.get("/")
    controls = re.findall(r"<(?:input|select)\b[^>]*>", page.text)
    status_bar_id = _widget_id(main_view.status_bar.renderer)
    input_id = _field_id(main_view.form.name)

    assert len(controls) >= 4  # name, age, two radios, colour
    assert all('autocomplete="off"' in control for control in controls)
    assert page.headers["cache-control"] == "no-store"
    event = client.post(f"/widget/{input_id}", data={"value": "Bob", "event": "input"})
    assert event.headers["cache-control"] == "no-store"
    assert client.get(f"/widget/{status_bar_id}").headers["cache-control"] == "no-store"


def test_the_page_loads_nothing_from_another_host(client: TestClient) -> None:
    """Styles and scripts are served by the app itself, so it also works offline."""
    page = client.get("/").text

    assert re.findall(r'(?:src|href)="(?:https?:)?//[^"]*"', page) == []
    assert client.get("/static/app.css").status_code == 200


def test_the_page_has_no_inline_script(client: TestClient) -> None:
    """The page's script is a static file: a policy can allow it by address, not inline."""
    page = client.get("/").text

    assert re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", page) == []


def test_the_page_names_each_static_file_by_its_content(client: TestClient) -> None:
    """A new stylesheet or script has a new address: a browser can't keep an older copy."""
    page = client.get("/").text

    addresses = re.findall(r'(?:src|href|data-[a-z]+)="(/static/[^"]*)"', page)

    assert sorted(address.split("?")[0] for address in addresses) == [
        "/static/app.css",
        "/static/cally.js",
        "/static/charts.js",
        "/static/deckgl.min.js",
        "/static/htmx.min.js",
        "/static/maps.js",
        "/static/page.js",
        "/static/tables.js",
        "/static/uPlot.iife.min.js",
    ]
    for address in addresses:
        body = client.get(address).content
        assert address.endswith(f"?v={hashlib.sha256(body).hexdigest()[:16]}")


def test_every_class_the_renderers_use_is_in_the_built_stylesheet(
    main_view: HelloMainView, client: TestClient, pipe_client: TestClient
) -> None:
    """Catches a class added in Python without rebuilding `static/app.css` (`make css`)."""
    markup = [client.get("/").text, pipe_client.get("/").text]
    for log_type in LogType:  # each log colour
        log = LogView(log_message="x", log_type=log_type)
        log.render(RendererType.WEB)
        assert isinstance(log.renderer, WebRenderer)
        markup.append(log.renderer.to_html())
    for variant in ButtonVariant:  # each button colour
        button = ButtonView(text="x", variant=variant)
        button.render(RendererType.WEB)
        assert isinstance(button.renderer, WebRenderer)
        markup.append(button.renderer.to_html())
    tree = TreeView(nodes=styled_site("building.png"), expanded=[("Building A",)])
    tree.render(RendererType.WEB)  # each mark's colour, each label's style
    assert isinstance(tree.renderer, WebRenderer)
    markup.append(tree.renderer.to_html())
    chart = ChartView(title="x")
    chart.render(RendererType.WEB)
    assert isinstance(chart.renderer, WebRenderer)
    markup.append(chart.renderer.to_html())
    main_view.file_menu.new.is_enabled = False  # a disabled menu item
    markup.append(client.get("/").text)
    classes = {
        name
        for page in markup
        for value in re.findall(r'class="([^"]*)"', page)
        for name in value.split()
    }
    stylesheet = client.get("/static/app.css").text

    def selector(name: str) -> str:
        # all but letters, digits, `_` and `-` is escaped in its selector, e.g.
        # `.sm\:w-auto`, `.text-base-content\/50`, `.has-\[\>\[hidden\]\]\:hidden`
        return "." + re.escape(re.sub(r"([^\w-])", r"\\\1", name))

    missing = sorted(
        name for name in classes if not re.search(rf"{selector(name)}(?![\w-])", stylesheet)
    )
    assert len(classes) > 40
    assert missing == []


def test_an_icon_is_served_from_its_content_and_only_when_a_view_names_it(
    toolbar_views: list[ToolBarMainView], toolbar_client: TestClient, tmp_path: Path
) -> None:
    toolbar_client.get("/")
    (main_view,) = toolbar_views
    run_svg = tmp_path / "run.svg"
    run_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>')
    wrap_png = tmp_path / "wrap.png"
    wrap_png.write_bytes(b"\x89PNG\r\n\x1a\n")
    secret = tmp_path / "secret.txt"
    secret.write_text("not an image")
    main_view.toolbar.run.icon = str(run_svg)
    main_view.toolbar.wrap.icon = str(wrap_png)
    main_view.router.results.icon = str(secret)

    page = toolbar_client.get("/").text
    run_url = _icon_url(_element(page, _action_id(main_view.toolbar.run)))
    wrap_url = _icon_url(_element(page, _action_id(main_view.toolbar.wrap)))
    for url, path, media_type in (
        (run_url, run_svg, "image/svg+xml"),
        (wrap_url, wrap_png, "image/png"),
    ):
        response = toolbar_client.get(url)
        assert response.status_code == 200
        assert response.content == path.read_bytes()
        assert response.headers["content-type"] == media_type
        assert "immutable" in response.headers["cache-control"]
    # the tooltip names a button the phone shows as its icon only
    assert _element(page, _action_id(main_view.toolbar.wrap)).attributes["title"] == "Wrap"
    results_tab = _element(page, _action_id(main_view.router.results.action))
    assert not any(tag in {"img", "span"} for tag, _ in results_tab.descendants)

    # another content: another address, and the old one is gone
    run_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="4"/></svg>')
    os.utime(run_svg, ns=(0, run_svg.stat().st_mtime_ns + 1))
    with collect_dirty() as dirty:
        main_view.toolbar.run.text = "Go"
        swapped = _swapped(render_dirty(dirty), _action_id(main_view.toolbar.run))
    assert _icon_url(swapped) != run_url
    assert toolbar_client.get(run_url).status_code == 404


def test_the_page_is_in_the_app_s_source_language_until_set(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    page = pipe_client.get("/").text

    assert '<html lang="en">' in page
    assert "<title>Pipe Form</title>" in page
    marker = _element(page, "cui-page").attributes
    assert (marker["data-language"], marker["data-title"]) == ("en", "Pipe Form")
    # an event leaving the language alone doesn't send it again
    response = pipe_client.post(
        f"/widget/{_action_id(pipe_main_view.language_menu.action('en'))}",
        data={"event": "triggered"},
    )
    assert _find(response.text, "cui-page") is None
    assert _find(response.text, "cui-brand") is None
