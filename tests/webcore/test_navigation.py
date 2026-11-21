"""Tests of the web main view, router and sidebar."""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from attrs import Factory

from composeui.core.registry import RendererType
from composeui.core.view import (
    MainView,
    PageView,
    Router,
    define_view,
)
from composeui.webcore._renderers.actions import WebActionRenderer
from composeui.webcore._renderers.navigation import RESERVED_ROUTES, WebMainRenderer
from composeui.webcore.changes import collect_dirty
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import (
    WebRenderer,
    handle_event,
)
from examples.webhello import HelloMainView
from tests.pages import InputsPage, PagesMainView
from tests.sidebar import SidebarMainView

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from starlette.testclient import TestClient


from tests.webcore.support import (
    _Browser,
    _disable_on_submit,
    _element,
    _NoteMainView,
    _swapped,
    _widget_id,
)


def _shown_routes(page: str) -> list[str]:
    return re.findall(r'<div data-route="([^"]*)">', page)


def test_each_page_has_its_own_address(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    home = pages_client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/inputs"

    page = pages_client.get("/results").text
    (main_view,) = pages_views
    assert main_view.router.current_route == "results"
    assert _shown_routes(page) == ["results"]
    results_link = _element(page, _widget_id(main_view.router.results.action.renderer))
    inputs_link = _element(page, _widget_id(main_view.router.inputs.action.renderer))
    assert (results_link.text, results_link.attributes["href"]) == ("Results", "/results")
    assert "aria-current" in results_link.attributes
    assert "aria-current" not in inputs_link.attributes

    # no page there, e.g. the browser's own `/favicon.ico`: not found, and no navigation
    for address in ("/settings", "/favicon.ico"):
        assert pages_client.get(address).status_code == 404
    assert main_view.router.current_route == "results"


@pytest.mark.parametrize("reserved", sorted(RESERVED_ROUTES))
def test_a_page_on_an_address_the_backend_uses_stops_the_app_before_serving(
    reserved: str,
) -> None:
    @define_view
    class Page(PageView):
        route = reserved

    @define_view
    class Pages(Router):
        reserved_page: Page = Factory(Page)

    @define_view
    class ReservedMainView(MainView):
        app_title = "Reserved"
        extension = ".reserved"

        pages: Pages = Factory(Pages)

    message = re.escape(f"the routes [{reserved!r}]: rename them")
    with pytest.raises(ValueError, match=message):
        WebApplication(build_main_view=ReservedMainView).create_starlette_app()
    with pytest.raises(ValueError, match=message):  # rendered without the app
        ReservedMainView().render(RendererType.WEB)


def test_a_toolbar_link_shows_its_page_and_puts_its_address_in_the_history(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    pages_client.get("/")
    (main_view,) = pages_views
    results = _widget_id(main_view.router.results.action.renderer)

    response = pages_client.post(f"/widget/{results}", data={"event": "triggered"})
    assert main_view.router.current_route == "results"
    assert response.headers["HX-Push-Url"] == "/results"
    router = _swapped(response.text, _widget_id(main_view.router.renderer))
    shown = [
        attributes["data-route"]
        for tag, attributes in router.descendants
        if tag == "div" and "data-route" in attributes and "hidden" not in attributes
    ]
    assert shown == ["results"]
    assert "aria-current" in _swapped(response.text, results).attributes
    inputs = _swapped(response.text, _widget_id(main_view.router.inputs.action.renderer))
    assert "aria-current" not in inputs.attributes

    # the shown page's link again: no navigation, so nothing new in the history
    again = pages_client.post(f"/widget/{results}", data={"event": "triggered"})
    assert "HX-Push-Url" not in again.headers


@pytest.fixture
def sidebar() -> Iterator[tuple[TestClient, SidebarMainView]]:
    """Serve an app with a sidebar beside its pages; yield a client and its main view."""
    views: list[SidebarMainView] = []

    class SidebarApp(WebApplication[SidebarMainView]):
        @override
        def setup_session(self, main_view: SidebarMainView) -> None:
            views.append(main_view)

    app = SidebarApp(build_main_view=SidebarMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield client, view


def test_a_sidebar_is_a_drawer_beside_the_pages_whatever_the_page(
    sidebar: tuple[TestClient, SidebarMainView],
) -> None:
    client, view = sidebar
    aside_id = _widget_id(view.sidebar.renderer)
    router_id = _widget_id(view.router.renderer)
    for path in ("/", "/results"):
        page = client.get(path).text
        aside = _element(page, aside_id)
        assert aside.tag == "aside"
        assert aside.attributes["aria-label"] == "New record"
        assert "New record" in aside.text
        assert _widget_id(view.sidebar.create.renderer) in page
        # not one of the pages: shown whatever the page
        pages = _element(page, router_id).descendants
        assert all(attributes.get("id") != aside_id for _, attributes in pages)
        # the drawer's checkbox, which the header's button and the backdrop toggle
        toggle = _element(page, f"{aside_id}-toggle").attributes
        drawer = _element(page, str(toggle["data-sidebar-toggle"])).attributes
        assert (drawer["type"], toggle["aria-controls"]) == ("checkbox", aside_id)
        assert f'<label for="{drawer["id"]}" class="drawer-overlay"' in page

    def rename() -> None:
        view.sidebar.title = "<Add>"
        view.sidebar.toggle_text = "<Panel>"

    view.sidebar.create.clicked.connect(rename)
    create = view.sidebar.create.renderer
    assert isinstance(create, WebRenderer)
    fragments = handle_event(create, "click", {})
    # the button swaps along with the sidebar, its text escaped as the title is
    assert "<Add>" in _swapped(fragments, aside_id).text
    assert _swapped(fragments, f"{aside_id}-toggle").attributes["aria-label"] == "<Panel>"


def test_a_sidebar_is_retracted_by_its_button_never_swapped_back(
    sidebar: tuple[TestClient, SidebarMainView],
) -> None:
    client, view = sidebar
    renderer = view.sidebar.renderer
    assert isinstance(renderer, WebRenderer)
    aside_id = renderer.widget_id
    toggles: list[bool] = []
    view.sidebar.toggled.connect(toggles.append)
    toggle = _element(client.get("/").text, f"{aside_id}-toggle").attributes
    assert (toggle["hx-post"], toggle["aria-expanded"]) == (f"/widget/{aside_id}", "true")

    fragments = handle_event(renderer, "toggle", {"expanded": "false"})
    assert (view.sidebar.is_expanded, toggles) == (False, [False])
    assert aside_id not in fragments  # the browser retracted it already
    handle_event(renderer, "toggle", {"expanded": "false"})
    assert toggles == [False]
    # a page of the session shows it retracted
    page = client.get("/").text
    assert "data-retracted" in _element(page, aside_id).attributes
    assert _element(page, f"{aside_id}-toggle").attributes["aria-expanded"] == "false"


@define_view
class _StatePage(InputsPage):
    route = "state"


@define_view
class _StateRouter(Router):
    state: _StatePage = Factory(_StatePage)


@define_view
class _StateMainView(MainView):
    app_title = "State"
    extension = ".state"

    router: _StateRouter = Factory(_StateRouter)


def test_a_route_cannot_take_an_address_of_the_backend() -> None:
    with pytest.raises(ValueError, match="'state'"):
        _StateMainView().render(RendererType.WEB)


def test_disabling_a_router_disables_its_pages_but_not_their_links(
    notes: tuple[TestClient, _NoteMainView],
) -> None:
    client, main_view = notes
    submit_id = _disable_on_submit(main_view, main_view.pages)
    body = client.post(f"/widget/{submit_id}", data={"event": "click"}).text

    router = _swapped(body, _widget_id(main_view.pages.renderer))
    (submit,) = [
        attributes for _, attributes in router.descendants if attributes.get("id") == submit_id
    ]
    assert "disabled" in submit
    assert client.post(f"/widget/{submit_id}", data={"event": "click"}).status_code == 400
    # as Qt's toolbar, apart from the stack of pages: the pages can still be switched
    page = client.get("/").text
    for routed in (main_view.pages.first, main_view.pages.note):
        link = _element(page, _widget_id(routed.action.renderer))
        assert "aria-disabled" not in link.attributes
        assert "hx-post" in link.attributes


def test_the_tab_and_the_header_show_the_app_s_icon_composeui_s_by_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = client.get("/").text

    match = re.search(r'<link rel="icon" href="([^"]+)" />', page)
    assert match is not None
    icon = client.get(match[1])
    assert icon.status_code == 200
    app_icon = HelloMainView.app_icon
    assert app_icon is not None
    assert icon.content == app_icon.read_bytes()
    assert ("img", match[1]) in [
        (tag, attributes.get("src")) for tag, attributes in _element(page, "cui-brand").descendants
    ]

    # without one, no icon in the tab, and a badge of the title's initial in the header
    monkeypatch.setattr(HelloMainView, "app_icon", None)
    main_view = HelloMainView()
    main_view.render(RendererType.WEB)
    assert isinstance(main_view.renderer, WebMainRenderer)
    page = main_view.renderer.page_html()
    assert 'rel="icon"' not in page
    brand = _element(page, "cui-brand")
    assert all(tag != "img" for tag, _attributes in brand.descendants)
    assert brand.text.startswith(main_view.title[0].upper())


@define_view
class _LonePageMainView(MainView):
    app_title = "Lone page"
    extension = ".lone"
    #: outside a router: no toolbar shows its entry
    page: InputsPage = Factory(InputsPage)


def test_a_page_outside_a_router_swaps_nothing_for_its_entry() -> None:
    main_view = _LonePageMainView()
    main_view.render(RendererType.WEB)
    assert isinstance(main_view.renderer, WebMainRenderer)
    page = main_view.renderer.page_html()
    action = main_view.page.action.renderer
    assert isinstance(action, WebActionRenderer)
    assert action.widget_id not in page
    new = main_view.file_menu.new.renderer
    assert isinstance(new, WebActionRenderer)
    assert new.widget_id in page

    with collect_dirty() as dirty:
        main_view.page.title = "Entrées"
        main_view.file_menu.new.text = "Nouveau"

    assert list(dirty) == [new.widget_id]


def test_a_header_button_shows_its_own_icon_and_a_disabled_page_tab_no_link(
    tmp_path: Path,
) -> None:
    icon = tmp_path / "save.svg"
    icon.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    view = PagesMainView()
    view.file_menu.save.icon = str(icon)
    page = view.router.pages[1]
    page.action.is_enabled = False
    view.render(RendererType.WEB)
    assert isinstance(view.renderer, WebMainRenderer)

    html = view.renderer.page_html()

    save = _element(html, _widget_id(view.file_menu.save.renderer))
    # its own icon, drawn in the text's color, rather than the built-in one
    assert any("/icon/" in (attributes.get("style") or "") for _, attributes in save.descendants)
    tab = _element(html, _widget_id(page.action.renderer))
    assert (tab.tag, tab.attributes.get("aria-disabled"), "href" in tab.attributes) == (
        "a",
        "true",
        False,
    )
