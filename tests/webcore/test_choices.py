"""Tests of the web radio groups, comboboxes, check lists and trees."""

from __future__ import annotations

import json
import sys

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from typing import TYPE_CHECKING

from composeui.core.registry import RendererType
from composeui.core.view import (
    CheckListView,
    TreeNode,
)
from composeui.webcore._renderers.choices import WebRadioGroupRenderer
from composeui.webcore.changes import collect_dirty
from composeui.webcore.session import WebSession
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import (
    UnsupportedEventError,
    WebRenderer,
    handle_event,
)
from examples.webhello import Colour, GreetingStyle, HelloMainView
from tests.buildings import SiteMainView, styled_site
from tests.choices import Base, ChoicesMainView
from tests.filters import FiltersMainView
from tests.webcore.support import (
    _HOSTILE,
    _Browser,
    _Element,
    _element,
    _field_id,
    _find,
    _HostileFinder,
    _icon_url,
    _part,
    _RowsMainView,
    _selected,
    _Shape,
    _swapped,
    _type_name,
    _widget_id,
)

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient


def _checked_keys(element: _Element) -> list[str]:
    """Get the keys of the boxes checked in a check list's `element`."""
    return [
        json.loads(attributes["hx-vals"] or "{}")["key"]
        for tag, attributes in element.descendants
        if tag == "input" and "checked" in attributes and "key" in (attributes["hx-vals"] or "")
    ]


def test_a_check_list_posts_each_box_s_state_and_swaps_only_what_it_changes() -> None:
    view = ChoicesMainView()
    session = WebSession(view)
    seen: list[list[int]] = []
    view.hours.selected_changed.connect(seen.append)
    widget_id = _widget_id(view.hours.renderer)

    def post(event: str, form: dict[str, str]) -> str:
        answer = session.handle_event(widget_id, event, form)
        assert answer is not None
        return answer[0]

    # a box posts its key and its state: the same post twice leaves the same choice
    post("toggle", {"key": "1", "checked": "on"})
    swapped = post("toggle", {"key": "1", "checked": "on"})
    assert (view.hours.selected, seen) == ([9], [[9]])
    assert "data-indeterminate" in _swapped(swapped, f"{widget_id}-all").descendants[0][1]

    swapped = post("search", {"search": "MORN"})
    assert view.hours.search == "MORN"
    assert _find(swapped, f"{widget_id}-search") is None  # the field typed in stays
    shown = _swapped(swapped, f"{widget_id}-list")
    assert (shown.text, _checked_keys(shown)) == ("Early morningMorning", ["1"])

    # partly checked, checked by the click: checks all those shown
    swapped = post("all", {"checked": "on"})
    assert (view.hours.selected, seen[-1]) == ([5, 9], [5, 9])
    assert _find(swapped, f"{widget_id}-all") is None  # the box clicked stays
    assert _checked_keys(_swapped(swapped, f"{widget_id}-list")) == ["0", "1"]
    # a page that still shows the box unchecked, the app having checked them since
    view.hours.selected = [5, 9]
    post("all", {"checked": "on"})  # checks them, as the page showed: not unchecks
    assert (view.hours.selected, len(seen)) == ([5, 9], 2)

    view.hours.values = {"Noon": 12}  # the app's change: the whole list swaps
    _swapped(post("search", {"search": ""}), widget_id)
    swapped = post("toggle", {"key": "3", "checked": "on"})  # a choice gone, from a stale page
    assert (view.hours.selected, len(seen)) == ([], 2)
    assert _swapped(swapped, f"{widget_id}-list").text == "Noon"  # shown as the view is

    view.hours.has_check_all = False
    renderer = view.hours.renderer
    assert isinstance(renderer, WebRenderer)
    html = renderer.to_html()
    assert _element(html, f"{widget_id}-all").tag == "span"  # no box, kept as a target
    session.close()


