"""Tests of the web containers: pages, rows, grids, splitters, expanders, tabs and lists."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from composeui.core.registry import RendererType
from composeui.core.view import (
    ButtonVariant,
    LabelView,
)
from composeui.webcore._renderers.navigation import WebMainRenderer
from composeui.webcore.changes import collect_dirty
from composeui.webcore.session import WebSession
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import (
    WebRenderer,
    handle_event,
    render_dirty,
)
from tests.expander import RecordMainView
from tests.latepages import LatePagesMainView
from tests.listview import PIPES, PipeExpander, PipesMainView
from tests.partial import PartialMainView, UnregisteredView
from tests.splitter import SplitterMainView, VerticalSplitterMainView
from tests.tables import (
    Room,
)
from tests.tabs import TabsMainView
from tests.vertical import VerticalMainView

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.testclient import TestClient

    from tests.pages import PagesMainView


from tests.webcore.support import (
    _Browser,
    _contains,
    _element,
    _field_id,
    _find,
    _swapped,
    _widget_id,
)


def test_a_tab_view_is_a_tab_list_posting_the_tab_picked_never_swapped_back() -> None:
    view = TabsMainView()
    view.render(RendererType.WEB)
    tabs = view.tabs
    renderer = tabs.renderer
    assert isinstance(renderer, WebRenderer)
    picks: list[int] = []
    tabs.current_changed.connect(picks.append)
    root = _element(renderer.to_html(), renderer.widget_id)
    buttons = [
        attributes for tag, attributes in root.descendants if attributes.get("role") == "tab"
    ]
    panels = [a for _, a in root.descendants if a.get("role") == "tabpanel"]
    assert [b["aria-selected"] for b in buttons] == ["true", "false", "false"]
    assert [b["tabindex"] for b in buttons] == ["0", "-1", "-1"]
    assert ["hidden" in panel for panel in panels] == [False, True, True]
    assert [b["aria-controls"] for b in buttons] == [p["id"] for p in panels]
    # only the current tab's views are sent, and built
    assert "Length: 12 m" in root.text
    assert "Created on Monday" not in root.text
    assert tabs.history.created.renderer is None

    fragments = handle_event(renderer, "select", {"index": "1"})
    assert (tabs.current_index, picks) == (1, [1])
    assert renderer.widget_id not in fragments  # the browser shows it already
    # the answer fills the tab picked and empties the tab left
    assert _swapped(fragments, _widget_id(tabs.history.renderer)).text == "Created on Monday"
    assert _swapped(fragments, _widget_id(tabs.details.renderer)).descendants == []
    for index in ("1", "7", "x"):  # the tab shown, or none: nothing changes
        handle_event(renderer, "select", {"index": index})
    assert (tabs.current_index, picks) == (1, [1])

    def rename() -> None:
        tabs.history.title = "<Changes>"
        tabs.notes.is_visible = False
        tabs.details.length.text = "Length: 15 m"  # on a tab not shown: not sent

    tabs.details.edit.clicked.connect(rename)
    edit = tabs.details.edit.renderer
    assert isinstance(edit, WebRenderer)
    fragments = handle_event(edit, "click", {})
    assert "Length: 15 m" not in fragments
    swapped = _swapped(fragments, renderer.widget_id)
    buttons = [a for _, a in swapped.descendants if a.get("role") == "tab"]
    assert "<Changes>" in swapped.text  # escaped, shown as text
    assert ["hidden" in b for b in buttons] == [False, False, True]

    tabs.notes.is_visible = True
    with collect_dirty() as dirty:  # the code shows a tab not built yet
        tabs.current_index = 2
        fragments = render_dirty(dirty)
    assert "Insulated in 2024" in _swapped(fragments, renderer.widget_id).text


def test_a_splitter_shares_its_width_as_its_sizes_and_takes_the_widths_posted() -> None:
    view = SplitterMainView()
    view.render(RendererType.WEB)
    splitter = view.splitter
    renderer = splitter.renderer
    assert isinstance(renderer, WebRenderer)
    root = _element(renderer.to_html(), renderer.widget_id)
    panes = [a for _, a in root.descendants if "data-pane" in a]
    borders = [a for _, a in root.descendants if a.get("role") == "separator"]
    assert [pane["style"] for pane in panes] == [f"--share: {size} 1 0%" for size in (1, 1, 2)]
    # a border between two panes, controlling the one after it, its value where it is
    assert [b["aria-controls"] for b in borders] == [p["id"] for p in panes[1:]]
    assert [b["aria-valuenow"] for b in borders] == ["25", "50"]
    assert {b["aria-orientation"] for b in borders} == {"vertical"}
    assert {b["tabindex"] for b in borders} == {"0"}

    resizes: list[list[int]] = []
    splitter.resized.connect(resizes.append)
    fragments = handle_event(renderer, "resize", {"lengths": "300,100,400"})
    assert (splitter.sizes, resizes) == ([38, 12, 50], [[38, 12, 50]])
    assert renderer.widget_id not in fragments  # the browser shows it already
    # the sizes it has (a click), or none: nothing changes, nothing reported
    for widths in ("300,100,400", "300,100", "1,x,3", "1,-1,3", "1,nan,3"):
        handle_event(renderer, "resize", {"lengths": widths})
    assert (splitter.sizes, len(resizes)) == ([38, 12, 50], 1)

    splitter.settings.is_visible = False  # its share kept, out of the others'
    handle_event(renderer, "resize", {"lengths": "300,0,100"})
    assert splitter.sizes == [75, 12, 25]
    splitter.is_enabled = False
    root = _element(renderer.to_html(), renderer.widget_id)
    borders = [a for _, a in root.descendants if a.get("role") == "separator"]
    assert [b["aria-valuenow"] for b in borders] == ["75", "75"]
    assert {(b["aria-disabled"], b["tabindex"]) for b in borders} == {("true", "-1")}


def test_a_splitter_s_borders_follow_the_language() -> None:
    view = SplitterMainView()
    view.render(RendererType.WEB)
    renderer = view.splitter.renderer
    assert isinstance(renderer, WebRenderer)

    with collect_dirty() as dirty:
        view.set_language("fr")
        root = _swapped(render_dirty(dirty), renderer.widget_id)

    borders = [a for _, a in root.descendants if a.get("role") == "separator"]
    assert [b["aria-label"] for b in borders] == ["Redimensionner les volets"] * 2


def test_a_vertical_splitter_stacks_its_panes_with_a_horizontal_border_between() -> None:
    view = VerticalSplitterMainView()
    view.render(RendererType.WEB)
    splitter = view.splitter
    renderer = splitter.renderer
    assert isinstance(renderer, WebRenderer)
    root = _element(renderer.to_html(), renderer.widget_id)
    panes = [a for _, a in root.descendants if "data-pane" in a]
    (border,) = [a for _, a in root.descendants if a.get("role") == "separator"]
    assert [pane["style"] for pane in panes] == ["--share: 2 1 0%", "--share: 1 1 0%"]
    # each scrolls on its own
    assert all("overflow-auto" in (pane["class"] or "") for pane in panes)
    assert (border["aria-orientation"], border["aria-valuenow"]) == ("horizontal", "67")

    handle_event(renderer, "resize", {"lengths": "100,300"})
    assert splitter.sizes == [25, 75]


def test_an_expander_is_a_details_posting_its_toggles_never_swapped_back() -> None:
    view = RecordMainView()
    view.render(RendererType.WEB)
    record = view.record
    expander = record.renderer
    assert isinstance(expander, WebRenderer)
    toggles: list[bool] = []
    record.toggled.connect(toggles.append)
    record.title = "<Pipe A>"
    details = _element(expander.to_html(), expander.widget_id)
    assert details.tag == "details"
    assert "open" not in details.attributes  # collapsed
    assert "<Pipe A>" in details.text  # escaped, shown as text
    # its views inside, rendered even while collapsed, for their own swaps
    assert _widget_id(record.buttons.edit.renderer) in expander.to_html()

    fragments = handle_event(expander, "toggle", {"open": "true"})
    assert (record.is_expanded, toggles) == (True, [True])
    assert expander.widget_id not in fragments  # the browser opened it already
    handle_event(expander, "toggle", {"open": "true"})  # the server's state posted back
    assert toggles == [True]
    assert "open" in _element(expander.to_html(), expander.widget_id).attributes

    record.is_enabled = False
    descendants = _element(expander.to_html(), expander.widget_id).descendants
    # its own summary, before the nested expander's
    summary = next(attributes for tag, attributes in descendants if tag == "summary")
    assert summary["tabindex"] == "-1"  # its title can't be focused to toggle it


@pytest.fixture
def pipes() -> Iterator[tuple[TestClient, PipesMainView]]:
    """Serve an app listing pipes, an expander each; yield a client and its main view."""
    views: list[PipesMainView] = []

    class PipesApp(WebApplication[PipesMainView]):
        @override
        def setup_session(self, main_view: PipesMainView) -> None:
            main_view.pipes.items = PIPES
            views.append(main_view)

    app = PipesApp(build_main_view=PipesMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        yield client, view


def test_a_list_view_swaps_only_the_items_its_records_changed(
    pipes: tuple[TestClient, PipesMainView],
) -> None:
    client, view = pipes
    list_id = _widget_id(view.pipes.renderer)
    main_line, ret = view.pipes.item_views
    main_line_id = _widget_id(main_line.renderer)
    page = client.get("/").text
    assert _contains(_element(page, list_id), main_line_id)

    # a pipe added first: the list's items kept, and the one added put in ahead of them
    body = client.post(f"/widget/{_widget_id(view.add.renderer)}", data={"event": "click"}).text
    feed = view.pipes.item_views[0]
    assert f'id="{list_id}" hx-swap-oob="true"' not in body
    assert f'hx-swap-oob="afterbegin:#{list_id}"' in body
    assert main_line_id not in body
    assert isinstance(feed, PipeExpander)
    feed_delete_id = _widget_id(feed.delete.renderer)
    assert feed_delete_id in body

    # the new item's controls reach the session: deleting it deletes its item only
    body = client.post(f"/widget/{feed_delete_id}", data={"event": "click"}).text
    assert [pipe.name for pipe in view.pipes.items] == ["Main line", "Return"]
    assert 'hx-swap-oob="delete"' in body
    assert main_line_id not in body
    assert client.post(f"/widget/{feed_delete_id}", data={"event": "click"}).status_code == 404

    # reordered: the whole list swaps
    view.add.clicked.connect(lambda: setattr(view.pipes, "items", PIPES[::-1]))
    body = client.post(f"/widget/{_widget_id(view.add.renderer)}", data={"event": "click"}).text
    assert _contains(_swapped(body, list_id), _widget_id(ret.renderer))


def test_a_page_not_shown_is_built_once_shown_with_what_changed_before() -> None:
    view = LatePagesMainView()
    session = WebSession(view)
    page = view.router.rooms
    assert page.rooms.renderer is None  # built once shown: a session doesn't pay for it before
    page.rooms.records = [Room("Hall", 18), Room("Kitchen", 20.5), Room("Attic", 9)]
    page.rooms.sort_column = 1  # temperature
    page.rooms.sort_descending = True

    assert session.open_route("rooms")  # as its address does

    text = _element(session.page_html(), _widget_id(page.rooms.renderer)).text
    assert text.index("Kitchen") < text.index("Hall") < text.index("Attic")
    session.close()


def test_clicking_the_button_changes_a_page_not_shown_once_it_shows(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    pages_client.get("/results")  # built, then left: its label changes outside the page
    page = pages_client.get("/inputs").text
    (main_view,) = pages_views
    inputs = main_view.router.inputs
    button_id = _widget_id(inputs.submit.renderer)
    button = _element(page, button_id)
    assert (button.tag, button.attributes["type"], button.text) == ("button", "button", "Submit")
    assert "btn-primary" in (button.attributes["class"] or "").split()
    inputs.name.text = "<Ada>"

    response = pages_client.post(f"/widget/{button_id}", data={"event": "click"})

    assert response.status_code == 200
    assert response.text == ""  # the clicked button isn't swapped back, nor the label not shown
    results_link = _widget_id(main_view.router.results.action.renderer)
    shown = pages_client.post(f"/widget/{results_link}", data={"event": "triggered"}).text
    _swapped(shown, _widget_id(main_view.router.renderer))
    assert _find(shown, button_id) is None  # the page left goes
    total = _element(shown, _widget_id(main_view.router.results.total.renderer))
    assert total.text == "Submitted: <Ada>"  # escaped in the markup, the text once parsed

    pages_client.get("/inputs")
    with collect_dirty() as dirty:
        inputs.submit.variant = ButtonVariant.DANGER
        swapped = _swapped(render_dirty(dirty), button_id)
    assert "btn-error" in (swapped.attributes["class"] or "").split()
    assert swapped.attributes["data-variant"] == "danger"  # what an app's stylesheet selects

    inputs.submit.is_enabled = False
    refused = pages_client.post(f"/widget/{button_id}", data={"event": "click"})
    assert refused.status_code == 400
    main_view.router.results.total.text = ""
    pages_client.post(f"/widget/{button_id}", data={"event": "click"})
    assert main_view.router.results.total.text == ""


def test_disabling_a_container_disables_the_views_in_it() -> None:
    views: list[VerticalMainView] = []

    class ColumnApp(WebApplication[VerticalMainView]):
        @override
        def setup_session(self, main_view: VerticalMainView) -> None:
            views.append(main_view)

    app = ColumnApp(build_main_view=VerticalMainView)
    with _Browser(app.create_starlette_app()) as client:
        client.get("/")
        (view,) = views
        row, column = view.tables, view.tables.column
        column.table.rows = [["North"], ["South"]]

        def disable_the_row(_rows: list[int]) -> None:
            row.is_enabled = False

        column.table.selection_changed.connect(disable_the_row)
        table_id, button_id = _widget_id(column.table.renderer), _widget_id(column.button.renderer)
        body = client.post(f"/widget/{table_id}", data={"event": "select", "row": "0"}).text

        # the row swaps whole, the views of the column inside it disabled
        swapped = _swapped(body, _widget_id(row.renderer))
        (button,) = [
            attributes for _, attributes in swapped.descendants if attributes.get("id") == button_id
        ]
        assert "disabled" in button
        assert not any(
            "hx-post" in attributes for tag, attributes in swapped.descendants if tag == "tr"
        )
        # a stale page's posts are refused, as a disabled button's or table's own
        clicked: list[bool] = []
        column.button.clicked.connect(lambda: clicked.append(True))
        assert client.post(f"/widget/{button_id}", data={"event": "click"}).status_code == 400
        selected = client.post(f"/widget/{table_id}", data={"event": "select", "row": "1"})
        assert selected.status_code == 400
        assert (column.table.selected_rows, clicked) == ([0], [])


def _holds(markup: str, container_id: str, element_id: str) -> bool:
    """Tell whether the element `container_id` of `markup` holds the element `element_id`."""
    descendants = _element(markup, container_id).descendants
    return any(attributes.get("id") == element_id for _tag, attributes in descendants)


def test_a_view_the_web_doesn_t_render_is_left_out_of_its_container() -> None:
    view = PartialMainView()
    view.render(RendererType.WEB)  # outside any session, as a test or a script does
    assert isinstance(view.renderer, WebMainRenderer)
    item = LabelView(text="Item")
    view.items.item_views = [UnregisteredView(), item]

    page = view.renderer.page_html()

    for container in (view.row, view.column, view.grid, view.splitter, view.expander, view.page):
        assert container.skipped.renderer is None
        assert _holds(page, _widget_id(container.renderer), _widget_id(container.shown.renderer))
    assert view.form.skipped.renderer is None  # a row whose field the web doesn't register
    assert _holds(page, _widget_id(view.form.renderer), _field_id(view.form.shown))
    assert _holds(page, _widget_id(view.items.renderer), _widget_id(item.renderer))
    for bar in (view.menu, view.toolbar):
        assert _holds(page, _widget_id(bar.renderer), _widget_id(bar.shown.renderer))
    view.items.item_views = []  # gone outside any session too
    assert _find(view.renderer.page_html(), _widget_id(item.renderer)) is None


def test_a_list_disabled_is_sent_whole() -> None:
    view = PipesMainView()
    view.render(RendererType.WEB)
    pipes = view.pipes.renderer
    assert isinstance(pipes, WebRenderer)

    with collect_dirty() as dirty:
        view.pipes.is_enabled = False

    assert list(dirty) == [pipes.widget_id]  # with its records' views, disabled too
