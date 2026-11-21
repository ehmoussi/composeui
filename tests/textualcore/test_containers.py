"""Tests of the Textual containers: pages, rows, grids, splitters, expanders, tabs, lists."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

from typing import TYPE_CHECKING

from attrs import Factory
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import (
    Button,
    Label,
    TabPane,
)
from textual.widgets.collapsible import CollapsibleTitle

from composeui.core.application import _add_reference_to_signals
from composeui.core.registry import RendererType
from composeui.core.view import (
    LabelView,
    MainView,
    TabPage,
    TabView,
    View,
    define_view,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composecollapsible import ComposeCollapsible
from composeui.textualcore.widgets.composesplitter import ComposeSplitter, SplitterHandle
from composeui.textualcore.widgets.composetabbedcontent import ComposeTabbedContent
from composeui.textualcore.widgets.composetoolbar import ComposeToolbarButton
from examples.pipeform import EdgeType, PipeMainView
from tests.expander import RecordMainView
from tests.grid import GridMainView
from tests.horizontal import ButtonsMainView, HorizontalMainView, ManyButtonsMainView
from tests.listview import PIPES, Pipe, PipeExpander, PipesMainView
from tests.pages import PagesMainView
from tests.partial import PartialMainView, UnregisteredView
from tests.splitter import SplitterMainView, VerticalSplitterMainView
from tests.tabs import TabsMainView
from tests.vertical import VerticalMainView

if TYPE_CHECKING:
    from composeui.core.view import View

from tests.textualcore.support import _app_of, _field_widget, _widget


@pytest.mark.asyncio
async def test_content_taller_than_the_terminal_is_reachable_by_scrolling() -> None:
    """Toggling a hidden `GroupFormView` visible can grow the form past screen height.

    A plain `Vertical` clips anything past the screen's height instead of making it
    reachable - there'd be no way to see the rest of the form (e.g. `chamfer`'s
    fields, revealed by picking `EdgeType.Chamfer`) with no scrollbar or resize to
    fall back on, unlike a real (resizable) Qt window. `TextualMainRenderer` wraps
    the form content in a `VerticalScroll` for exactly this; `StatusBar` is kept
    outside of it so it stays docked to the actual bottom of the terminal.
    """
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        view.pages.inputs.pipe_form.edge_type.value = EdgeType.Chamfer
        await pilot.pause()

        chamfer_renderer = view.pages.inputs.pipe_form.chamfer.renderer
        assert isinstance(chamfer_renderer, TextualWidgetRenderer)
        chamfer_widget = chamfer_renderer.widget
        assert chamfer_widget is not None
        screen_height = app.screen.size.height
        # past the bottom of the terminal before scrolling
        assert chamfer_widget.region.y >= screen_height

        scroller = app.screen.query_one(VerticalScroll)
        assert scroller.max_scroll_y > 0  # there's actually overflow to scroll through
        scroller.scroll_end(animate=False)
        await pilot.pause()
        assert chamfer_widget.region.y < screen_height  # reachable now


@pytest.mark.asyncio
async def test_a_horizontal_view_shares_the_row_by_stretch() -> None:
    view = HorizontalMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    widgets = []
    for table in (view.tables.narrow, view.tables.wide, view.tables):
        assert isinstance(table.renderer, TextualWidgetRenderer)
        assert table.renderer.widget is not None
        widgets.append(table.renderer.widget)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        narrow, wide, row = (widget.region for widget in widgets)
        assert narrow.y == wide.y
        assert narrow.right <= wide.x
        assert wide.width == pytest.approx(3 * narrow.width, rel=0.02)
        # the hidden table takes no share: the two shown span the row
        assert (narrow.x, wide.right) == (row.x, row.right)


@pytest.mark.asyncio
async def test_a_vertical_view_stacks_its_views_at_its_top() -> None:
    view = VerticalMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    widgets = []
    for child in (view.tables.column.table, view.tables.column.button, view.tables.tall):
        assert isinstance(child.renderer, TextualWidgetRenderer)
        assert child.renderer.widget is not None
        widgets.append(child.renderer.widget)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table, button, tall = (widget.region for widget in widgets)
        assert table.y == tall.y
        assert button.y == table.bottom
        # next to a taller table, the column's spare height is left below its views
        assert button.bottom < tall.bottom


@pytest.mark.asyncio
async def test_a_grid_view_places_its_views_in_equally_wide_columns() -> None:
    view = GridMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    widgets = []
    for child in (view.tables.first, view.tables.button, view.tables.spanning, view.tables):
        assert isinstance(child.renderer, TextualWidgetRenderer)
        assert child.renderer.widget is not None
        widgets.append(child.renderer.widget)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        first, button, spanning, grid = (widget.region for widget in widgets)
        assert (first.x, first.y, button.y) == (grid.x, grid.y, grid.y)
        assert first.width == grid.width // 3
        # the hidden table's column is kept: the button is in the third one
        assert button.x == grid.x + 2 * first.width
        # as wide as its text, unlike the table filling its column
        assert button.width < first.width // 2
        # the next row starts below the taller of the views above it, spanning the columns
        assert (spanning.x, spanning.y, spanning.right) == (grid.x, first.bottom, grid.right)


@pytest.mark.asyncio
async def test_buttons_with_no_share_pack_at_their_row_s_start_or_end() -> None:
    view = ButtonsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    def widget(of: View) -> Widget:
        assert isinstance(of.renderer, TextualWidgetRenderer)
        assert isinstance(of.renderer.widget, Widget)
        return of.renderer.widget

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        for row, packed_at_end in (
            (view.start, False),
            (view.end, True),
            # the table with a share hidden: the free width still goes before the buttons
            (view.beside_hidden, True),
        ):
            first, second = widget(row.first).region, widget(row.second).region
            row_region = widget(row).region
            # as wide as their text, side by side
            assert first.width < row_region.width // 4
            assert second.x - first.right < 4
            if packed_at_end:
                assert second.right == row_region.right
            else:
                assert first.x == row_region.x


@pytest.mark.asyncio
async def test_buttons_with_no_share_wrap_onto_lines_as_wide_as_their_row() -> None:
    view = ManyButtonsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    def widget(of: View) -> Widget:
        assert isinstance(of.renderer, TextualWidgetRenderer)
        assert isinstance(of.renderer.widget, Widget)
        return of.renderer.widget

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        bottom = 0
        for row, packed_at_end in (
            (view.start, False),
            (view.end, True),
            (view.beside.buttons, False),
        ):
            row_region = widget(row).region
            boxes = [widget(button).region for button in row.buttons]
            # each within the row: none cut off
            assert all(row_region.contains_region(box) for box in boxes)
            first, last = boxes[0], boxes[-1]
            # side by side, the last ones on another line, and the row as tall as its lines
            assert boxes[1].y == first.y
            assert last.y >= first.bottom
            assert row_region.y >= bottom
            bottom = last.bottom
            if packed_at_end:
                assert last.right == row_region.right
            else:
                assert first.x == row_region.x
        # a note longer than the row wraps within it, its button beside or below it
        row_region = widget(view.noted).region
        note, retry = widget(view.noted.note).region, widget(view.noted.retry).region
        assert row_region.contains_region(note)
        assert note.height > 1
        assert row_region.contains_region(retry)
        assert widget(view.below).region.y >= max(note.bottom, retry.bottom)


@pytest.mark.asyncio
async def test_a_list_view_shows_a_view_per_record_as_the_records_change() -> None:
    view = PipesMainView()
    view.status_bar.timeout = 0
    _add_reference_to_signals(view, None)
    view.pipes.items = PIPES[:1]  # before rendering, as at startup
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.pipes.renderer, TextualWidgetRenderer)
    column = view.pipes.renderer.widget
    assert column is not None

    def shown(container: Widget) -> list[str]:
        return [
            str(child.title)
            for child in container.children
            if isinstance(child, ComposeCollapsible)
        ]

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        assert shown(column) == ["Main line"]
        main_line = view.pipes.item_views[0]
        assert isinstance(main_line.renderer, TextualWidgetRenderer)
        main_line_widget = main_line.renderer.widget

        view.pipes.items = [Pipe("Feed", 1), *PIPES]  # built since: mounted as they come
        await pilot.pause()
        assert shown(column) == ["Feed", "Main line", "Return"]
        # collapsed, a line apart: a rule, then the title
        assert [child.region.height for child in column.children] == [2, 2, 2]
        assert column.children[1] is main_line_widget  # the record's own widget
        feed = view.pipes.item_views[0]
        assert isinstance(feed, PipeExpander)
        feed.is_expanded = True
        await pilot.pause()
        assert isinstance(feed.length.renderer, TextualWidgetRenderer)
        length = feed.length.renderer.widget
        assert isinstance(length, Label)
        assert str(length.render()) == "Length: 1 m"  # its state, given once mounted

        assert isinstance(feed.delete.renderer, TextualWidgetRenderer)
        delete = feed.delete.renderer.widget
        assert delete is not None
        await pilot.click(delete)
        await pilot.pause()
        assert shown(column) == ["Main line", "Return"]
        assert view.status_bar.message == "Deleted Feed"


@pytest.mark.asyncio
async def test_a_tab_view_shows_the_tab_the_user_picks() -> None:
    view = TabsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    tabs = view.tabs
    assert isinstance(tabs.renderer, TextualWidgetRenderer)
    tabbed = tabs.renderer.widget
    assert isinstance(tabbed, ComposeTabbedContent)
    panes = []
    for tab in tabs.tabs:
        assert isinstance(tab.renderer, TextualWidgetRenderer)
        pane = tab.renderer.widget
        assert isinstance(pane, TabPane)
        panes.append(pane)
    details, history, notes = panes
    assert isinstance(history, TabPane)
    assert isinstance(notes, TabPane)
    picks: list[int] = []
    tabs.current_changed.connect(picks.append)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert [str(tabbed.get_tab(pane).label) for pane in panes] == [
            "Details",
            "History",
            "Notes",
        ]
        assert tabbed.active_pane is details

        await pilot.click(tabbed.get_tab(history))
        await pilot.pause()
        assert (tabs.current_index, picks) == (1, [1])
        assert tabbed.active_pane is history

        tabs.current_index = 0  # set in code: shown, and not reported
        await pilot.pause()
        assert (tabbed.active_pane, picks) == (details, [1])
        tabs.history.title = "Changes"
        tabs.notes.is_enabled = False
        tabs.notes.is_visible = False
        await pilot.pause()
        assert str(tabbed.get_tab(history).label) == "Changes"
        assert tabbed.get_tab(notes).disabled
        assert not tabbed.get_tab(notes).display


@pytest.mark.asyncio
async def test_an_expander_shows_its_views_while_expanded_by_its_title() -> None:
    view = RecordMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    record, history = view.record, view.record.history
    toggles: list[bool] = []
    history_toggles: list[bool] = []
    record.toggled.connect(toggles.append)
    history.toggled.connect(history_toggles.append)
    widgets = [
        renderer.widget
        for renderer in (record.renderer, history.renderer, record.buttons.edit.renderer)
        if isinstance(renderer, TextualWidgetRenderer)
    ]
    expander, history_expander, edit = widgets
    assert isinstance(expander, ComposeCollapsible)
    assert isinstance(history_expander, ComposeCollapsible)
    assert isinstance(edit, Button)

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert expander.title == "Pipe A"
        assert edit.region.area == 0  # collapsed: not laid out

        await pilot.click(expander.query_one(CollapsibleTitle))
        await pilot.pause()
        assert (record.is_expanded, toggles) == (True, [True])
        assert edit.region.area > 0
        # the nested expander's toggle is its own
        history_expander.query_one(CollapsibleTitle).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert (history.is_expanded, history_toggles, toggles) == (True, [True], [True])
        await pilot.press("enter")  # and back
        await pilot.pause()
        assert (history.is_expanded, history_toggles) == (False, [True, False])
        await pilot.press("enter")
        await pilot.pause()

        record.is_expanded = False  # set in code: collapsed, and not reported
        await pilot.pause()
        assert edit.region.area == 0
        assert toggles == [True]


@pytest.mark.asyncio
async def test_a_splitter_shares_its_width_as_its_sizes_and_takes_the_users_drags() -> None:
    view = SplitterMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    splitter = view.splitter
    assert isinstance(splitter.renderer, TextualWidgetRenderer)
    widget = splitter.renderer.widget
    assert isinstance(widget, ComposeSplitter)

    async with app.run_test(size=(84, 20)) as pilot:
        await pilot.pause()
        study, settings, result = widget.pane_lengths()
        assert study == pytest.approx(settings, abs=1)  # rounded to cells
        assert result == pytest.approx(2 * study, abs=2)
        resizes: list[list[int]] = []
        splitter.resized.connect(resizes.append)
        first, second = widget.query(SplitterHandle)
        # the borders as tall as the panes, not the screen
        assert first.region.height == widget.region.height == 1

        # on the screen: the handle follows the mouse
        dragged_to = (first.region.x + 6, first.region.y)
        await pilot.mouse_down(first)
        await pilot.hover(None, offset=dragged_to)
        await pilot.mouse_up(None, offset=dragged_to)
        await pilot.pause()
        widths = widget.pane_lengths()
        assert widths == [study + 6, settings - 6, result]
        assert splitter.sizes == [round(100 * width / sum(widths)) for width in widths]
        assert resizes == [splitter.sizes]  # once dropped
        await pilot.click(second)  # a click: nothing moves, nothing reported
        assert len(resizes) == 1
        second.focus()  # the arrow keys move a focused border
        # Both keys can arrive before the next layout, especially on Windows.
        with app.batch_update():
            await pilot.press("left", "left")
        await pilot.pause()
        assert widget.pane_lengths()[2] == result + 2
        assert len(resizes) == 3

        splitter.sizes = [1, 1, 1]  # set in code: shared alike, and not reported
        await pilot.pause()
        assert len(resizes) == 3
        study, settings, result = widget.pane_lengths()
        assert study == pytest.approx(settings, abs=1)
        assert study == pytest.approx(result, abs=1)
        splitter.settings.is_visible = False  # its width to the others, its share kept
        await pilot.pause()
        assert widget.pane_lengths()[1] == 0
        assert (first.display, second.display) == (False, True)
        study, _, result = widget.pane_lengths()
        await pilot.press("right")  # the study's border, now
        await pilot.pause()
        assert widget.pane_lengths() == [study + 1, 0, result - 1]
        assert splitter.sizes == [
            round(100 * (study + 1) / (study + result)),
            1,
            round(100 * (result - 1) / (study + result)),
        ]


@pytest.mark.asyncio
async def test_a_splitter_keeps_its_panes_through_a_language_switch() -> None:
    view = SplitterMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(84, 20)) as pilot:
        await pilot.pause()
        view.set_language("fr")  # its borders' name is the web's only
        await pilot.pause()

        assert view.splitter.border_text == "Redimensionner les volets"
        assert isinstance(view.splitter.renderer, TextualWidgetRenderer)
        widget = view.splitter.renderer.widget
        assert isinstance(widget, ComposeSplitter)
        assert len(widget.pane_lengths()) == 3


@pytest.mark.asyncio
async def test_a_vertical_splitter_shares_its_rows_and_moves_its_border_up_and_down() -> None:
    view = VerticalSplitterMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    splitter = view.splitter
    assert isinstance(splitter.renderer, TextualWidgetRenderer)
    widget = splitter.renderer.widget
    assert isinstance(widget, ComposeSplitter)

    async with app.run_test(size=(60, 40)) as pilot:
        await pilot.pause()
        chart, table = widget.pane_lengths()
        assert chart + table + 1 == widget.region.height == 24  # and the border's row
        assert chart == pytest.approx(2 * table, abs=1)
        handle = widget.query_one(SplitterHandle)
        assert (handle.region.width, handle.region.height) == (widget.region.width, 1)

        dragged_to = (handle.region.x + 5, handle.region.y + 4)
        await pilot.mouse_down(handle, offset=(5, 0))
        await pilot.hover(None, offset=dragged_to)
        await pilot.mouse_up(None, offset=dragged_to)
        await pilot.pause()
        assert widget.pane_lengths() == [chart + 4, table - 4]
        handle.focus()
        await pilot.press("left", "right")  # across the border: nothing moves
        await pilot.press("up")
        await pilot.pause()
        assert widget.pane_lengths() == [chart + 3, table - 3]
        assert splitter.sizes == [
            round(100 * (chart + 3) / (chart + table)),
            round(100 * (table - 3) / (chart + table)),
        ]


@pytest.mark.asyncio
async def test_a_long_label_wraps_to_its_page_s_width_rather_than_widening_it() -> None:
    view = PagesMainView()
    view.router.results.total.text = " ".join(["A sentence longer than the screen is wide."] * 8)
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None

    async with app.run_test(size=(80, 30)) as pilot:
        view.router.navigate("results")
        await pilot.pause()
        assert isinstance(view.router.results.total.renderer, TextualWidgetRenderer)
        label = view.router.results.total.renderer.widget
        assert isinstance(view.router.results.renderer, TextualWidgetRenderer)
        page = view.router.results.renderer.widget
        assert label is not None
        assert page is not None

        # every word in view, on several lines: no sideways scroll to read the end of the text
        assert label.region.height > 1
        assert label.region.right <= page.region.right
        assert page.max_scroll_x == 0


@pytest.mark.asyncio
async def test_a_view_textual_doesn_t_render_is_left_out_of_its_container() -> None:
    view = PartialMainView()
    app = _app_of(view)

    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        item = LabelView()
        view.items.item_views = [UnregisteredView(), item]
        await pilot.pause()

        for container in (view.row, view.column, view.grid, view.splitter, view.page):
            assert container.skipped.renderer is None
            assert _widget(container) in _widget(container.shown).ancestors
        assert _widget(view.expander.shown).parent is not None
        assert _widget(view.shown).is_attached
        assert _widget(view.items) in _widget(item).ancestors
        assert view.form.skipped.renderer is None  # a row whose field Textual doesn't register
        assert _widget(view.form) in _field_widget(view.form.shown.renderer).ancestors
        assert len(_widget(view.toolbar).query(ComposeToolbarButton)) == 1


@pytest.mark.asyncio
async def test_a_list_s_records_set_before_the_app_runs_show_once_it_does() -> None:
    view = PipesMainView()
    _add_reference_to_signals(view, None)
    app = _app_of(view)
    view.pipes.items = PIPES[:1]  # rendered, the app not running yet
    column = _widget(view.pipes)

    def shown() -> list[str]:
        return [
            str(child.title) for child in column.children if isinstance(child, ComposeCollapsible)
        ]

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        first = shown()
        view.pipes.items = []
        await pilot.pause()
        view.pipes.items = PIPES[1:2]  # into an empty list
        await pilot.pause()

        assert first == ["Main line"]
        assert shown() == ["Return"]


@pytest.mark.asyncio
async def test_tabs_start_on_the_tab_their_view_says_unreported() -> None:
    view = TabsMainView()
    view.tabs.current_index = 1  # e.g. by the app's setup, before rendering
    picks: list[int] = []
    view.tabs.current_changed.connect(picks.append)
    app = _app_of(view)
    tabbed = _widget(view.tabs)
    assert isinstance(tabbed, ComposeTabbedContent)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert tabbed.active_pane is _widget(view.tabs.history)
        assert (view.tabs.current_index, picks) == (1, [])


@pytest.mark.asyncio
async def test_tabs_changed_before_the_app_runs_show_so_once_it_does() -> None:
    view = TabsMainView()
    app = _app_of(view)
    tabs = view.tabs
    tabbed = _widget(tabs)
    assert isinstance(tabbed, ComposeTabbedContent)
    history, notes = _widget(tabs.history), _widget(tabs.notes)
    assert isinstance(history, TabPane)
    assert isinstance(notes, TabPane)
    tabs.history.title = "Changes"
    tabs.notes.is_visible = False

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert str(tabbed.get_tab(history).label) == "Changes"
        assert not tabbed.get_tab(notes).display


@pytest.mark.asyncio
async def test_a_tab_picked_in_code_before_its_tabs_mount_shows_once_they_do() -> None:
    view = TabsMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.tabs.renderer, TextualWidgetRenderer)
    tabbed = view.tabs.renderer.widget
    assert isinstance(tabbed, ComposeTabbedContent)
    assert isinstance(view.tabs.history.renderer, TextualWidgetRenderer)
    history = view.tabs.history.renderer.widget
    picks: list[int] = []
    view.tabs.current_changed.connect(picks.append)
    view.tabs.current_index = 1  # e.g. tabs in a dialog's form, its screen not shown yet

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert tabbed.active_pane is history
        assert (view.tabs.current_index, picks) == (1, [])


@pytest.mark.asyncio
async def test_a_splitter_s_border_stays_on_a_hover_and_beside_a_hidden_pane() -> None:
    view = SplitterMainView()
    app = _app_of(view)
    resizes: list[list[int]] = []
    view.splitter.resized.connect(resizes.append)

    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        first, _second = app.query(SplitterHandle)
        await pilot.hover(first)  # no button held: no drag
        view.splitter.study.is_visible = False  # no pane left of the first border
        await pilot.pause()
        first.focus()
        await pilot.press("right")
        await pilot.pause()

        assert len(resizes) <= 1  # nothing moved: the sizes as they were, if reported
        assert all(sizes == view.splitter.sizes for sizes in resizes)


@pytest.mark.asyncio
async def test_a_splitter_s_border_released_undragged_reports_nothing() -> None:
    view = SplitterMainView()
    app = _app_of(view)
    resizes: list[list[int]] = []
    view.splitter.resized.connect(resizes.append)

    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        first, _second = app.query(SplitterHandle)
        await pilot.mouse_up(first)  # pressed elsewhere

        assert resizes == []


@define_view
class _InnerFirstTab(TabPage):
    text: LabelView = Factory(lambda: LabelView(text="One"))


@define_view
class _InnerSecondTab(TabPage):
    text: LabelView = Factory(lambda: LabelView(text="Two"))


@define_view
class _InnerTabs(TabView):
    first: _InnerFirstTab = Factory(lambda: _InnerFirstTab(title="First"))
    second: _InnerSecondTab = Factory(lambda: _InnerSecondTab(title="Second"))


@define_view
class _OuterTab(TabPage):
    inner: _InnerTabs = Factory(_InnerTabs)


@define_view
class _OtherTab(TabPage):
    text: LabelView = Factory(lambda: LabelView(text="Other"))


@define_view
class _OuterTabs(TabView):
    outer: _OuterTab = Factory(lambda: _OuterTab(title="Outer"))
    other: _OtherTab = Factory(lambda: _OtherTab(title="Other"))


@define_view
class _NestedTabsMainView(MainView):
    app_title = "Nested"
    extension = ".nested"

    tabs: _OuterTabs = Factory(_OuterTabs)


@pytest.mark.asyncio
async def test_a_tab_picked_in_tabs_within_tabs_is_theirs_only() -> None:
    view = _NestedTabsMainView()
    app = _app_of(view)
    outer_picks: list[int] = []
    view.tabs.current_changed.connect(outer_picks.append)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        inner = _widget(view.tabs.outer.inner)
        assert isinstance(inner, ComposeTabbedContent)
        second = _widget(view.tabs.outer.inner.second)
        assert isinstance(second, TabPane)
        await pilot.click(inner.get_tab(second))
        await pilot.pause()

        assert view.tabs.outer.inner.current_index == 1
        assert (view.tabs.current_index, outer_picks) == (0, [])