def test_a_multi_combobox_shows_the_choice_on_its_button_and_escapes_the_labels() -> None:
    view = ChoicesMainView()
    session = WebSession(view)
    field = _part(view.bases, "field")
    assert _element(field.to_html(), f"{field.widget_id}-summary").text == "None"

    answer = session.handle_event(field.widget_id, "toggle", {"key": "WEITER", "checked": "on"})

    assert answer is not None
    assert view.bases.selected == [Base.WEITER]
    assert _swapped(answer[0], f"{field.widget_id}-summary").text == "Weiter"
    view.bases.values = {_HOSTILE: Base.UNTER, "Hinter": Base.HINTER}
    view.bases.selected = [Base.UNTER]
    finder = _HostileFinder()
    finder.feed(field.to_html())
    assert (finder.found, finder.shown) == ([], 2)  # on the button and beside its box
    session.close()

    # a value's text is its key, which its box posts
    texts = CheckListView[str](values={"Hostile": _HOSTILE})
    texts.render(RendererType.WEB)
    renderer = texts.renderer
    assert isinstance(renderer, WebRenderer)
    finder = _HostileFinder()
    finder.feed(renderer.to_html())
    assert (finder.found, finder.shown) == ([], 1)


def _tree_buttons(markup: str, tree_id: str) -> dict[str, dict[str, str | None]]:
    """Get a tree's buttons by their text or name: the nodes', then "toggle " and theirs."""
    buttons: dict[str, dict[str, str | None]] = {}
    for tag, attributes in _element(markup, tree_id).descendants:
        if tag == "button":
            name = attributes.get("aria-label")
            node_id = str(attributes["id"])
            text = _element(markup, node_id).text
            buttons[f"toggle {name}" if name is not None else text] = attributes
    return buttons


def _tree_post(button: dict[str, str | None]) -> dict[str, str]:
    values = json.loads(str(button["hx-vals"]))
    assert isinstance(values, dict)
    return values


def test_a_tree_posts_its_nodes_selections_and_toggles_swapping_itself_back() -> None:
    view = SiteMainView()
    view.render(RendererType.WEB)
    site = view.site
    tree = site.renderer
    assert isinstance(tree, WebRenderer)
    selections: list[tuple[str, ...]] = []
    toggles: list[tuple[tuple[str, ...], bool]] = []
    site.selection_changed.connect(selections.append)
    site.toggled.connect(lambda path, is_expanded: toggles.append((path, is_expanded)))
    site.nodes = [*site.nodes, TreeNode("<Garden>")]
    buttons = _tree_buttons(tree.to_html(), tree.widget_id)
    # a collapsed node's children left out; a leaf has no arrow
    assert list(buttons) == [
        "toggle Building A",
        "Building A",
        "toggle Floor 1",
        "Floor 1",
        "toggle Floor 2",
        "Floor 2",
        "toggle Building B",
        "Building B",
        "Parking",
        "<Garden>",  # escaped, shown as text
    ]
    assert buttons["toggle Building A"]["aria-expanded"] == "true"
    assert buttons["toggle Building B"]["aria-expanded"] == "false"

    fragments = handle_event(tree, "select", _tree_post(buttons["Floor 2"]))
    assert (site.selected, selections) == (("Building A", "Floor 2"), [("Building A", "Floor 2")])
    _swapped(fragments, tree.widget_id)  # to show it selected
    buttons = _tree_buttons(fragments, tree.widget_id)
    assert buttons["Floor 2"]["aria-current"] == "true"
    assert "aria-current" not in buttons["Floor 1"]
    handle_event(tree, "select", _tree_post(buttons["Floor 2"]))  # already selected
    assert len(selections) == 1

    fragments = handle_event(tree, "toggle", _tree_post(buttons["toggle Building B"]))
    assert site.expanded == [("Building A",), ("Building B",)]
    assert toggles == [(("Building B",), True)]
    # each button keeping its id, for htmx to give the focus back
    swapped = _tree_buttons(fragments, tree.widget_id)
    assert swapped["toggle Building B"]["aria-expanded"] == "true"
    assert swapped["Building B"]["id"] == buttons["Building B"]["id"]
    handle_event(tree, "toggle", _tree_post(buttons["toggle Building B"]))  # posted twice
    assert len(toggles) == 1

    # a node a stale page still shows: the tree swapped back, nothing selected
    site.nodes = site.nodes[:1]
    fragments = handle_event(tree, "select", _tree_post(buttons["Parking"]))
    assert "Parking" not in _swapped(fragments, tree.widget_id).text
    handle_event(tree, "toggle", {"path": "not json", "expanded": "true"})
    assert (len(selections), len(toggles)) == (1, 1)

    site.is_enabled = False
    assert all("disabled" in b for b in _tree_buttons(tree.to_html(), tree.widget_id).values())
    with pytest.raises(UnsupportedEventError):  # the route answers 400
        handle_event(tree, "select", _tree_post(buttons["Building A"]))


