"""Tests of the Qt containers: pages, rows, grids, splitters, expanders, tabs and lists."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from qtpy.QtCore import QPoint, Qt
from qtpy.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QMainWindow,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QWidget,
)

from composeui.core.application import _add_reference_to_signals
from composeui.core.registry import RendererType
from composeui.core.view import (
    Frame,
    LabelView,
    TabView,
)
from composeui.qtcore._renderers.actions import QtActionRenderer
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qexpander import QExpander
from examples.pipecatalogue import PipeCatalogueMainView
from examples.pipeform import PipeMainView
from tests.expander import RecordMainView
from tests.frames import FramedMainView
from tests.grid import GridMainView
from tests.horizontal import (
    ButtonsMainView,
    HorizontalMainView,
    ManyButtonsMainView,
    ManyStartButtons,
)
from tests.listview import PIPES, Pipe, PipeExpander, PipesMainView
from tests.markdown import HelpMainView
from tests.pages import (
    ColumnsMainView,
    DocumentSidebarMainView,
    DocumentTabMainView,
    NotesMainView,
    PagesMainView,
)
from tests.partial import PartialMainView, UnregisteredView
from tests.splitter import SplitterMainView, VerticalSplitterMainView
from tests.tabs import TabsMainView
from tests.vertical import VerticalMainView

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytestqt.qtbot import QtBot

    from composeui.core.view import MainView, View

from tests.qtcore.support import _field_widget, _move_pressed, _press, _release, _widget


def test_a_layout_frame_keeps_its_contents_when_its_title_is_translated(qtbot: QtBot) -> None:
    view = FramedMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()

    row, grid, column = (_widget(layout) for layout in (view.row, view.grid, view.column))
    assert isinstance(row, QGroupBox)
    assert isinstance(grid, QGroupBox)
    assert isinstance(column, QGroupBox)
    assert (row.title(), grid.title(), column.title()) == ("Shape", "", "<layout-title> & controls")

    table = _widget(view.row.narrow)
    assert row.isAncestorOf(table)
    assert table.isVisible()
    assert grid.isAncestorOf(_widget(view.grid.button))
    assert column.isAncestorOf(_widget(view.column.button))
    first_children = (table, _widget(view.grid.first), _widget(view.column.table))
    for box, first in zip((row, grid, column), first_children):
        assert first.geometry().left() > box.contentsRect().left()
        assert first.geometry().top() > box.contentsRect().top()
    view.set_language("fr")
    assert _widget(view.row) is row
    assert row.title() == "Forme"
    assert row.isAncestorOf(table)
    assert table.isVisible()


def test_markdown_takes_the_spare_height_of_the_window(qtbot: QtBot) -> None:
    view = HelpMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)
    renderer = view.help.renderer
    assert isinstance(renderer, QtWidgetRenderer)
    browser = renderer.qt_object
    assert isinstance(browser, QTextBrowser)
    # it scrolls within itself: down to the status bar, no empty space under it
    browser_bottom = browser.mapTo(window, browser.rect().bottomLeft()).y()
    assert window.statusBar().geometry().top() - browser_bottom < 30


def test_a_page_s_markdown_takes_the_spare_height_of_the_window(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)
    view.pages.navigate("help")
    browser = _widget(view.pages.help.help)
    # its page, under the pages' toolbar, down to the status bar: no empty space under it
    qtbot.waitUntil(
        lambda: (
            window.statusBar().geometry().top()
            - browser.mapTo(window, browser.rect().bottomLeft()).y()
            < 30
        )
    )


def test_a_window_asks_for_its_page_s_size_and_scrolls_a_wider_page(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    page = _widget(view.pages.inputs)
    assert isinstance(page, QScrollArea)
    column = page.widget()
    assert column is not None

    # room for the whole page, as without scrolling: Qt opens a window at its size hint, up
    # to a share of the screen
    assert window.sizeHint().height() > column.sizeHint().height()
    # narrower than its fields: they scroll sideways, rather than being cut on the right
    view.minimum_width = 100
    window.resize(100, window.height())
    qtbot.waitUntil(page.horizontalScrollBar().isVisible)


def test_a_page_taller_than_the_window_scrolls_rather_than_squeezing_its_views(
    qtbot: QtBot,
) -> None:
    view = NotesMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 480)
    window.show()
    qtbot.waitExposed(window)
    expander = _widget(view.router.notes.notes)
    assert isinstance(expander, QExpander)
    notes = _widget(view.router.notes.notes.notes)

    expander.header.click()

    # every line shown, as on the web: the page grows past the window, and scrolls
    qtbot.waitUntil(lambda: notes.height() == notes.sizeHint().height())
    page = _widget(view.router.notes)
    assert isinstance(page, QScrollArea)
    assert page.verticalScrollBar().isVisible()


def test_a_long_label_wraps_to_its_page_s_width_rather_than_widening_it(qtbot: QtBot) -> None:
    view = PagesMainView()
    view.router.results.total.text = " ".join(["A sentence longer than the window is wide."] * 8)
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 480)
    window.show()
    qtbot.waitExposed(window)
    view.router.navigate("results")
    page = _widget(view.router.results)
    assert isinstance(page, QScrollArea)
    label = _widget(view.router.results.total)
    assert isinstance(label, QLabel)

    # every word in view, on several lines: no sideways scroll to read the end of the text
    qtbot.waitUntil(lambda: label.height() >= 2 * label.fontMetrics().height())
    assert page.horizontalScrollBar().maximum() == 0
    assert label.mapTo(page, label.rect().topRight()).x() <= page.viewport().width()


def test_a_column_on_a_short_page_is_as_tall_as_its_views(qtbot: QtBot) -> None:
    view = ColumnsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(1100, 800)
    window.show()
    qtbot.waitExposed(window)
    page = view.router.header
    header, name = _widget(page.header), _widget(page.name)
    # the page's spare height goes under its views, not between its header and the field
    assert header.height() == header.sizeHint().height()
    header_bottom = header.mapTo(window, header.rect().bottomLeft()).y()
    assert name.mapTo(window, name.rect().topLeft()).y() - header_bottom < 20


@pytest.mark.parametrize(
    ("main_view_type", "document_of"),
    [
        (DocumentTabMainView, lambda view: view.tabs.document.help),
        (DocumentSidebarMainView, lambda view: view.side.help),
    ],
    ids=["tab", "sidebar"],
)
def test_a_document_takes_the_spare_height_of_its_tab_or_sidebar(
    qtbot: QtBot, main_view_type: type[MainView], document_of: Callable[[Any], View]
) -> None:
    view = main_view_type()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(1100, 800)
    window.show()
    qtbot.waitExposed(window)
    browser = _widget(document_of(view))
    # it scrolls within itself: down to the bottom of the column holding it
    column = browser.parentWidget()
    assert column is not None
    qtbot.waitUntil(lambda: column.height() - browser.geometry().bottom() < 15)


def test_a_column_s_document_takes_the_spare_height_while_shown(qtbot: QtBot) -> None:
    view = ColumnsMainView()
    document = view.router.help.help.help
    document.is_visible = False
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(1100, 800)
    window.show()
    qtbot.waitExposed(window)
    view.router.navigate("help")
    column, browser = _widget(view.router.help.help), _widget(document)

    # hidden when the page was built: the column is as tall as its title
    qtbot.waitUntil(lambda: column.height() == column.sizeHint().height())
    # shown: it scrolls within itself, down to the window's bottom
    document.is_visible = True
    qtbot.waitUntil(
        lambda: window.height() - browser.mapTo(window, browser.rect().bottomLeft()).y() < 40
    )
    # hidden again: the column gives the height back
    document.is_visible = False
    qtbot.waitUntil(lambda: column.height() == column.sizeHint().height())


def test_a_row_holding_a_list_and_a_tree_takes_the_spare_height_of_the_window(
    qtbot: QtBot,
) -> None:
    view = PipeCatalogueMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.resize(1100, 700)
    window.show()
    qtbot.waitExposed(window)
    browser = view.catalogue.browser
    tree, pipes = _widget(browser.tree), _widget(browser.pipes)
    # both scroll within themselves: as tall as the row, down to the window's bottom
    assert tree.height() == pipes.height()
    assert window.height() - pipes.mapTo(window, pipes.rect().bottomLeft()).y() < 40


def test_a_horizontal_view_shares_the_row_by_stretch(qtbot: QtBot) -> None:
    view = HorizontalMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)
    narrow, wide, row = (
        _widget(table).geometry() for table in (view.tables.narrow, view.tables.wide, view.tables)
    )

    assert narrow.top() == wide.top()
    assert narrow.right() < wide.left()
    assert wide.width() == pytest.approx(3 * narrow.width(), rel=0.02)
    # the hidden table takes no share: the two shown span the row
    assert narrow.left() == 0
    assert wide.right() == row.width() - 1


def test_a_vertical_view_stacks_its_views_at_its_top(qtbot: QtBot) -> None:
    view = VerticalMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)
    column = view.tables.column
    table, button = (_widget(child).geometry() for child in (column.table, column.button))
    layout = _widget(column).layout()
    assert layout is not None

    assert table.top() == 0
    assert button.top() == table.bottom() + 1 + layout.spacing()
    # next to a taller table, the row's spare height is left below the column's views
    assert _widget(column).geometry().top() == _widget(view.tables.tall).geometry().top()
    assert button.bottom() < _widget(view.tables.tall).geometry().bottom()


def test_a_view_shorter_than_its_row_stays_at_the_row_s_top(qtbot: QtBot) -> None:
    view = VerticalMainView()
    # the table beside the column now the shorter of the two
    view.tables.tall.rows = [["Short"]]
    view.tables.column.table.rows = [[str(i)] for i in range(10)]
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)

    for height in (600, 900):
        window.resize(800, height)

        def resized(height: int = height) -> bool:
            return window.height() == height

        qtbot.waitUntil(resized)
        assert _widget(view.tables.tall).geometry().top() == 0


def test_a_grid_view_places_its_views_in_equally_wide_columns(qtbot: QtBot) -> None:
    view = GridMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(900, 600)
    window.show()
    qtbot.waitExposed(window)
    grid = view.tables
    first, button, spanning = (
        _widget(child).geometry() for child in (grid.first, grid.button, grid.spanning)
    )
    layout = _widget(grid).layout()
    assert isinstance(layout, QGridLayout)
    gap = layout.horizontalSpacing()

    assert (first.left(), first.top(), button.top()) == (0, 0, 0)
    # the hidden table's column is kept: the button is in the third one
    assert button.left() == pytest.approx(2 * (first.width() + gap), abs=2)
    # as wide as its text, unlike the table filling its column
    assert button.width() < first.width() // 2
    # the next row starts below the taller of the views above it, spanning the columns
    assert spanning.top() == first.bottom() + 1 + layout.verticalSpacing()
    assert spanning.width() == pytest.approx(3 * first.width() + 2 * gap, abs=2)
    assert spanning.right() == _widget(grid).width() - 1


def test_buttons_with_no_share_pack_at_their_row_s_start_or_end(qtbot: QtBot) -> None:
    view = ButtonsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)

    for row, packed_at_end in (
        (view.start, False),
        (view.end, True),
        # the table with a share hidden: the free width still goes before the buttons
        (view.beside_hidden, True),
    ):
        first, second = (_widget(button).geometry() for button in (row.first, row.second))
        width = _widget(row).width()
        # as wide as their text, side by side
        assert first.width() == _widget(row.first).sizeHint().width()
        assert 0 < second.left() - first.right() < 20
        if packed_at_end:
            assert second.right() == width - 1
        else:
            assert first.left() == 0


def test_buttons_with_no_share_wrap_onto_lines_as_wide_as_their_row(qtbot: QtBot) -> None:
    view = ManyButtonsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(400, 600)
    window.show()
    qtbot.waitExposed(window)
    # the rows don't widen the window
    assert window.width() == 400

    top = 0
    for row, packed_at_end in (
        (view.start, False),
        (view.end, True),
        (view.beside.buttons, False),
    ):
        first, last = (_widget(button) for button in (row.buttons[0], row.buttons[-1]))
        width = _widget(row).width()
        assert width < window.width()
        boxes = [_widget(button).geometry() for button in row.buttons]
        # each as wide as its text, within the row: none cut off or squeezed
        assert all(
            box.width() == _widget(button).sizeHint().width()
            for box, button in zip(boxes, row.buttons)
        )
        assert all(box.left() >= 0 and box.right() <= width - 1 for box in boxes)
        # side by side, the last ones on another line, and the row as tall as its lines
        assert boxes[1].top() == boxes[0].top()
        assert last.geometry().top() > first.geometry().bottom()
        assert _widget(row).mapTo(window, QPoint(0, 0)).y() >= top
        top = last.mapTo(window, last.rect().bottomLeft()).y()
        if packed_at_end:
            assert last.geometry().right() == width - 1
        else:
            assert first.geometry().left() == 0
    # a note longer than the row wraps within it, its button beside or below it
    note, retry = _widget(view.noted.note), _widget(view.noted.retry)
    width = _widget(view.noted).width()
    assert note.geometry().right() <= width - 1
    assert note.height() >= 2 * note.fontMetrics().height()
    assert retry.geometry().right() <= width - 1
    top = max(widget.mapTo(window, widget.rect().bottomLeft()).y() for widget in (note, retry))
    assert _widget(view.below).mapTo(window, QPoint(0, 0)).y() > top


def test_a_framed_button_row_wraps_inside_its_padding(qtbot: QtBot) -> None:
    view = ManyButtonsMainView(start=ManyStartButtons(frame=Frame(title="Actions")))
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(400, 600)
    window.show()
    qtbot.waitExposed(window)

    area = _widget(view.start).contentsRect()
    buttons = [_widget(button).geometry() for button in view.start.buttons]
    assert buttons[-1].top() > buttons[0].bottom()
    assert all(area.adjusted(1, 1, -1, -1).contains(button) for button in buttons)


def test_a_list_view_shows_a_view_per_record_as_the_records_change(qtbot: QtBot) -> None:
    view = PipesMainView()
    view.status_bar.timeout = 0
    _add_reference_to_signals(view, None)
    view.pipes.items = PIPES[:1]  # before rendering, as at startup
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    scroll = _widget(view.pipes)
    assert isinstance(scroll, QScrollArea)
    column = scroll.widget()
    layout = None if column is None else column.layout()
    assert layout is not None

    def shown() -> list[str]:
        titles = []
        for index in range(layout.count()):
            item = layout.itemAt(index)
            expander = None if item is None else item.widget()
            if isinstance(expander, QExpander):  # not the stretch under them
                titles.append(expander.header.text())
        return titles

    assert shown() == ["Main line"]
    main_line = _widget(view.pipes.item_views[0])
    view.pipes.items = [Pipe("Feed", 1), *PIPES]  # built since: rendered as they come
    assert shown() == ["Feed", "Main line", "Return"]
    assert _widget(view.pipes.item_views[1]) is main_line  # the record's own widget

    feed = view.pipes.item_views[0]
    assert isinstance(feed, PipeExpander)
    qtbot.mouseClick(_widget(feed.delete), Qt.MouseButton.LeftButton)
    assert shown() == ["Main line", "Return"]
    assert view.status_bar.message == "Deleted Feed"

    # the list scrolls within itself: many records leave the window's height alone
    height = window.minimumSizeHint().height()
    view.pipes.items = [Pipe(f"Pipe {number}", 1) for number in range(40)]
    assert window.minimumSizeHint().height() == height


def test_a_tab_view_shows_the_tab_the_user_picks(qtbot: QtBot) -> None:
    view = TabsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    tabs = view.tabs
    tab_widget = _widget(tabs)
    assert isinstance(tab_widget, QTabWidget)
    bar = tab_widget.tabBar()
    assert [tab_widget.tabText(index) for index in range(tab_widget.count())] == [
        "Details",
        "History",
        "Notes",
    ]
    picks: list[int] = []
    tabs.current_changed.connect(picks.append)
    assert _widget(tabs.details.length).isVisible()
    # a tab's views are built the first time it's shown, as they are then
    assert tabs.history.created.renderer is None
    tabs.history.created.text = "Created on Tuesday"

    qtbot.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(1).center())
    assert (tabs.current_index, picks) == (1, [1])
    created = _widget(tabs.history.created)
    assert isinstance(created, QLabel)
    assert created.text() == "Created on Tuesday"
    assert created.isVisible()  # at once, not at the event loop's next turn
    assert tabs.current_tab is tabs.history

    tabs.current_index = 0  # set in code: shown, and not reported
    assert (tab_widget.currentIndex(), picks) == (0, [1])
    assert not created.isVisible()
    tabs.current_index = 1
    assert _widget(tabs.history.created) is created  # built once
    tabs.history.title = "Changes"
    assert tab_widget.tabText(1) == "Changes"
    # a tab not built yet shows its title and state on its tab all the same
    assert tabs.notes.note.renderer is None
    tabs.notes.title = "Remarks"
    assert tab_widget.tabText(2) == "Remarks"
    tabs.notes.is_enabled = False
    assert not tab_widget.isTabEnabled(2)
    tabs.notes.is_visible = False
    assert not tab_widget.isTabVisible(2)


def test_a_tab_view_without_tabs_shows_an_empty_tab_widget(qtbot: QtBot) -> None:
    view = TabView()
    view.render(RendererType.QT)
    tab_widget = _widget(view)
    assert isinstance(tab_widget, QTabWidget)
    qtbot.addWidget(tab_widget)
    assert tab_widget.count() == 0


def test_an_expander_shows_its_views_while_expanded_by_a_click_on_its_header(
    qtbot: QtBot,
) -> None:
    view = RecordMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    record = view.record
    expander = _widget(record)
    assert isinstance(expander, QExpander)
    edit = _widget(record.buttons.edit)
    toggles: list[bool] = []
    record.toggled.connect(toggles.append)
    window.show()
    assert expander.header.text() == "Pipe A"
    assert not edit.isVisible()  # collapsed

    qtbot.mouseClick(expander.header, Qt.MouseButton.LeftButton)
    assert (record.is_expanded, toggles) == (True, [True])
    assert edit.isVisible()
    assert expander.header.arrowType() == Qt.ArrowType.DownArrow

    record.is_expanded = False  # set in code: collapsed, and not reported
    assert not edit.isVisible()
    assert (expander.header.isChecked(), toggles) == (False, [True])
    record.title = "Pipe B"
    assert expander.header.text() == "Pipe B"


def _drag(widget: QWidget, start: QPoint, end: QPoint) -> None:
    """Drag the mouse from `start` to `end` in `widget`, its left button held throughout."""
    _press(widget, start)
    _move_pressed(widget, end)
    _release(widget, end)


def test_a_splitter_shares_its_width_as_its_sizes_and_takes_the_users_drags(
    qtbot: QtBot,
) -> None:
    view = SplitterMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(830, 400)
    window.show()
    qtbot.waitExposed(window)
    splitter = view.splitter
    widget = _widget(splitter)
    assert isinstance(widget, QSplitter)
    assert splitter.sizes == [1, 1, 2]  # the panes' STRETCH, at least 1
    resizes: list[list[int]] = []
    splitter.resized.connect(resizes.append)
    study, settings, result = widget.sizes()
    assert study == pytest.approx(settings, abs=2)
    assert result == pytest.approx(2 * study, abs=4)

    handle = widget.handle(1)  # between the study and the settings
    middle = handle.rect().center()
    _drag(handle, middle, middle + QPoint(study // 2, 0))
    widths = widget.sizes()
    assert widths[0] > study
    assert splitter.sizes == [round(100 * width / sum(widths)) for width in widths]
    assert resizes == [splitter.sizes]  # once dropped
    _drag(handle, middle, middle)  # a click: nothing moves, nothing reported
    assert len(resizes) == 1

    handle.setFocus()  # the arrow keys move a focused handle
    qtbot.keyClick(handle, Qt.Key.Key_Left)
    assert widget.sizes()[0] == widths[0] - 16
    assert resizes[1:] == [splitter.sizes]

    splitter.sizes = [1, 1, 1]  # set in code: shared alike, and not reported
    study, settings, result = widget.sizes()
    assert study == pytest.approx(result, abs=2)
    assert len(resizes) == 2
    splitter.settings.is_visible = False  # its width to the others, its share kept
    qtbot.waitUntil(lambda: widget.sizes()[1] == 0)
    assert widget.handle(1).isHidden()
    splitter.sizes = [1, 2, 1]  # set while hidden: it stays so, its share for later
    settings_widget = widget.widget(1)
    assert settings_widget is not None
    assert (widget.sizes()[1], settings_widget.isHidden()) == (0, True)
    assert widget.sizes()[0] == pytest.approx(widget.sizes()[2], abs=2)
    handle = widget.handle(2)
    middle = handle.rect().center()
    _drag(handle, middle, middle - QPoint(50, 0))
    assert splitter.sizes[1] == 2
    assert splitter.sizes[0] + splitter.sizes[2] == 100
    assert splitter.sizes[0] < splitter.sizes[2]  # dragged left
    splitter.settings.is_visible = True
    qtbot.waitUntil(lambda: widget.sizes()[1] > 0)


def test_a_splitter_keeps_its_panes_through_a_language_switch(qtbot: QtBot) -> None:
    view = SplitterMainView()
    view.render(RendererType.QT)
    widget = _widget(view.splitter)
    assert isinstance(widget, QSplitter)
    qtbot.addWidget(widget)

    view.set_language("fr")  # its borders' name is the web's only

    assert view.splitter.border_text == "Redimensionner les volets"
    assert widget.count() == 3


def test_a_vertical_splitter_shares_the_windows_spare_height_as_its_sizes(
    qtbot: QtBot,
) -> None:
    view = VerticalSplitterMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(600, 700)
    window.show()
    qtbot.waitExposed(window)
    splitter = view.splitter
    widget = _widget(splitter)
    assert isinstance(widget, QSplitter)
    assert widget.orientation() == Qt.Orientation.Vertical
    chart, table = widget.sizes()
    assert chart == pytest.approx(2 * table, abs=4)
    assert chart + table > 500  # the window's spare height, not its labels'

    handle = widget.handle(1)
    middle = handle.rect().center()
    _drag(handle, middle, middle + QPoint(0, 60))
    heights = widget.sizes()
    assert heights[0] == pytest.approx(chart + 60, abs=2)
    assert splitter.sizes == [round(100 * height / sum(heights)) for height in heights]

    handle.setFocus()  # its keys are the up and down arrows
    qtbot.keyClick(handle, Qt.Key.Key_Down)
    assert widget.sizes()[0] == heights[0] + 16


def test_a_view_qt_doesn_t_render_is_left_out_of_its_container(qtbot: QtBot) -> None:
    view = PartialMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    item = LabelView()
    view.items.item_views = [UnregisteredView(), item]

    for container in (view.row, view.column, view.grid, view.splitter, view.expander, view.page):
        assert container.skipped.renderer is None
        assert _widget(container).isAncestorOf(_widget(container.shown))
    assert window.isAncestorOf(_widget(view.shown))
    assert _widget(view.items).isAncestorOf(_widget(item))
    assert isinstance(view.action.renderer, QtActionRenderer)
    assert view.action.renderer.qt_object is None
    assert view.form.skipped.renderer is None  # a row whose field Qt doesn't register
    assert _widget(view.form).isAncestorOf(_field_widget(view.form.shown))
    for bar in (view.menu, view.toolbar):
        assert isinstance(bar.renderer, QtWidgetRenderer)
        assert isinstance(bar.renderer.qt_object, QWidget)
        assert len(bar.renderer.qt_object.actions()) == 1  # its action only


def test_a_splitter_s_handle_moves_by_its_own_arrows_and_the_left_button_only(
    qtbot: QtBot,
) -> None:
    view = SplitterMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    widget = _widget(view.splitter)
    assert isinstance(widget, QSplitter)
    sizes = widget.sizes()
    resizes: list[list[int]] = []
    view.splitter.resized.connect(resizes.append)
    handle = widget.handle(1)

    handle.setFocus()
    qtbot.keyClick(handle, Qt.Key.Key_Up)  # across a row of panes
    qtbot.mouseClick(handle, Qt.MouseButton.RightButton)

    assert (widget.sizes(), resizes) == (sizes, [])
