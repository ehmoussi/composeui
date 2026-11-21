"""Tests of the Textual radio groups, comboboxes, check lists and trees."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

import asyncio

from rich.color import Color
from rich.style import Style
from textual.widgets import (
    Select,
)
from textual.widgets.collapsible import CollapsibleTitle

from composeui.core.registry import RendererType
from composeui.core.view import (
    TreeNode,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composechecklist import ComposeCheckList, ComposeMultiComboBox
from composeui.textualcore.widgets.composecombobox import ComposeComboBox
from composeui.textualcore.widgets.composeradioset import ComposeRadioSet
from composeui.textualcore.widgets.composetree import ComposeTree
from examples.pipeform import EdgeType, Material, PipeMainView
from tests.buildings import SiteMainView, styled_site
from tests.choices import Base, ChoicesMainView
from tests.filters import FiltersMainView
from tests.textualcore.support import _app_of, _field_widget, _widget
from tests.translated import TranslatedMainView


@pytest.mark.asyncio
async def test_a_check_list_checks_the_view_s_values_its_check_all_box_those_the_search_shows() -> (
    None
):
    view = ChoicesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    renderer = view.hours.renderer
    assert isinstance(renderer, TextualWidgetRenderer)
    check_list = renderer.widget
    assert isinstance(check_list, ComposeCheckList)
    seen: list[list[int]] = []
    view.hours.selected_changed.connect(seen.append)

    async with app.run_test() as pilot:
        await pilot.pause()
        check_list.search_input.focus()
        await pilot.press(*"MORN")
        await pilot.pause()
        prompts = [str(option.prompt) for option in check_list.choices.options]
        assert (view.hours.search, prompts) == ("MORN", ["Early morning", "Morning"])
        check_list.choices.focus()
        await pilot.press("home", "down", "space")
        await pilot.pause()
        assert (view.hours.selected, seen) == ([9], [[9]])
        assert check_list.check_all.BUTTON_INNER == "-"  # partly checked

        check_list.check_all.focus()
        await pilot.press("space")  # partly checked: checks all those shown
        await pilot.pause()
        assert (view.hours.selected, seen[-1]) == ([5, 9], [5, 9])
        assert (check_list.check_all.value, check_list.check_all.BUTTON_INNER) == (True, "X")

        view.hours.search = ""  # set in code: the list follows, and nothing is reported
        view.hours.selected = [12]
        await pilot.pause()
        assert check_list.choices.selected == ["2"]  # the key of 12: its position
        assert check_list.check_all.BUTTON_INNER == "-"
        assert len(seen) == 2

        view.hours.values = {"Dawn": 5, "Day": 9, "Dusk": 12, "Night": 19}  # the same keys
        await pilot.pause()
        prompts = [str(option.prompt) for option in check_list.choices.options]
        assert prompts == ["Dawn", "Day", "Dusk", "Night"]


@pytest.mark.asyncio
async def test_a_multi_combobox_is_a_collapsible_titled_with_the_choice() -> None:
    view = ChoicesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    combobox = _field_widget(view.bases.renderer)
    assert isinstance(combobox, ComposeMultiComboBox)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert (combobox.title, combobox.collapsed) == ("None", True)
        await pilot.click(combobox.query_one(CollapsibleTitle))
        await pilot.pause()
        combobox.check_list.choices.focus()
        await pilot.press("home", "down", "down", "space")
        await pilot.pause()
        assert (view.bases.selected, combobox.title) == ([Base.WEITER], "Weiter")
        view.bases.selected = [Base.UNTER, Base.HINTER]
        await pilot.pause()
        assert combobox.title == "2 selected"


@pytest.mark.asyncio
async def test_textual_radio_group_with_nonnull_initial_value_mounts_without_crashing() -> None:
    """A radio group whose `value` is already non-None on first render used to crash.

    `refresh()` fires "values" (rebuild) and "value" (select) back to back; the
    rebuild's `remove_children()`/`mount()` are asynchronous, so selecting a button
    before that rebuild actually lands raced with it - Textual's own `RadioSet`
    then crashed trying to look up a button that had since been removed.
    `EdgeTypeView` in `examples/pipeform.py` sets a non-None `value` right after
    `values` in `__attrs_post_init__`, which triggers exactly this path.
    """
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        widget = _field_widget(view.pages.inputs.pipe_form.edge_type.renderer)
        assert isinstance(widget, ComposeRadioSet)
        assert widget.value() == EdgeType.Normal
        assert view.pages.inputs.pipe_form.edge_type.value == EdgeType.Normal


@pytest.mark.asyncio
async def test_a_radio_group_shows_no_choice_when_its_value_or_its_choice_is_gone() -> None:
    view = PipeMainView()
    app = _app_of(view)
    edge = view.pages.inputs.pipe_form.edge_type
    changes: list[object] = []

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        widget = _field_widget(edge.renderer)
        assert isinstance(widget, ComposeRadioSet)
        assert widget.pressed_index != -1
        edge.value_changed.connect(changes.append)  # after its first value shows

        edge.value = None
        await pilot.pause()
        await pilot.pause()
        assert widget.pressed_index == -1
        assert changes == []

        edge.value = EdgeType.Chamfer
        await pilot.pause()
        await pilot.pause()
        assert widget.value() == EdgeType.Chamfer
        edge.values = {"Normal": EdgeType.Normal}  # without the choice selected
        await pilot.pause()
        await pilot.pause()
        assert edge.value is None
        assert widget.pressed_index == -1


def _tree_lines(tree: ComposeTree) -> list[tuple[str, bool]]:
    """Get a tree's lines as shown: each node's label, and whether it is marked selected."""
    lines = []
    for line in range(tree.last_line + 1):
        node = tree.get_node_at_line(line)
        assert node is not None
        label = tree.render_label(node, Style(), Style())
        is_marked = any(isinstance(span.style, Style) and span.style.bold for span in label.spans)
        lines.append((label.plain, is_marked))
    return lines


@pytest.mark.asyncio
async def test_a_tree_selects_its_nodes_by_enter_or_click_and_expands_them_by_space() -> None:
    view = SiteMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    site = view.site
    assert isinstance(site.renderer, TextualWidgetRenderer)
    tree = site.renderer.widget
    assert isinstance(tree, ComposeTree)
    selections: list[tuple[str, ...]] = []
    toggles: list[tuple[tuple[str, ...], bool]] = []
    site.selection_changed.connect(selections.append)
    site.toggled.connect(lambda path, is_expanded: toggles.append((path, is_expanded)))

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert [label for label, _ in _tree_lines(tree)] == [
            "▼ Building A",
            "▶ Floor 1",
            "▶ Floor 2",
            "▶ Building B",
            "Parking",
        ]
        await pilot.click(tree, offset=(8, 2))
        await pilot.pause()
        assert (site.selected, selections) == (
            ("Building A", "Floor 2"),
            [("Building A", "Floor 2")],
        )
        assert _tree_lines(tree)[2] == ("▶ Floor 2", True)
        assert site.expanded == [("Building A",)]  # a click selects, without toggling

        tree.focus()
        await pilot.press("space")  # the node under the cursor
        await pilot.pause()
        assert site.expanded == [("Building A",), ("Building A", "Floor 2")]
        assert toggles == [(("Building A", "Floor 2"), True)]
        await pilot.press("down", "enter")
        await pilot.pause()
        assert selections[-1] == ("Building A", "Floor 2", "Room 201")
        assert [marked for _, marked in _tree_lines(tree)] == [
            False,
            False,
            False,
            True,
            False,
            False,
        ]

        # set in code: shown, and not reported
        site.expanded = []
        site.selected = ("Parking",)
        await pilot.pause()
        assert _tree_lines(tree) == [
            ("▶ Building A", False),
            ("▶ Building B", False),
            ("Parking", True),
        ]
        assert (len(selections), len(toggles)) == (2, 1)
        site.nodes = [*site.nodes, TreeNode("Garden")]
        await pilot.pause()
        assert _tree_lines(tree)[-2:] == [("Parking", True), ("Garden", False)]


@pytest.mark.asyncio
async def test_a_tree_shows_its_nodes_style_and_mark_after_the_label() -> None:
    view = SiteMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    site = view.site
    assert isinstance(site.renderer, TextualWidgetRenderer)
    tree = site.renderer.widget
    assert isinstance(tree, ComposeTree)

    async with app.run_test(size=(80, 30)) as pilot:
        site.nodes = styled_site("building.png")  # a terminal shows no icon
        site.selected = ("Building A", "Room 101")
        await pilot.pause()
        labels = {}
        for line in range(tree.last_line + 1):
            node = tree.get_node_at_line(line)
            assert node is not None
            label = tree.render_label(node, Style(), Style())
            labels[label.plain] = label
        assert list(labels) == ["▼ Building A", "Room 101 ✓", "Room 102 ✗", "Parking !"]

        def style_of(label: str, text: str) -> Style:
            start = label.index(text)
            return labels[label].get_style_at_offset(app.console, start)

        assert style_of("▼ Building A", "Building").bold
        assert not style_of("▼ Building A", "Building").underline
        assert style_of("Parking !", "Parking").underline
        assert not style_of("Parking !", "Parking").bold
        # the mark in its own color, the selected label's left out
        selected, done = style_of("Room 101 ✓", "Room"), style_of("Room 101 ✓", "✓")
        assert selected.color != done.color
        assert {
            done.color,
            style_of("Room 102 ✗", "✗").color,
            style_of("Parking !", "!").color,
        } == {
            Color.parse("green"),
            Color.parse("red"),
            Color.parse("orange1"),
        }


@pytest.mark.asyncio
async def test_a_combobox_emits_its_value_when_the_user_picks_it_not_when_code_sets_it() -> None:
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    material = view.pages.inputs.pipe_form.material
    seen: list[object] = []
    material.value_changed.connect(seen.append)

    async with app.run_test() as pilot:
        await pilot.pause()
        material.values = dict(reversed(material.values.items()))
        material.value = Material.Copper
        await pilot.pause()
        assert seen == []

        combobox = _field_widget(material.renderer)
        assert isinstance(combobox, ComposeComboBox)
        combobox.value = Material.Steel  # what picking an option does
        await pilot.pause()
        assert seen == [Material.Steel]
        assert material.value is Material.Steel


@pytest.mark.asyncio
async def test_a_tree_reports_a_node_selected_once_and_its_collapse() -> None:
    view = SiteMainView()
    app = _app_of(view)
    site = view.site
    tree = _widget(site)
    selections: list[tuple[str, ...]] = []
    toggles: list[tuple[tuple[str, ...], bool]] = []
    site.selection_changed.connect(selections.append)
    site.toggled.connect(lambda path, is_expanded: toggles.append((path, is_expanded)))

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        tree.focus()
        await pilot.press("down", "enter", "enter")  # the top node, twice
        await pilot.press("space")  # it was expanded
        await pilot.pause()

        assert selections == [("Building A",)]
        assert toggles == [(("Building A",), False)]


@pytest.mark.asyncio
async def test_a_combobox_without_a_value_shows_none() -> None:
    view = TranslatedMainView()
    app = _app_of(view)
    combobox = _field_widget(view.shape.size.renderer)
    assert isinstance(combobox, ComposeComboBox)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        view.shape.size.value = None
        await pilot.pause()

        assert combobox.is_blank()


@pytest.mark.asyncio
async def test_a_none_choice_is_shown_selected_and_picked_back() -> None:
    view = FiltersMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    region, shown = view.form.region, view.form.shown
    picked: list[object] = []
    region.value_changed.connect(picked.append)

    async with app.run_test() as pilot:
        combobox = _field_widget(region.renderer)
        radios = _field_widget(shown.renderer)
        assert isinstance(combobox, ComposeComboBox)
        assert isinstance(radios, ComposeRadioSet)
        await asyncio.wait_for(combobox.wait_for_refresh(), timeout=5)
        await pilot.pause()
        assert combobox.value is None  # the "All regions" option, not Select.NULL
        assert radios.pressed_index == 0
        region.value = "south"
        await asyncio.wait_for(combobox.wait_for_refresh(), timeout=5)
        await pilot.pause()

        combobox.value = None  # what picking "All regions" does
        await pilot.pause()
        assert (region.value, picked) == (None, [None])

        region.values = {"North": "north"}  # no None among them: None selects nothing again
        await asyncio.wait_for(combobox.wait_for_refresh(), timeout=5)
        await pilot.pause()

        assert combobox.value is Select.NULL