def test_a_tree_shows_its_nodes_icon_style_and_mark_described_to_screen_readers(
    tmp_path: Path,
) -> None:
    icon = tmp_path / "building.png"
    icon.write_bytes(b"\x89PNG\r\n\x1a\n")
    view = SiteMainView()
    view.render(RendererType.WEB)
    site = view.site
    tree = site.renderer
    assert isinstance(tree, WebRenderer)
    site.nodes = styled_site(str(icon))
    markup = tree.to_html()
    building, done, failed, parking = (
        _element(markup, f"{tree.widget_id}-node-{position}") for position in range(4)
    )
    assert _icon_url(building).startswith("/icon/")
    assert not any(tag == "img" or "style" in attributes for tag, attributes in parking.descendants)
    classes = [
        set(str(attributes.get("class")).split())
        for element in (building, parking)
        for tag, attributes in element.descendants
        if tag == "span" and "class" in attributes
    ]
    assert classes == [
        {"truncate", "font-bold"},
        {"truncate", "underline"},
        {"shrink-0", "text-warning"},
    ]
    assert "aria-describedby" not in building.attributes
    # the mark's icon unread, its name read after the label naming the button
    for button, name in ((done, "Done"), (failed, "Error"), (parking, "Warning")):
        mark = _element(markup, str(button.attributes["aria-describedby"]))
        assert "hidden" in mark.attributes
        assert mark.text == name

    site.done_text = "<Terminé>"  # as the main view's language changes, escaped
    markup = tree.to_html()
    done = _element(markup, f"{tree.widget_id}-node-1")
    assert _element(markup, str(done.attributes["aria-describedby"])).text == "<Terminé>"


def test_page_renders_the_choices(main_view: HelloMainView, client: TestClient) -> None:
    page = client.get("/").text
    style_id = _field_id(main_view.form.style)

    style = _element(page, style_id)
    radios = [attributes for tag, attributes in style.descendants if tag == "input"]
    assert style.attributes["role"] == "radiogroup"
    # keyed by the enum members' names, which no language changes
    assert [radio["value"] for radio in radios] == ["CASUAL", "FORMAL"]
    # one radio set per group: named after the group's own id
    assert {radio["name"] for radio in radios} == {style_id}
    assert _selected(style) == ["CASUAL"]
    colour = _element(page, _field_id(main_view.form.colour))
    options = [attributes["value"] for tag, attributes in colour.descendants if tag == "option"]
    assert options == ["", "RED", "GREEN", "BLUE"]
    assert _selected(colour) == [""]  # nothing chosen yet: the empty choice


def test_choosing_a_style_regreets_without_swapping_the_radio_group(
    main_view: HelloMainView, client: TestClient
) -> None:
    style_id = _field_id(main_view.form.style)
    _type_name(client, main_view, "Bob")

    body = client.post(f"/widget/{style_id}", data={style_id: "FORMAL", "event": "change"}).text

    assert main_view.form.style.value is GreetingStyle.FORMAL
    assert _swapped(body, _widget_id(main_view.status_bar.renderer)).text == "Good day, Bob."
    assert _find(body, style_id) is None


def test_choosing_a_colour_updates_the_summary(
    main_view: HelloMainView, client: TestClient
) -> None:
    colour_id = _field_id(main_view.form.colour)
    summary_id = _widget_id(main_view.summary.renderer)

    body = client.post(f"/widget/{colour_id}", data={colour_id: "BLUE", "event": "change"}).text

    assert main_view.form.colour.value is Colour.BLUE
    assert _swapped(body, summary_id).text == "Nobody hasn't said how old they are and likes blue."
    assert _find(body, colour_id) is None

    # the empty choice clears the colour again
    body = client.post(f"/widget/{colour_id}", data={colour_id: "", "event": "change"}).text

    assert main_view.form.colour.value is None
    assert _swapped(body, summary_id).text == "Nobody hasn't said how old they are."


def test_an_unknown_choice_clears_the_value_instead_of_failing(
    main_view: HelloMainView, client: TestClient
) -> None:
    colour_id = _field_id(main_view.form.colour)
    main_view.form.colour.value = Colour.RED

    response = client.post(f"/widget/{colour_id}", data={colour_id: "Purple", "event": "change"})

    assert response.status_code == 200
    assert main_view.form.colour.value is None


def test_choosing_the_current_value_again_does_not_re_emit(
    main_view: HelloMainView, client: TestClient
) -> None:
    style = main_view.form.style
    style_id = _field_id(style)
    emitted: list[GreetingStyle | None] = []

    style.value_changed.connect(emitted.append)

    for _ in range(2):
        client.post(f"/widget/{style_id}", data={style_id: "FORMAL", "event": "change"})

    assert emitted == [GreetingStyle.FORMAL]


def test_replacing_the_values_rerenders_the_options(main_view: HelloMainView) -> None:
    style = main_view.form.style
    renderer = _part(style, "field")
    assert isinstance(renderer, WebRadioGroupRenderer)
    style.value = GreetingStyle.FORMAL

    with collect_dirty() as dirty:
        # drops the current value, which `_reconcile_values` clears
        style.values = {"Casual": GreetingStyle.CASUAL}

    assert list(dirty) == [renderer.widget_id]
    assert style.value is None
    group = _element(renderer.to_html(), renderer.widget_id)
    radios = [attributes for tag, attributes in group.descendants if tag == "input"]
    assert [radio.get("value") for radio in radios] == ["CASUAL"]
    assert _selected(group) == []


def test_a_disabled_radio_group_disables_every_radio(main_view: HelloMainView) -> None:
    style = main_view.form.style
    field = _part(style, "field")
    assert isinstance(field, WebRadioGroupRenderer)

    style.is_enabled = False

    group = _element(field.to_html(), field.widget_id)
    radios = [attributes for tag, attributes in group.descendants if tag == "input"]
    assert len(radios) == 2
    assert all("disabled" in radio for radio in radios)


def test_a_radio_row_label_does_not_point_at_the_group(rows: _RowsMainView) -> None:
    label, field = _part(rows.shape, "label"), _part(rows.shape, "field")

    # a `<div>` isn't labelable: `for=` would point at nothing
    assert "for" not in _element(label.to_html(), label.widget_id).attributes

    handle_event(field, "change", {field.widget_id: "SQUARE"})

    assert rows.shape.value is _Shape.SQUARE


def test_a_tree_ignores_a_path_that_isn_t_a_list_of_names() -> None:
    view = SiteMainView()
    view.render(RendererType.WEB)
    tree = view.site.renderer
    assert isinstance(tree, WebRenderer)
    toggles: list[object] = []
    view.site.toggled.connect(lambda path, _is_expanded: toggles.append(path))

    for posted in ('{"Building A": 1}', "[1]", "not json"):  # e.g. sent by hand
        handle_event(tree, "toggle", {"path": posted})

    assert toggles == []
    assert view.site.expanded == [("Building A",)]


def test_a_none_choice_is_shown_selected_and_picked_back() -> None:
    views: list[FiltersMainView] = []

    class FiltersApp(WebApplication[FiltersMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=FiltersMainView)

        @override
        def setup_session(self, main_view: FiltersMainView) -> None:
            views.append(main_view)

    with _Browser(FiltersApp().create_starlette_app()) as client:
        page = client.get("/").text
        (main_view,) = views
        region, shown = main_view.form.region, main_view.form.shown
        region_id = _field_id(region)
        combobox = _element(page, region_id)
        options = [
            attributes["value"] for tag, attributes in combobox.descendants if tag == "option"
        ]

        # no empty option: "All regions" is a choice, and the one selected
        assert options == ["0", "north", "south"]
        assert _selected(combobox) == ["0"]
        assert _selected(_element(page, _field_id(shown))) == ["0"]
        region.value = "south"
        client.post(f"/widget/{region_id}", data={region_id: "0", "event": "change"})

    assert region.value is None
