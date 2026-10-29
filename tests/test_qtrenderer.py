"""End-to-end coverage for the Qt backend (roadmap item 3).

Unlike `tests/test_pipeview.py`, which drives view/model logic by calling methods
and manually emitting signals, these tests actually render a widget tree with Qt,
assert on the real widget's state, and drive interactions through the widget layer
(typed keystrokes, a real radio-button click, a triggered `QAction`) to prove the
round trip back into the view - the same style `tests/test_textual_renderer.py`
already uses for the Textual backend.
"""

from __future__ import annotations

import datetime
import gc
import json
import math
import sys
import threading
from typing import TYPE_CHECKING, Any

import numpy as np
import pyqtgraph as pg
import pytest
from qtpy.QtCore import QDate, QEvent, QModelIndex, QPoint, QPointF, QSize, Qt, QUrl
from qtpy.QtGui import (
    QAction,
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPalette,
    QPixmap,
    QTextDocument,
)
from qtpy.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from composeui.core import chartimage
from composeui.core.application import _add_reference_to_signals
from composeui.core.chartcolors import SERIES_COLORS
from composeui.core.registry import create_renderer
from composeui.core.renderer import MainRenderer, NoRenderedObjectError, RendererContainer
from composeui.core.view import (
    SEARCH_DELAY_MS,
    SOURCE_TABLE_JOB_ROWS,
    SOURCE_TABLE_WINDOW,
    ActionView,
    ButtonVariant,
    CellStyle,
    CellWidget,
    ChartKind,
    ChartView,
    DialogKind,
    EditRefusedError,
    FloatInputView,
    HeaderGroup,
    InputView,
    IntInputView,
    LabelView,
    LineStyle,
    ListSource,
    LogType,
    MapPoint,
    MapView,
    ReferenceLine,
    RendererType,
    Router,
    SelectionMode,
    Series,
    SourceTableView,
    T,
    TableView,
    TreeNode,
    replace_cell,
)
from composeui.qtcore.qtrenderer import RENDERERS as QT_RENDERERS
from composeui.qtcore.qtrenderer import QtActionRenderer, QtMainRenderer, QtWidgetRenderer
from composeui.qtcore.widgets.qchart import QChart
from composeui.qtcore.widgets.qdatefield import QDateField
from composeui.qtcore.widgets.qexpander import QExpander
from composeui.qtcore.widgets.qfilepathfield import QFilePathField
from composeui.qtcore.widgets.qfiltertable import QFilterTable
from composeui.qtcore.widgets.qformdialog import QFormDialog
from composeui.qtcore.widgets.qformlabel import QFormLabel
from composeui.qtcore.widgets.qmap import QMap
from composeui.qtcore.widgets.qmetric import QMetric
from composeui.qtcore.widgets.qsidebar import QSidebar
from composeui.qtcore.widgets.qsourcetable import QDataFilterTable
from composeui.qtcore.widgets.qtexttable import QCheckHeader, QTextTableView
from composeui.qtcore.widgets.qvalueslider import QValueSlider
from composeui.qtcore.widgets.qwindowrelease import release_when_hidden
from examples.pipecatalogue import PipeCatalogueMainView
from examples.pipechart import PipeChartMainView
from examples.pipeform import EdgeType, PipeMainView
from tests.bookings import BookingMainView
from tests.buildings import SiteMainView, styled_site
from tests.charts import ChartPagesMainView
from tests.datafiles import DataFileMainView
from tests.dialogs import DialogsMainView
from tests.expander import RecordMainView
from tests.filters import FiltersMainView
from tests.formdialog import PipeMainView as EditedPipeMainView
from tests.grid import GridMainView
from tests.horizontal import ButtonsMainView, HorizontalMainView
from tests.hours import HoursMainView
from tests.listview import PIPES, Pipe, PipeExpander, PipesMainView
from tests.lonerows import LoneRowsMainView
from tests.maps import MapMainView
from tests.markdown import HelpMainView, HelpViewerMainView
from tests.markup import MARKUP, MarkupMainView
from tests.metrics import JobsMainView
from tests.pages import InputsPage, PagesMainView
from tests.partial import PartialMainView, UnregisteredView
from tests.sidebar import SidebarMainView
from tests.splitter import SplitterMainView, VerticalSplitterMainView
from tests.tables import (
    CellWidgetsMainView,
    EditableTableMainView,
    GatedMainView,
    GatedSource,
    MillionRowsMainView,
    MillionSource,
    Room,
    RoomsDataMainView,
    SortedRoomsMainView,
    StyledTablesMainView,
)
from tests.tabs import TabsMainView
from tests.toolbar import ToolBarMainView
from tests.translated import Size, TranslatedMainView
from tests.unlabelled import NoteMainView
from tests.vertical import VerticalMainView
from tests.workers import WorkersMainView

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.core.chartimage import ImageOptions
    from composeui.core.view import Filter, MainView, Sort, View


@pytest.fixture(autouse=True)
def _collect_between_tests() -> Iterator[None]:
    """Destroy the windows tests leave to the garbage collector only between tests.

    Collected while pyqtgraph paints (its items paint in Python, where a collection can
    run), a window's widgets die under a painter, which crashes.
    """
    gc.collect()
    gc.disable()
    yield
    gc.enable()
    gc.collect()


def _field_widget(view: View) -> QWidget:
    renderer = view.renderer
    assert isinstance(renderer, RendererContainer)
    field_renderer = renderer.get_renderer("field")
    assert isinstance(field_renderer, QtWidgetRenderer)
    widget = field_renderer.qt_object
    assert widget is not None
    return widget


def test_map_renders_points_and_syncs_the_viewport_and_clicks(qtbot: QtBot) -> None:
    view = MapMainView()
    view.map.render(RendererType.QT)
    assert isinstance(view.map.renderer, QtWidgetRenderer)
    widget = view.map.renderer.qt_object
    assert isinstance(widget, QMap)
    qtbot.addWidget(widget)
    widget.resize(640, 440)
    widget.show()
    assert not widget.map.errors()
    assert widget.title.text() == "Pickup locations"
    assert widget.root.property("latitude") == 40.73
    assert widget.root.property("longitude") == -73.98
    assert widget.root.property("zoom") == 11
    assert widget.map.height() == 400

    widget.map.setFocus()
    widget.activateWindow()
    qtbot.waitUntil(widget.map.hasFocus)
    qtbot.keyClick(widget.map, Qt.Key.Key_Plus)
    assert view.map.zoom == 12
    assert view.result.text.startswith("Zoom 12;")
    view.map.renderer.render()
    assert widget.root.property("zoom") == 12

    qtbot.mouseClick(widget.map, Qt.MouseButton.LeftButton, pos=widget.map.rect().center())
    qtbot.waitUntil(lambda: view.result.text.startswith("Clicked"))
    assert view.result.text == "Clicked 40.73, -73.98"
    image = widget.map.grabFramebuffer()
    assert not image.isNull()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    assert color.blue() > color.green() > color.red()
    qtbot.keyClick(widget.map, Qt.Key.Key_Right)
    center = view.map.center
    assert center is not None
    assert center.longitude > -73.98
    assert center.latitude == pytest.approx(40.73)
    view.map.center = MapPoint(latitude=48.86, longitude=2.35)
    view.map.zoom = 12
    view.map.points = [MapPoint(latitude=48.86, longitude=2.35)]
    assert widget.root.property("latitude") == 48.86
    assert widget.root.property("longitude") == 2.35
    assert widget.root.property("zoom") == 12
    assert widget.root.property("points") == [[48.86, 2.35]]
    view.map.title = "Paris"
    view.map.height = 250
    view.map.user_agent = "ComposeUI test"
    assert widget.title.text() == "Paris"
    assert widget.map.height() == 250
    assert widget.root.property("latitude") == 48.86
    assert widget.root.property("zoom") == 12


def test_map_fits_late_points_and_resizes_until_the_user_chooses_a_viewport(qtbot: QtBot) -> None:
    view = MapView(tiles=False)
    events: list[tuple[MapPoint | None, float | None]] = []
    view.viewport_changed.connect(lambda: events.append((view.center, view.zoom)))
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QMap)
    qtbot.addWidget(widget)
    widget.resize(640, 440)
    widget.show()
    assert widget.root.property("latitude") == 0
    assert widget.root.property("longitude") == 0

    view.points = [MapPoint(latitude=0, longitude=-10), MapPoint(latitude=0, longitude=10)]
    qtbot.waitUntil(lambda: widget.map.width() == widget.width())
    assert widget.root.property("longitude") == pytest.approx(0)
    zoom = widget.root.property("zoom")
    widget.resize(2 * widget.width() - 64, widget.height())
    qtbot.waitUntil(lambda: widget.root.property("zoom") > zoom)
    fitted_zoom = widget.root.property("zoom")
    assert fitted_zoom == pytest.approx(zoom + 1)

    view.center = MapPoint(latitude=0, longitude=10)
    assert widget.root.property("longitude") == 10
    assert widget.root.property("zoom") == pytest.approx(fitted_zoom - 1)
    view.zoom = 8
    assert widget.root.property("zoom") == 8
    view.center = None
    assert widget.root.property("longitude") == pytest.approx(0)
    assert widget.root.property("zoom") == 8
    view.zoom = None
    assert widget.root.property("zoom") == pytest.approx(fitted_zoom)
    assert events == []

    widget.activateWindow()
    widget.map.setFocus()
    qtbot.waitUntil(widget.map.hasFocus)
    qtbot.keyClick(widget.map, Qt.Key.Key_Plus)
    assert len(events) == 1
    center, chosen_zoom = events[0]
    assert center is not None
    assert chosen_zoom == pytest.approx(fitted_zoom + 1)
    view.points = [MapPoint(latitude=48.86, longitude=2.35)]
    widget.resize(640, 440)
    assert widget.root.property("latitude") == center.latitude
    assert widget.root.property("longitude") == center.longitude
    assert widget.root.property("zoom") == chosen_zoom

    view.center = None
    view.zoom = None
    assert widget.root.property("latitude") == 48.86
    assert widget.root.property("longitude") == 2.35
    assert widget.root.property("zoom") == 12
    assert len(events) == 1


def test_an_unloaded_qml_map_reports_a_deployment_error(qtbot: QtBot) -> None:
    widget = QMap("ComposeUI test", tiles=False)
    qtbot.addWidget(widget)
    widget.map.setSource(QUrl())
    with pytest.raises(RuntimeError, match="Cannot load the Qt Location map"):
        _ = widget.root


def test_label_renderer_pushes_view_state_to_the_widget(qtbot: QtBot) -> None:
    view = LabelView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QLabel)

    view.text = "hello"
    assert widget.text() == "hello"


def _blocks(browser: QTextBrowser) -> list[tuple[str, int, bool]]:
    """Each paragraph of `browser`: its text, its heading level and whether it's listed."""
    blocks = []
    block = browser.document().firstBlock()
    while block.isValid():
        blocks.append(
            (block.text(), block.blockFormat().headingLevel(), block.textList() is not None)
        )
        block = block.next()
    return blocks


def test_markdown_renderer_shows_the_text_formatted(qtbot: QtBot) -> None:
    view = HelpMainView()
    view.render(RendererType.QT)
    renderer = view.help.renderer
    assert isinstance(renderer, QtWidgetRenderer)
    browser = renderer.qt_object
    assert isinstance(browser, QTextBrowser)
    assert browser.isReadOnly()
    assert browser.openExternalLinks()
    assert _blocks(browser) == [
        ("Help", 1, False),
        ("Open a study", 0, True),
        ("Run it", 0, True),
    ]

    view.help.text = "## Results\n\nAll [done](https://example.com)."
    assert _blocks(browser) == [("Results", 2, False), ("All done.", 0, False)]


def test_the_window_shows_the_app_s_icon_composeui_s_by_default(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = HelpMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    assert not window.windowIcon().isNull()

    monkeypatch.setattr(HelpMainView, "app_icon", None)
    iconless = HelpMainView()
    iconless.render(RendererType.QT)
    assert isinstance(iconless.renderer, QtWidgetRenderer)
    assert isinstance(iconless.renderer.qt_object, QMainWindow)
    assert iconless.renderer.qt_object.windowIcon().isNull()


def test_a_main_view_shown_in_another_s_window_replaces_its_parts(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = HelpMainView()
    previous.render(RendererType.QT)
    window = _widget(previous)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    menus = [action.text() for action in window.menuBar().actions()]
    content = window.centralWidget()
    # e.g. the changed code on a reload, which drops the icon
    monkeypatch.setattr(HelpMainView, "app_icon", None)
    view = HelpMainView()
    view.renderer = QtMainRenderer(view, window)

    view.render(RendererType.QT)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert [action.text() for action in window.menuBar().actions()] == menus  # not twice
    assert window.statusBar() is _widget(view.status_bar)
    assert window.centralWidget() is not content  # deleted
    assert window.isAncestorOf(_widget(view.help))
    assert window.windowIcon().isNull()


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


def test_pick_file_action_hands_the_picked_file_over(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = HelpMainView()
    _add_reference_to_signals(view, None)  # `main_view` for the action, as an app does
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    path = tmp_path / "notes.md"
    path.write_text("# Notes", encoding="utf-8")
    offered: list[str] = []

    def pick(*args: object) -> tuple[str, str]:
        offered.append(str(args[3]))
        return answer

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(pick))
    renderer = view.help_menu.open_help.renderer
    assert isinstance(renderer, QtActionRenderer)
    action = renderer.qt_object
    assert isinstance(action, QAction)

    answer = ("", "")  # cancelled: nothing picked
    action.trigger()
    assert view.help.text.startswith("# Help")
    answer = (str(path), "Markdown (*.md *.markdown)")
    action.trigger()
    assert view.help.text == "# Notes"
    assert offered == ["Markdown (*.md *.markdown)"] * 2


def test_an_app_without_studies_has_no_file_menu(qtbot: QtBot) -> None:
    view = HelpViewerMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    menus = [action.text() for action in window.menuBar().actions()]
    assert menus == ["Help"]
    # nor Ctrl+O, Ctrl+S... anywhere in the window
    shortcuts = [
        action.shortcut().toString()
        for action in window.findChildren(QAction)
        if not action.shortcut().isEmpty()
    ]
    assert shortcuts == ["Ctrl+H"]


def test_input_renderer_round_trips_typed_text(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    name_widget = _field_widget(view.pages.inputs.pipe_form.name)
    assert isinstance(name_widget, QLineEdit)
    assert name_widget.text() == ""

    name_widget.show()
    name_widget.setFocus()
    qtbot.keyClicks(name_widget, "PipeTShape")
    assert view.pages.inputs.pipe_form.name.text == "PipeTShape"
    assert view.pages.inputs.pipe_form.name.log_message == ""  # _check_name ran via text_edited

    # a change the user didn't type, e.g. a paste or a completer's, reaches the view too
    name_widget.setText("direct")
    assert view.pages.inputs.pipe_form.name.text == "direct"


def test_a_failing_pipe_check_outlines_the_fields_it_names(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    form = view.pages.inputs.pipe_form
    radius_widget = _field_widget(form.main_pipe.radius)
    assert isinstance(radius_widget, QLineEdit)
    named = [form.main_pipe.radius, form.main_pipe.width, form.incident_pipe.half_length]

    def outlined() -> list[bool]:
        return [
            _field_widget(row).styleSheet() != "" for row in (*named, form.incident_pipe.radius)
        ]

    radius_widget.show()
    radius_widget.setFocus()
    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "300")
    qtbot.keyClick(radius_widget, Qt.Key.Key_Return)
    # radius + width > the incident half length: the incident radius isn't involved
    assert outlined() == [True, True, True, False]

    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "50")
    qtbot.keyClick(radius_widget, Qt.Key.Key_Return)
    assert outlined() == [False, False, False, False]


@pytest.mark.parametrize(
    ("view", "read"),
    [
        (InputView(), lambda view: view.text),
        (FloatInputView(), lambda view: view.value),
        (IntInputView(), lambda view: view.value),
    ],
    ids=["text", "float", "int"],
)
def test_an_edit_is_reported_once_the_view_has_it(
    qtbot: QtBot,
    view: InputView | FloatInputView | IntInputView,
    read: Callable[[Any], object],
) -> None:
    """A check run on each edit (`text_edited`) reads the edited value, not the one before."""
    view.render(RendererType.QT)
    field = _widget(view)
    qtbot.addWidget(field)
    seen: list[object] = []
    view.text_edited.connect(lambda _text: seen.append(read(view)))
    field.show()
    field.setFocus()

    qtbot.keyClicks(field, "42")

    assert seen[-2:] in (["4", "42"], [4.0, 42.0], [4, 42])


def test_float_input_renderer_round_trips_typed_value_and_rejects_bad_input(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    radius_widget = _field_widget(view.pages.inputs.pipe_form.main_pipe.radius)
    assert isinstance(radius_widget, QLineEdit)

    radius_widget.show()
    radius_widget.setFocus()
    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "2000")
    qtbot.keyClick(radius_widget, Qt.Key.Key_Return)
    assert view.pages.inputs.pipe_form.main_pipe.radius.value == 2000.0
    assert view.pages.inputs.pipe_form.log_view.is_visible is True  # tripped the pipe validation

    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "abc")
    assert radius_widget.text() != "abc"  # rejected by the QDoubleValidator

    radius_widget.selectAll()
    qtbot.keyClick(radius_widget, Qt.Key.Key_Backspace)
    assert view.pages.inputs.pipe_form.main_pipe.radius.value is None


def test_a_float_input_shows_its_value_with_at_most_its_decimals(qtbot: QtBot) -> None:
    view = FloatInputView(value=3.14159)
    view.render(RendererType.QT)
    field = _widget(view)
    assert isinstance(field, QLineEdit)
    qtbot.addWidget(field)
    assert field.text() == "3.14159"

    view.decimals = 2
    assert field.text() == "3.14"
    assert view.value == 3.14159  # shown rounded, kept as it was
    view.value = 36.0
    assert field.text() == "36"


def test_int_input_is_a_spin_box_keeping_its_value_within_its_range(qtbot: QtBot) -> None:
    view = HoursMainView()
    view.render(RendererType.QT)
    opening = view.form.opening
    spin_box = _field_widget(opening)
    assert isinstance(spin_box, QSpinBox)
    qtbot.addWidget(spin_box)
    assert (spin_box.minimum(), spin_box.maximum(), spin_box.value()) == (0, 23, 8)

    spin_box.show()
    spin_box.setFocus()
    spin_box.selectAll()
    qtbot.keyClicks(spin_box, "15")
    assert opening.value == 15
    qtbot.keyClick(spin_box, Qt.Key.Key_Up)
    assert opening.value == 16
    spin_box.selectAll()
    qtbot.keyClicks(spin_box, "99")
    assert opening.value == 9  # the second 9 would take it past 23

    opening.value = None
    assert spin_box.text() == ""
    opening.minimum = 10  # Qt would show it, as it raises the 9 still held to 10
    assert (spin_box.minimum(), spin_box.text()) == (10, "")
    qtbot.keyClicks(spin_box, "1")
    assert opening.value is None  # on the way to a value in range, not one yet
    qtbot.keyClicks(spin_box, "2")
    assert opening.value == 12
    spin_box.selectAll()
    qtbot.keyClick(spin_box, Qt.Key.Key_Backspace)
    assert opening.value is None


def test_an_int_input_keeps_its_value_while_a_minus_sign_is_typed(qtbot: QtBot) -> None:
    view = IntInputView(value=3, minimum=-5)
    view.render(RendererType.QT)
    spin_box = _widget(view)
    assert isinstance(spin_box, QSpinBox)
    qtbot.addWidget(spin_box)
    spin_box.show()
    spin_box.setFocus()
    spin_box.selectAll()

    qtbot.keyClicks(spin_box, "-")
    kept = view.value
    qtbot.keyClicks(spin_box, "2")

    assert (kept, view.value) == (3, -2)


def test_a_date_input_is_typed_or_picked_in_the_language_s_format(qtbot: QtBot) -> None:
    view = BookingMainView()
    view.render(RendererType.QT)
    arrival = view.form.arrival
    field = _field_widget(arrival)
    assert isinstance(field, QDateField)
    qtbot.addWidget(field)
    changes: list[datetime.date | None] = []
    arrival.value_changed.connect(changes.append)
    assert field.line_edit.text() == "10/18/2026"  # English's, as the code writes its text

    view.set_language("fr")
    assert field.line_edit.text() == "18/10/2026"
    field.show()
    field.line_edit.selectAll()
    qtbot.keyClicks(field.line_edit, "25/10/20")
    assert (arrival.value, changes) == (datetime.date(2026, 10, 18), [])  # not a date yet
    qtbot.keyClicks(field.line_edit, "26")
    assert (arrival.value, changes) == (datetime.date(2026, 10, 25), [datetime.date(2026, 10, 25)])

    qtbot.mouseClick(field.button, Qt.MouseButton.LeftButton)
    calendar = field.calendar
    assert calendar.isVisible()
    assert calendar.selectedDate() == QDate(2026, 10, 25)
    assert (calendar.minimumDate(), calendar.maximumDate()) == (
        QDate(2026, 10, 1),
        QDate(2026, 12, 31),
    )
    calendar.setSelectedDate(QDate(2026, 11, 3))  # the arrows' move to a day
    days = calendar.findChild(QTableView)
    assert days is not None
    qtbot.keyClick(days, Qt.Key.Key_Return)
    assert not calendar.isVisible()
    assert (arrival.value, field.line_edit.text()) == (datetime.date(2026, 11, 3), "03/11/2026")
    assert changes[-1] == datetime.date(2026, 11, 3)

    field.line_edit.selectAll()
    qtbot.keyClicks(field.line_edit, "31/02")
    qtbot.keyClick(field.line_edit, Qt.Key.Key_Return)  # left as no date: the date back
    assert field.line_edit.text() == "03/11/2026"
    qtbot.mouseClick(field.button, Qt.MouseButton.LeftButton)
    qtbot.keyClick(days, Qt.Key.Key_Return)  # the same day again: nothing to report
    assert len(changes) == 2
    field.line_edit.selectAll()
    qtbot.keyClick(field.line_edit, Qt.Key.Key_Backspace)  # cleared: no date
    assert (arrival.value, changes[-1]) == (None, None)
    # without a date, the calendar opens on today's month, or the nearest it allows
    qtbot.mouseClick(field.button, Qt.MouseButton.LeftButton)
    nearest = min(max(QDate.currentDate(), calendar.minimumDate()), calendar.maximumDate())
    assert (calendar.yearShown(), calendar.monthShown()) == (nearest.year(), nearest.month())
    calendar.close()
    arrival.value = datetime.date(2026, 11, 3)
    arrival.value = None  # set in code: shown empty, the format as its hint, not reported
    assert field.line_edit.text() == ""
    assert field.line_edit.placeholderText() == "dd/mm/yyyy"
    assert len(changes) == 3


def test_a_file_path_is_typed_or_picked_in_qt_s_dialog_and_reloaded(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = DataFileMainView()
    view.render(RendererType.QT)
    view.set_language("fr")
    measurements = view.form.measurements
    field = _field_widget(measurements)
    assert isinstance(field, QFilePathField)
    qtbot.addWidget(field)
    field.show()
    picked: list[Path] = []
    measurements.path_picked.connect(picked.append)
    reloads: list[None] = []
    measurements.reload_clicked.connect(lambda: reloads.append(None))
    asked: list[tuple[str, str, str]] = []
    answer = ("", "")

    def ask(*args: object) -> tuple[str, str]:
        asked.append((str(args[1]), str(args[2]), str(args[3])))
        return answer

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(ask))
    assert field.browse_button.accessibleName() == "Choisir un fichier"
    assert field.reload_button.isVisible()
    # squares as tall as the field, whatever their text or icon
    side = field.line_edit.height()
    assert field.browse_button.size() == field.reload_button.size() == QSize(side, side)
    qtbot.keyClicks(field.line_edit, str(tmp_path / "old.csv"))
    assert measurements.path == tmp_path / "old.csv"

    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)  # cancelled
    assert asked == [("Choisir un fichier", str(tmp_path), "CSV (*.csv);;Text (*.txt *.text)")]
    assert (measurements.text, picked) == (str(tmp_path / "old.csv"), [])
    answer = (str(tmp_path / "new.txt"), "Text (*.txt *.text)")
    qtbot.mouseClick(field.browse_button, Qt.MouseButton.LeftButton)
    assert (measurements.path, field.line_edit.text()) == (tmp_path / "new.txt", answer[0])
    assert picked == [tmp_path / "new.txt"]

    qtbot.mouseClick(field.reload_button, Qt.MouseButton.LeftButton)
    assert len(reloads) == 1
    measurements.has_reload = False
    assert not field.reload_button.isVisible()


def test_a_slider_stops_on_its_steps_its_value_painted_beside_the_track(qtbot: QtBot) -> None:
    view = WorkersMainView()
    view.render(RendererType.QT)
    workers = view.form.workers
    slider = _field_widget(workers)
    assert isinstance(slider, QValueSlider)
    qtbot.addWidget(slider)
    moves: list[int] = []
    workers.value_changed.connect(moves.append)
    assert slider.shown_value() == 5
    plain = QSlider(Qt.Orientation.Horizontal).sizeHint()
    # no taller than a plain slider, the value's slot on its right
    assert slider.sizeHint().height() == plain.height()
    assert slider.sizeHint().width() > plain.width()

    slider.resize(300, slider.sizeHint().height())
    slider.show()
    slider.setFocus()
    slot = slider.value_rect()
    assert slot.right() == slider.width() - 1
    qtbot.keyClick(slider, Qt.Key.Key_Right)
    assert (workers.value, moves) == (8, [8])
    qtbot.keyClick(slider, Qt.Key.Key_End)
    assert (workers.value, moves) == (14, [8, 14])  # the last step, short of 16
    assert slider.value_rect() == slot  # as wide whatever the value: the track keeps its length

    workers.value = 6  # set in code: shown at its nearest step, and not reported
    assert (slider.shown_value(), moves) == (5, [8, 14])
    workers.step = 1
    workers.minimum = 0
    assert (slider.maximum(), slider.shown_value()) == (16, 6)


def test_radio_group_renderer_click_round_trips_value_and_drives_status_bar(qtbot: QtBot) -> None:
    view = PipeMainView()
    # timeout=0, set before render() (see test_status_bar_renderer_... below for why):
    # the click below triggers `_display_message_status_bar`, and the default 3s
    # timeout would otherwise leave a real background `threading.Timer` running
    # past this test, later crashing whatever test happens to be running when it
    # fires against this test's already-destroyed `QStatusBar`.
    view.status_bar.timeout = 0
    view.render(RendererType.QT)
    edge_widget = _field_widget(view.pages.inputs.pipe_form.edge_type)

    # rendering rebuilds the buttons (`refresh` re-applies `values`): the first set is
    # gone at once, not left on screen until the event loop deletes it
    buttons = edge_widget.findChildren(QRadioButton)
    assert len(buttons) == 3
    chamfer_button = next(b for b in buttons if b.text() == EdgeType.Chamfer.value)
    chamfer_button.click()

    assert view.pages.inputs.pipe_form.edge_type.value == EdgeType.Chamfer
    assert "Chamfer" in view.status_bar.message  # value_changed -> status bar

    chamfer_renderer = view.pages.inputs.pipe_form.chamfer.renderer
    assert isinstance(chamfer_renderer, QtWidgetRenderer)
    chamfer_widget = chamfer_renderer.qt_object
    assert chamfer_widget is not None
    assert chamfer_widget.isVisible() is True  # edge_type -> group visibility


def test_radio_buttons_sit_together_at_the_start_of_their_row(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    edge_widget = _field_widget(view.pages.inputs.pipe_form.edge_type)
    edge_widget.resize(600, 40)
    edge_widget.show()
    # rendering already rebuilt them once (`refresh` re-applies `values`)
    buttons = edge_widget.findChildren(QRadioButton)
    qtbot.waitUntil(lambda: all(button.isVisible() for button in buttons))  # laid out
    buttons.sort(key=lambda button: button.x())

    assert buttons[0].x() == 0
    # each next to the one before, at its own width, not spread over the row: the stretch
    # after them takes the rest. Not a share of the row: the text's width differs between
    # systems' fonts.
    layout = edge_widget.layout()
    assert layout is not None
    for before, after in zip(buttons, buttons[1:]):
        assert after.x() == before.geometry().right() + 1 + layout.spacing()
    assert [button.width() for button in buttons] == [
        button.sizeHint().width() for button in buttons
    ]
    assert buttons[-1].geometry().right() < edge_widget.width() - 1


def test_clicking_the_checkbox_checks_the_view_and_enables_its_row(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    insulated = view.pages.inputs.pipe_form.insulated
    checkbox = _field_widget(insulated)
    assert isinstance(checkbox, QCheckBox)
    assert checkbox.text() == "Insulated pipe"
    thickness_widget = _field_widget(view.pages.inputs.pipe_form.insulation_thickness)
    assert not thickness_widget.isEnabled()
    toggled: list[bool] = []
    insulated.toggled.connect(toggled.append)

    checkbox.click()

    assert insulated.is_checked is True
    assert thickness_widget.isEnabled()  # toggled -> the thickness row
    assert toggled == [True]

    # set in code: the box follows, but only the user's toggles are reported
    insulated.is_checked = False
    assert not checkbox.isChecked()
    assert toggled == [True]


def test_the_summary_table_shows_each_edit_and_cannot_be_edited(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    assert isinstance(view.pages.results.summary.renderer, QtWidgetRenderer)
    box = view.pages.results.summary.renderer.qt_object
    assert isinstance(box, QFilterTable)
    table = box.table
    model = table.model()
    assert model.headerData(3, Qt.Orientation.Horizontal) == "Half Length"
    radius_widget = _field_widget(view.pages.inputs.pipe_form.main_pipe.radius)
    assert isinstance(radius_widget, QLineEdit)

    radius_widget.show()
    radius_widget.setFocus()
    radius_widget.selectAll()
    qtbot.keyClicks(radius_widget, "35")
    qtbot.keyClick(radius_widget, Qt.Key.Key_Return)

    cells = [model.index(0, column).data() for column in range(model.columnCount())]
    assert cells == ["Main Pipe", "35", "20", "200"]

    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    window.resize(900, 1100)
    window.show()
    qtbot.waitExposed(window)
    name_renderer = view.pages.inputs.pipe_form.name.renderer
    assert isinstance(name_renderer, RendererContainer)
    name_label = name_renderer.get_renderer("label")
    assert isinstance(name_label, QtWidgetRenderer)
    assert isinstance(name_label.qt_object, QFormLabel)
    label_left = name_label.qt_object.mapTo(window, QPoint(0, 0)).x()
    view.pages.navigate("results")
    qtbot.waitUntil(table.isVisible)
    # as tall as its rows in the window: no empty block under them
    rows_height = model.rowCount() * table.rowHeight(0)
    assert 0 <= table.viewport().height() - rows_height < table.rowHeight(0)
    # lined up with the form of the other page, whose labels start its rows
    assert table.mapTo(window, QPoint(0, 0)).x() == label_left
    table.setCurrentIndex(model.index(0, 1))
    table.setFocus()
    qtbot.keyClick(table, Qt.Key.Key_F2)  # the edit key
    assert table.state() is not QAbstractItemView.State.EditingState


def _qt_part(row: Any, part: str) -> QWidget:
    """Get the widget of one of a form row's parts: "label", "field" or "log"."""
    assert isinstance(row.renderer, RendererContainer)
    renderer = row.renderer.get_renderer(part)
    assert isinstance(renderer, QtWidgetRenderer)
    assert isinstance(renderer.qt_object, QWidget)
    return renderer.qt_object


def test_a_form_row_outside_a_form_shows_as_a_form_shows_it(qtbot: QtBot) -> None:
    view = LoneRowsMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    hour, name, note = view.sidebar.hour, view.column.name, view.note

    # in the sidebar's dock, a column, and the main view itself: each part, as in a form
    for row, parts in ((hour, ["label", "field"]), (name, ["label", "field"]), (note, ["field"])):
        for part in parts:
            widget = _qt_part(row, part)
            # in the window: a widget never added is "visible" to it too
            assert window.isAncestorOf(widget)
            assert widget.isVisibleTo(window)
    label = _qt_part(name, "label")
    assert isinstance(label, QFormLabel)
    name.label = "Full name"
    assert label.text_label.text() == "Full name"
    name.is_visible = False
    assert not _qt_part(name, "field").isVisibleTo(window)
    # a list's rows: one record more keeps the first one's row, its text with it
    view.names.items = ["First"]
    (first,) = view.names.item_views
    first_field = _qt_part(first, "field")
    view.names.items = ["First", "Second"]
    assert view.names.item_views[0] is first
    assert _qt_part(first, "field") is first_field
    for item_view in view.names.item_views:
        assert window.isAncestorOf(_qt_part(item_view, "label"))


def test_the_help_button_beside_a_row_label_shows_the_help_when_clicked(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    edge_type = view.pages.inputs.pipe_form.edge_type
    renderer = edge_type.renderer
    assert isinstance(renderer, RendererContainer)
    label_renderer = renderer.get_renderer("label")
    assert isinstance(label_renderer, QtWidgetRenderer)
    label_widget = label_renderer.qt_object
    assert isinstance(label_widget, QFormLabel)
    help_text = "How the edge joining the two pipes is finished"
    assert label_widget.text_label.text() == "Edge Type"
    assert label_widget.toolTip() == help_text  # on hover
    button = label_widget.help_button
    assert button.text() == "?"
    assert button.accessibleName() == "Help"
    assert button.focusPolicy() & Qt.FocusPolicy.TabFocus  # Tab reaches it
    label_widget.show()
    qtbot.waitExposed(label_widget)

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # or a tap, or Space

    qtbot.waitUntil(lambda: QToolTip.isVisible() and QToolTip.text() == help_text)
    edge_type.help = ""
    assert button.isHidden()
    assert label_widget.toolTip() == ""


def test_group_form_renderer_sets_the_qgroupbox_title(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    renderer = view.pages.inputs.pipe_form.main_pipe.renderer
    assert isinstance(renderer, QtWidgetRenderer)
    widget = renderer.qt_object
    assert isinstance(widget, QGroupBox)
    assert widget.title() == "Main Pipe"


def test_status_bar_renderer_shows_a_message_on_the_widget(qtbot: QtBot) -> None:
    view = PipeMainView()
    # timeout=0, set before render(): `StatusBar` has no refresh handler for
    # "timeout" itself (only "message" is dispatched), so setting it once a
    # renderer is bound would raise `MissingRefreshAttributeFunctionError` via
    # `notify_renderer`. Zero also means no auto-dismiss `threading.Timer` is left
    # running past this test - it would otherwise eventually fire against an
    # already-deleted `QStatusBar` from a later test's own window (see
    # `tests/test_statusbar_thread_safety.py` for that timer's actual coverage).
    view.status_bar.timeout = 0
    view.render(RendererType.QT)
    renderer = view.status_bar.renderer
    assert isinstance(renderer, QtWidgetRenderer)
    widget = renderer.qt_object
    assert isinstance(widget, QStatusBar)

    view.status_bar.show_message("hi there")
    assert widget.currentMessage() == "hi there"


def test_main_renderer_builds_the_window_from_view_state(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)

    assert window.windowTitle() == "Pipe Form"
    assert window.minimumWidth() == 720
    assert window.minimumHeight() == 480
    assert isinstance(window.statusBar(), QStatusBar)


def test_menu_renderer_builds_a_real_qmenu_with_actions_and_shortcuts(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)

    menus = []
    for action in window.menuBar().actions():
        menu = action.menu()
        assert isinstance(menu, QMenu)
        menus.append(menu)
    assert [menu.title() for menu in menus] == ["File", "Pipe", "Language"]
    file_menu = menus[0]
    action_texts = [a.text() for a in file_menu.actions()]
    assert action_texts == ["New", "Open", "Save", "Save As", "", "Exit"]
    open_action = next(a for a in file_menu.actions() if a.text() == "Open")
    assert open_action.shortcut().toString() == "Ctrl+O"
    assert any(a.isSeparator() for a in file_menu.actions())


def test_a_checkable_action_and_its_qaction_toggle_together(qtbot: QtBot) -> None:
    window = QMainWindow()
    qtbot.addWidget(window)
    action = ActionView(text="Wrap", is_checkable=True)
    action.render(RendererType.QT)
    assert isinstance(action.renderer, QtActionRenderer)
    action.renderer.set_parent_rendered_object(window)
    action.renderer.render()
    qaction = action.renderer.qt_object
    assert isinstance(qaction, QAction)

    qaction.trigger()  # `QAction` checks itself before emitting `triggered`

    assert action.is_checked is True
    assert qaction.isChecked() is True

    qaction.trigger()

    assert action.is_checked is False
    assert qaction.isChecked() is False


def test_open_file_action_runs_the_native_dialog_and_loads_state(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    donor = PipeMainView()
    donor.pages.inputs.pipe_form.name.text = "loaded_name"
    filepath = tmp_path / "state.pipe"
    donor.save_state(filepath)

    view = PipeMainView()
    _add_reference_to_signals(view, None)  # OpenFileAction._load_state needs `main_view`
    view.render(RendererType.QT)
    assert isinstance(view.renderer, MainRenderer)

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(filepath), ".pipe (*.pipe)")),  # noqa: ARG005
    )

    open_action_renderer = view.file_menu.open_file.renderer
    assert isinstance(open_action_renderer, QtWidgetRenderer)
    action = open_action_renderer.qt_object
    assert action is not None
    action.trigger()

    assert view.file_view.filepath == filepath
    assert view.pages.inputs.pipe_form.name.text == "loaded_name"
    name_widget = _field_widget(view.pages.inputs.pipe_form.name)
    assert isinstance(name_widget, QLineEdit)
    assert name_widget.text() == "loaded_name"


def test_save_file_action_runs_the_native_dialog_and_saves_state(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = PipeMainView()
    _add_reference_to_signals(view, None)
    view.render(RendererType.QT)
    assert isinstance(view.renderer, MainRenderer)

    view.pages.inputs.pipe_form.name.text = "saved_name"
    target = tmp_path / "out"  # no extension - the renderer must add one
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), ".pipe (*.pipe)")),  # noqa: ARG005
    )

    save_action_renderer = view.file_menu.save.renderer
    assert isinstance(save_action_renderer, QtWidgetRenderer)
    action = save_action_renderer.qt_object
    assert action is not None
    action.trigger()

    saved_path = target.with_suffix(".pipe")
    assert saved_path.exists()
    assert view.file_view.filepath == saved_path
    data = json.loads(saved_path.read_text())["views"]
    assert data["pages"]["inputs"]["pipe_form"]["name"]["text"] == "saved_name"


def _widget(view: View) -> QWidget:
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QWidget)
    return widget


def _table(view: View) -> QTextTableView:
    box = _widget(view)
    assert isinstance(box, QFilterTable)
    return box.table


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

    for row, packed_at_end in ((view.start, False), (view.end, True)):
        first, second = (_widget(button).geometry() for button in (row.first, row.second))
        width = _widget(row).width()
        # as wide as their text, side by side
        assert first.width() == _widget(row.first).sizeHint().width()
        assert 0 < second.left() - first.right() < 20
        if packed_at_end:
            assert second.right() == width - 1
        else:
            assert first.left() == 0


def test_the_toolbar_shows_one_page_at_a_time(qtbot: QtBot) -> None:
    view = PagesMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()
    toolbar = window.findChild(QToolBar)
    assert isinstance(toolbar, QToolBar)
    actions = {action.text(): action for action in toolbar.actions()}
    assert list(actions) == ["Inputs", "Results"]
    name = view.router.inputs.name.renderer
    total = view.router.results.total.renderer
    assert isinstance(name, QtWidgetRenderer)
    assert isinstance(total, QtWidgetRenderer)
    assert name.qt_object is not None
    assert total.qt_object is not None
    assert name.qt_object.isVisible()
    assert not total.qt_object.isVisible()

    results_button = toolbar.widgetForAction(actions["Results"])
    qtbot.mouseClick(results_button, Qt.MouseButton.LeftButton)
    assert view.router.current_route == "results"
    assert total.qt_object.isVisible()
    assert not name.qt_object.isVisible()
    # clicking the shown page's entry again leaves it checked, the other unchecked
    qtbot.mouseClick(results_button, Qt.MouseButton.LeftButton)
    assert actions["Results"].isChecked()
    assert not actions["Inputs"].isChecked()

    view.router.navigate("inputs")  # from app code
    assert name.qt_object.isVisible()
    assert actions["Inputs"].isChecked()
    assert not actions["Results"].isChecked()


def test_a_sidebar_is_docked_left_of_the_pages_whatever_the_page(qtbot: QtBot) -> None:
    view = SidebarMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    dock = _widget(view.sidebar)
    assert isinstance(dock, QSidebar)
    assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    # part of the layout: the user can't close, move or float it
    assert dock.features() == QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
    create = _widget(view.sidebar.create)
    assert dock.isAncestorOf(create)
    window.resize(900, 500)
    window.show()
    assert dock.title.text() == "New record"
    assert dock.geometry().right() < window.centralWidget().geometry().left()

    view.router.navigate("results")
    assert create.isVisible()  # still beside the other page
    view.sidebar.title = ""
    assert not dock.title.isVisible()  # no empty heading
    view.sidebar.is_visible = False
    assert not dock.isVisible()


def test_a_sidebar_retracts_to_a_strip_by_its_button_and_back(qtbot: QtBot) -> None:
    view = SidebarMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    dock = _widget(view.sidebar)
    assert isinstance(dock, QSidebar)
    create = _widget(view.sidebar.create)
    toggles: list[bool] = []
    view.sidebar.toggled.connect(toggles.append)
    window.resize(900, 500)
    window.show()
    qtbot.waitExposed(window)
    width = dock.width()
    assert dock.toggle.toolTip() == "Sidebar"

    qtbot.mouseClick(dock.toggle, Qt.MouseButton.LeftButton)
    assert (view.sidebar.is_expanded, toggles) == (False, [False])
    assert not create.isVisible()
    assert dock.toggle.isVisible()  # the strip's button brings it back
    qtbot.waitUntil(lambda: dock.width() < width / 4)  # the pages take the room

    view.sidebar.is_expanded = True  # set in code: expanded, and not reported
    assert create.isVisible()
    assert toggles == [False]
    qtbot.waitUntil(lambda: dock.width() == width)  # its width before


def _tree_item(tree: QTreeWidget, *labels: str) -> QTreeWidgetItem:
    """Get the item down a tree's labels, from a top-level one."""
    items = tree.findItems(labels[-1], Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
    (item,) = [item for item in items if _labels(item) == labels]
    return item


def _labels(item: QTreeWidgetItem) -> tuple[str, ...]:
    parent = item.parent()
    return (*(() if parent is None else _labels(parent)), item.text(0))


def test_a_tree_selects_and_expands_its_nodes_by_click_and_key(qtbot: QtBot) -> None:
    view = SiteMainView()
    view.render(RendererType.QT)
    site = view.site
    assert isinstance(site.renderer, QtWidgetRenderer)
    tree = site.renderer.qt_object
    assert isinstance(tree, QTreeWidget)
    qtbot.addWidget(tree)
    selections: list[tuple[str, ...]] = []
    toggles: list[tuple[tuple[str, ...], bool]] = []
    site.selection_changed.connect(selections.append)
    site.toggled.connect(lambda path, is_expanded: toggles.append((path, is_expanded)))
    tree.show()
    assert _tree_item(tree, "Building A").isExpanded()
    assert not _tree_item(tree, "Building B").isExpanded()

    room = _tree_item(tree, "Building A", "Floor 1")
    qtbot.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(room).center()
    )
    assert (site.selected, selections) == (("Building A", "Floor 1"), [("Building A", "Floor 1")])
    tree.setFocus()
    qtbot.keyClick(tree, Qt.Key.Key_Right)
    assert site.expanded == [("Building A",), ("Building A", "Floor 1")]
    assert toggles == [(("Building A", "Floor 1"), True)]
    qtbot.keyClick(tree, Qt.Key.Key_Down)  # onto its first room
    assert selections[-1] == ("Building A", "Floor 1", "Room 101")

    # set in code: shown, and not reported
    site.expanded = [("Building B",)]
    site.selected = ("Building B", "Floor 1")
    assert not _tree_item(tree, "Building A").isExpanded()
    assert _tree_item(tree, "Building B").isExpanded()
    assert tree.selectedItems() == [_tree_item(tree, "Building B", "Floor 1")]
    assert (len(selections), len(toggles)) == (2, 1)
    # new nodes keep the selection still in them
    site.nodes = [*site.nodes, TreeNode("Garden")]
    assert tree.topLevelItemCount() == 4
    assert tree.selectedItems() == [_tree_item(tree, "Building B", "Floor 1")]


def test_a_tree_shows_its_nodes_icon_style_and_mark_named_by_a_tooltip(
    qtbot: QtBot, tmp_path: Path
) -> None:
    icon = tmp_path / "building.png"
    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor("blue"))
    assert pixmap.save(str(icon))
    view = SiteMainView()
    view.render(RendererType.QT)
    site = view.site
    assert isinstance(site.renderer, QtWidgetRenderer)
    tree = site.renderer.qt_object
    assert isinstance(tree, QTreeWidget)
    qtbot.addWidget(tree)
    assert tree.isColumnHidden(1)  # no node marked: no column for the marks

    site.nodes = styled_site(str(icon))
    assert not tree.isColumnHidden(1)
    building, parking = _tree_item(tree, "Building A"), _tree_item(tree, "Parking")
    assert not building.icon(0).isNull()
    assert parking.icon(0).isNull()
    assert (building.font(0).bold(), building.font(0).underline()) == (True, False)
    assert (parking.font(0).bold(), parking.font(0).underline()) == (False, True)
    done, failed = (
        _tree_item(tree, "Building A", "Room 101"),
        _tree_item(tree, "Building A", "Room 102"),
    )
    assert building.icon(1).isNull()
    assert not done.icon(1).isNull()
    assert done.icon(1).cacheKey() != failed.icon(1).cacheKey()
    assert [item.toolTip(1) for item in (done, failed, parking)] == ["Done", "Error", "Warning"]
    site.done_text = "Terminé"  # as the main view's language changes
    assert [item.toolTip(1) for item in (done, failed)] == ["Terminé", "Error"]


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
    created = _widget(tabs.history.created)
    assert _widget(tabs.details.length).isVisible()
    assert not created.isVisible()

    qtbot.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(1).center())
    assert (tabs.current_index, picks) == (1, [1])
    assert created.isVisible()
    assert tabs.current_tab is tabs.history

    tabs.current_index = 0  # set in code: shown, and not reported
    assert (tab_widget.currentIndex(), picks) == (0, [1])
    tabs.history.title = "Changes"
    assert tab_widget.tabText(1) == "Changes"
    tabs.notes.is_enabled = False
    assert not tab_widget.isTabEnabled(2)
    tabs.notes.is_visible = False
    assert not tab_widget.isTabVisible(2)


def test_a_form_dialog_s_ok_follows_its_form_s_checks(qtbot: QtBot) -> None:
    view = EditedPipeMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    dialog = _widget(view.edit_dialog)
    assert isinstance(dialog, QFormDialog)
    parent = dialog.parentWidget()
    assert parent is not None
    assert parent.window() is window  # modal over the window
    name = _field_widget(view.edit_dialog.form.name)
    assert isinstance(name, QLineEdit)
    assert dialog.isAncestorOf(name)

    qtbot.mouseClick(_widget(view.edit), Qt.MouseButton.LeftButton)
    assert dialog.isVisible()
    assert dialog.windowTitle() == "Edit the pipe"
    assert dialog.ok_button.isEnabled()
    name.selectAll()
    qtbot.keyClick(name, Qt.Key.Key_Delete)
    assert not dialog.ok_button.isEnabled()  # a name is mandatory
    qtbot.keyClicks(name, "Return")
    assert dialog.ok_button.isEnabled()
    qtbot.mouseClick(dialog.ok_button, Qt.MouseButton.LeftButton)
    assert not dialog.isVisible()
    assert view.pipe.text == "Return, 12 m"

    qtbot.mouseClick(_widget(view.edit), Qt.MouseButton.LeftButton)
    qtbot.keyClicks(name, "!")
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)  # Cancel
    assert not dialog.isVisible()
    assert view.pipe.text == "Return, 12 m"
    # its native window released (see the confirmation's), its form kept for next time
    qtbot.waitUntil(lambda: not dialog.testAttribute(Qt.WidgetAttribute.WA_WState_Created))
    qtbot.mouseClick(_widget(view.edit), Qt.MouseButton.LeftButton)
    assert dialog.isVisible()
    assert dialog.isAncestorOf(name)

    qtbot.keyClicks(name, "?")
    dialog.close()  # the title bar's button: as Cancel
    assert not dialog.isVisible()
    assert view.pipe.text == "Return, 12 m"


def test_a_toolbar_docks_its_actions_beside_the_pages(qtbot: QtBot) -> None:
    view = ToolBarMainView()
    _add_reference_to_signals(view, None)
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()
    toolbar, pages = window.findChildren(QToolBar)
    assert window.toolBarArea(toolbar) == Qt.ToolBarArea.TopToolBarArea
    assert toolbar.windowTitle() == "Edit"
    assert [(action.text(), action.isSeparator()) for action in toolbar.actions()] == [
        ("Open", False),
        ("", True),
        ("Run", False),
        ("Wrap", False),
    ]
    assert [action.text() for action in pages.actions()] == ["Inputs", "Results"]
    _, _, run, wrap = toolbar.actions()

    qtbot.mouseClick(toolbar.widgetForAction(run), Qt.MouseButton.LeftButton)
    assert view.router.results.total.text == "Ran"
    qtbot.mouseClick(toolbar.widgetForAction(wrap), Qt.MouseButton.LeftButton)
    assert view.toolbar.wrap.is_checked
    view.toolbar.wrap.is_checked = False
    assert not wrap.isChecked()
    view.toolbar.is_enabled = False
    assert not toolbar.widgetForAction(run).isEnabled()


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
    left, no_button = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    for kind, position, button, buttons in (
        (QMouseEvent.Type.MouseButtonPress, start, left, left),
        (QMouseEvent.Type.MouseMove, end, no_button, left),
        (QMouseEvent.Type.MouseButtonRelease, end, left, no_button),
    ):
        local = QPointF(position)
        event = QMouseEvent(
            kind,
            local,
            QPointF(widget.mapToGlobal(position)),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(widget, event)


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


def test_a_metric_shows_its_value_large_and_its_change_as_a_badge_colored_by_sign(
    qtbot: QtBot,
) -> None:
    view = JobsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    running, failed = _widget(view.summary.running), _widget(view.summary.failed)
    assert isinstance(running, QMetric)
    assert isinstance(failed, QMetric)
    assert (running.label.text(), running.value.text()) == ("Running", "3")
    assert running.value.font().pointSizeF() > running.label.font().pointSizeF()
    assert running.badge.text() == "↑ 2 since yesterday"
    assert not failed.badge.isVisibleTo(window)  # no change given

    window.show()
    rise = running.badge.palette().color(running.badge.foregroundRole())
    view.summary.running.delta = -2
    running.badge.ensurePolished()
    fall = running.badge.palette().color(running.badge.foregroundRole())
    assert running.badge.text() == "↓ 2 since yesterday"
    assert rise != fall
    view.summary.running.delta_text = ""
    assert running.badge.text() == "↓ 2"
    view.summary.failed.delta = 1
    assert failed.badge.isVisibleTo(window)


def test_the_progress_bar_follows_its_view(qtbot: QtBot) -> None:
    view = PagesMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    progress = view.router.results.progress
    assert isinstance(progress.renderer, QtWidgetRenderer)
    bar = progress.renderer.qt_object
    assert isinstance(bar, QProgressBar)
    assert (bar.value(), bar.maximum()) == (0, 100)

    progress.value = 40
    assert bar.value() == 40
    progress.maximum = 200
    assert (bar.value(), bar.maximum()) == (40, 200)
    progress.value = 250  # Qt ignores a value out of range: the bar would stay at 40
    assert bar.value() == 200
    progress.maximum = None
    assert (bar.minimum(), bar.maximum()) == (0, 0)  # Qt's busy bar


def test_clicking_the_button_runs_what_its_view_connects(qtbot: QtBot) -> None:
    view = PagesMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()
    inputs = view.router.inputs
    assert isinstance(inputs.submit.renderer, QtWidgetRenderer)
    button = inputs.submit.renderer.qt_object
    assert isinstance(button, QPushButton)
    assert button.text() == "Submit"
    # as wide as its text, not the page's whole width
    assert button.width() < window.width() / 2
    inputs.name.text = "Ada"

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert view.router.results.total.text == "Submitted: Ada"
    inputs.submit.text = "Send"
    assert button.text() == "Send"
    # the main action stands out; a destroying one is red
    assert button.isDefault()
    inputs.submit.variant = ButtonVariant.DANGER
    assert not button.isDefault()
    assert "red" in button.styleSheet()
    inputs.submit.variant = ButtonVariant.SECONDARY
    assert (button.isDefault(), button.styleSheet()) == (False, "")


def _dialog_window(qtbot: QtBot) -> tuple[DialogsMainView, QMainWindow, QMessageBox]:
    view = DialogsMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()
    box = window.findChild(QMessageBox)
    assert isinstance(box, QMessageBox)
    return view, window, box


def _shown_buttons(box: QMessageBox) -> dict[str, QAbstractButton]:
    return {button.text(): button for button in box.buttons() if button.isVisibleTo(box)}


def test_a_confirmation_opens_over_the_window_and_answers_with_its_buttons(
    qtbot: QtBot,
) -> None:
    view, window, box = _dialog_window(qtbot)
    assert not box.isVisible()

    view.edit_menu.clear.triggered.emit()
    assert box.isVisible()
    assert box.isModal()
    assert box.window() is not window
    parent = box.parentWidget()
    assert parent is not None
    assert parent.window() is window
    # macOS shows no title on a message box: its bold text is the title there
    shown = (
        (box.text(), box.informativeText())
        if sys.platform == "darwin"
        else (box.windowTitle(), box.text())
    )
    assert shown == ("Clear the name", "The name will be lost.")
    buttons = _shown_buttons(box)
    assert list(buttons) == ["Clear", "Cancel"]

    qtbot.keyClick(box, Qt.Key.Key_Escape)
    # macOS clicks the Escape button with an animation, later
    qtbot.waitUntil(lambda: not box.isVisible())
    assert not view.confirm_clear.is_visible
    assert view.name.text == "Ada"

    view.confirm_clear.open()
    view.confirm_clear.is_visible = False  # closed by the app, not by the box itself
    # its native window released, which WSLg's compositor could otherwise keep drawing
    qtbot.waitUntil(lambda: not box.testAttribute(Qt.WidgetAttribute.WA_WState_Created))
    view.confirm_clear.open()
    assert box.isVisible()  # in a native window of its own again
    qtbot.mouseClick(buttons["Clear"], Qt.MouseButton.LeftButton)
    assert not box.isVisible()
    assert view.name.text == ""


def test_a_dialog_s_title_is_its_bold_text_where_a_message_box_has_no_title(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("composeui.qtcore.qtrenderer._TITLE_AS_TEXT", True)  # as on macOS
    view, _window, box = _dialog_window(qtbot)

    view.confirm_clear.open()
    assert (box.text(), box.informativeText()) == ("Clear the name", "The name will be lost.")

    view.confirm_clear.title = ""  # then the message is the bold text
    assert (box.text(), box.informativeText()) == ("The name will be lost.", "")


def test_a_message_has_one_button_and_escape_or_closing_accepts_it(qtbot: QtBot) -> None:
    view, _window, box = _dialog_window(qtbot)
    dialog = view.confirm_clear
    dialog.kind = DialogKind.MESSAGE

    dialog.open()
    assert list(_shown_buttons(box)) == ["Clear"]
    qtbot.keyClick(box, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: view.name.text == "")  # at once, or after macOS's animation

    view.name.text = "Ada"
    dialog.open()
    box.close()  # from its window's title bar
    assert not dialog.is_visible
    assert view.name.text == ""


def test_clicking_a_table_row_selects_it_and_emits_only_for_the_user(qtbot: QtBot) -> None:
    view = HorizontalMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.tables.narrow)
    emitted: list[list[int]] = []
    view.tables.narrow.selection_changed.connect(emitted.append)

    south = table.visualRect(table.model().index(1, 0)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=south)

    assert view.tables.narrow.selected_rows == [1]
    assert emitted == [[1]]

    # set from code: shown, but not the user's doing
    view.tables.narrow.selected_rows = [2]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [2]
    # new rows still holding it, at the same index then moved: it stays shown
    view.tables.narrow.rows = [["West"], ["South"], ["East"]]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [2]
    view.tables.narrow.rows = [["East"], ["West"]]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [0]
    view.tables.narrow.rows = [["West"]]
    assert table.selectionModel().selectedRows() == []
    assert emitted == [[1]]


def test_each_click_adds_or_removes_its_row_in_a_table_selecting_several(
    qtbot: QtBot,
) -> None:
    view = HorizontalMainView()
    view.tables.narrow.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.tables.narrow)
    emitted: list[list[int]] = []
    view.tables.narrow.selection_changed.connect(emitted.append)

    def click(row: int) -> None:
        center = table.visualRect(table.model().index(row, 0)).center()
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)

    click(2)
    click(0)
    click(2)
    assert view.tables.narrow.selected_rows == [0]
    assert emitted == [[2], [0, 2], [0]]

    # set from code: shown, but not the user's doing
    view.tables.narrow.selected_rows = [1, 2]
    assert sorted(index.row() for index in table.selectionModel().selectedRows()) == [1, 2]
    # back to a single row: a click replaces it
    view.tables.narrow.selection_mode = SelectionMode.SINGLE
    click(0)
    assert view.tables.narrow.selected_rows == [0]
    assert emitted == [[2], [0, 2], [0], [0]]


def test_double_clicking_an_editable_cell_edits_it_keeping_the_selection(qtbot: QtBot) -> None:
    view = EditableTableMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.places)
    model = table.model()
    edited: list[tuple[int, int, str, list[str]]] = []

    def record(row: int, column: int, text: str) -> None:
        # the row as it was: the edit is applied once the callbacks have run
        edited.append((row, column, text, view.places.rows[row]))

    view.places.cell_edited.connect(record)

    def edit(row: int, column: int, text: str) -> None:
        center = table.visualRect(model.index(row, column)).center()
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
        qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
        editor = table.focusWidget()
        assert isinstance(editor, QLineEdit)
        editor.selectAll()
        qtbot.keyClicks(editor, text)
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        # Qt commits the text and closes the editor in a queued call
        qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)

    # the harbour's row is short of its note: the edit fills it
    edit(1, 1, "Busy")
    assert view.places.rows == [["Lake", "Calm"], ["Harbour", "Busy"]]
    assert edited == [(1, 1, "Busy", ["Harbour"])]
    # its row moved nowhere: it stays selected
    assert view.places.selected_rows == [1]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [1]

    def answer(row: int, column: int, text: str) -> None:
        if text == "Windy":  # applied, the rows sorted by note: the lake moves last
            rows = replace_cell(view.places.rows, row, column, text)
            view.places.rows = sorted(rows, key=lambda cells: cells[1])
        elif text == "Foggy":
            raise EditRefusedError

    view.places.cell_edited.connect(answer)
    # the table shows the app's rows, its selection following the edited row
    edit(0, 1, "Windy")
    assert view.places.rows == [["Harbour", "Busy"], ["Lake", "Windy"]]
    assert model.index(1, 1).data() == "Windy"
    assert view.places.selected_rows == [1]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [1]
    # refused: the table shows the old text again, the row still selected
    edit(1, 1, "Foggy")
    assert view.places.rows == [["Harbour", "Busy"], ["Lake", "Windy"]]
    assert model.index(1, 1).data() == "Windy"
    assert [index.row() for index in table.selectionModel().selectedRows()] == [1]

    # the places themselves aren't editable
    center = table.visualRect(model.index(0, 0)).center()
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert table.state() is not QAbstractItemView.State.EditingState
    assert [edit[:3] for edit in edited] == [(1, 1, "Busy"), (0, 1, "Windy"), (1, 1, "Foggy")]


def test_picking_a_combobox_cell_s_option_with_the_mouse_edits_it_once(qtbot: QtBot) -> None:
    headers = ["Name", "Role"]
    table = QTextTableView()
    qtbot.addWidget(table)
    table.set_editable_columns([1])
    table.set_cell_widgets({1: CellWidget.combobox(["Input", "Output"])})
    edited: list[tuple[int, int, str]] = []

    def edit(row: int, column: int, text: str) -> None:
        edited.append((row, column, text))
        # answering an edit with new rows, as a view does, resets the model
        table.set_table(headers, [["a", text]])

    table.cell_edited.connect(edit)
    table.set_table(headers, [["a", "Input"]])
    table.show()
    # a click opens the combobox; a click on its popup's option picks it. Qt only logs a
    # commit to a view that no longer has the editor, which fails the test as a warning
    qtbot.mouseClick(
        table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=table.visualRect(table.model().index(0, 1)).center(),
    )
    qtbot.waitUntil(lambda: table.state() is QAbstractItemView.State.EditingState)
    editor = table.viewport().findChild(QComboBox)
    assert editor is not None
    popup = editor.view()
    option = popup.visualRect(popup.model().index(1, 0)).center()
    qtbot.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton, pos=option)
    qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)
    assert edited == [(0, 1, "Output")]
    qtbot.waitUntil(lambda: table.viewport().findChild(QComboBox) is None)


def test_a_table_s_cell_widgets_edit_their_cells_or_report_their_clicks(qtbot: QtBot) -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.variables)
    model, header = table.model(), table.horizontalHeader()
    assert isinstance(header, QCheckHeader)
    events: list[tuple[int, ...] | tuple[int, int, str]] = []
    view.variables.cell_edited.connect(lambda row, column, text: events.append((row, column, text)))
    view.variables.cell_clicked.connect(lambda row, column: events.append((row, column)))

    def checks() -> list[Any]:
        return [model.index(row, 0).data(Qt.ItemDataRole.CheckStateRole) for row in range(2)]

    # a check box shows no text; the header's box shows the column's
    assert checks() == [Qt.CheckState.Checked, Qt.CheckState.Unchecked]
    assert model.index(0, 0).data() is None
    icon = model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DecorationRole)
    assert icon is not None
    # Space toggles the current row's box, the header's box following
    table.setCurrentIndex(model.index(1, 0))
    qtbot.keyClick(table, Qt.Key.Key_Space)
    assert view.variables.rows[1][0] == "True"
    assert checks() == [Qt.CheckState.Checked, Qt.CheckState.Checked]
    assert (
        model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DecorationRole) is not icon
    )
    # the header's box unchecks every row, sorting nothing
    box = QPoint(header.sectionViewportPosition(0) + header.box_width() // 2, header.height() // 2)
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=box)
    assert [row[0] for row in view.variables.rows] == ["False", "False"]
    assert checks() == [Qt.CheckState.Unchecked, Qt.CheckState.Unchecked]

    # a click on a role opens a combobox of the roles
    center = table.visualRect(model.index(0, 2)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    qtbot.waitUntil(lambda: table.state() is QAbstractItemView.State.EditingState)
    editor = table.viewport().findChild(QComboBox)
    assert isinstance(editor, QComboBox)
    assert [editor.itemText(item) for item in range(editor.count())] == ["Input", "Output"]
    editor.hidePopup()
    editor.setCurrentIndex(1)
    editor.activated.emit(1)
    qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)
    assert view.variables.rows[0][2] == "Output"

    # a click on a button reports it, not one on its cell's text; a click on a link too
    button = table.visualRect(model.index(1, 3))
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=button.center())
    qtbot.mouseClick(
        table.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(button.right() - 4, button.center().y()),
    )
    link = table.visualRect(model.index(0, 4)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=link)
    assert events == [
        (1, 0, "True"),
        (0, 0, "False"),
        (1, 0, "False"),
        (0, 2, "Output"),
        (1, 3),
        (0, 4),
    ]
    # not editable, a role is shown only: no combobox opens
    view.variables.editable_columns = [0]
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert table.state() is not QAbstractItemView.State.EditingState
    # nor are the boxes, the header's checking none of them
    view.variables.editable_columns = []
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=box)
    assert [row[0] for row in view.variables.rows] == ["False", "False"]


def test_a_table_s_cells_and_headers_look_as_the_view_says(qtbot: QtBot) -> None:
    view = StyledTablesMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.points)
    model = table.model()

    def data(row: int, column: int, role: Qt.ItemDataRole) -> Any:
        return model.index(row, column).data(role)

    # NaN on red, its text white; a warning on light yellow, its text black, marked
    assert data(1, 2, Qt.ItemDataRole.BackgroundRole) == QColor("#dc2626")
    assert data(1, 2, Qt.ItemDataRole.ForegroundRole) == QColor("#ffffff")
    assert data(2, 3, Qt.ItemDataRole.ForegroundRole) == QColor("#000000")
    assert data(2, 3, Qt.ItemDataRole.DecorationRole) is not None
    assert data(2, 3, Qt.ItemDataRole.ToolTipRole) == "Warning"
    view.points.warning_text = "Attention"
    assert data(2, 3, Qt.ItemDataRole.ToolTipRole) == "Attention"
    # the group covers its two points
    assert (table.rowSpan(0, 0), table.rowSpan(2, 0)) == (2, 1)

    # a disabled cell of an editable column is neither typed in nor checked
    point = table.visualRect(model.index(1, 1)).center()
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert table.state() is not QAbstractItemView.State.EditingState
    box = table.visualRect(model.index(1, 4)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=box)
    assert view.points.rows[1][4] == "False"

    # the group's row doubles the header, a click on it sorting nothing
    header = table.horizontalHeader()
    view.points.sortable_columns = [2]
    group = QPoint(header.sectionViewportPosition(2) + 4, header.height() // 4)
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=group)
    assert view.points.sort_column is None
    column = QPoint(group.x(), 3 * header.height() // 4)
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=column)
    assert view.points.sort_column == 2
    unsortable = QPoint(header.sectionViewportPosition(0) + 4, column.y())
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=unsortable)
    assert view.points.sort_column == 2
    height = header.sizeHint().height()
    view.points.header_groups = []
    assert 2 * header.sizeHint().height() == height

    # the key/value table's keys head its rows; the points have no row headers
    numbers = _table(view.numbers)
    assert numbers.verticalHeader().isVisible()
    assert numbers.model().headerData(0, Qt.Orientation.Vertical) == "Number of calls"
    assert not table.verticalHeader().isVisible()

    # new looks show at once, in place of the old ones
    view.points.cell_styles = {(0, 2): CellStyle(background="#dc2626")}
    assert data(0, 2, Qt.ItemDataRole.BackgroundRole) == QColor("#dc2626")
    assert data(1, 2, Qt.ItemDataRole.BackgroundRole) is None
    view.numbers.row_headers = ["Calls", "Time (s)"]
    assert numbers.model().headerData(0, Qt.Orientation.Vertical) == "Calls"


# Qt warned "commitData called with an editor that does not belong to this view"
@pytest.mark.qt_log_level_fail("WARNING")
@pytest.mark.qt_log_ignore("propagateSizeHints")
def test_an_edit_answered_with_new_rows_closes_its_editor(qtbot: QtBot) -> None:
    view = EditableTableMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    # active, for the editor to take the focus, and lose it once closed
    with qtbot.waitActive(window):
        window.activateWindow()
    table = _table(view.places)
    model = table.model()

    def answer(row: int, column: int, text: str) -> None:
        view.places.rows = replace_cell(view.places.rows, row, column, text)

    view.places.cell_edited.connect(answer)
    center = table.visualRect(model.index(0, 1)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    editor = QApplication.focusWidget()
    assert isinstance(editor, QLineEdit)
    editor.selectAll()
    qtbot.keyClicks(editor, "Windy")
    # Tab commits, then would edit the next cell: the new rows reset the table first
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert table.state() is not QAbstractItemView.State.EditingState
    assert view.places.rows[0] == ["Lake", "Windy"]
    assert model.index(0, 1).data() == "Windy"
    assert QApplication.focusWidget() is table


def test_a_language_set_once_rendered_relabels_the_widgets(qtbot: QtBot) -> None:
    view = TranslatedMainView()
    view.render(RendererType.QT)
    size = view.shape.size
    seen: list[object] = []
    size.value_changed.connect(seen.append)

    view.set_language("fr")

    group = view.shape.renderer
    assert isinstance(group, QtWidgetRenderer)
    assert isinstance(group.qt_object, QGroupBox)
    assert group.qt_object.title() == "Forme"
    combobox = _field_widget(size)
    assert isinstance(combobox, QComboBox)
    assert [combobox.itemText(i) for i in range(combobox.count())] == ["Petite", "Grande"]
    assert combobox.currentText() == "Grande"
    assert size.value is Size.LARGE
    assert seen == []
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    assert [action.text() for action in window.menuBar().actions()] == ["Fichier"]


def test_an_action_without_a_qaction_ignores_changes_until_rendered(qtbot: QtBot) -> None:
    # a page outside a router: its entry, showing its title, has no toolbar to be in
    page = InputsPage()
    page.render(RendererType.QT)
    assert isinstance(page.action.renderer, QtActionRenderer)
    assert page.action.renderer.qt_object is None

    page.title = "Entrées"

    window = QMainWindow()
    qtbot.addWidget(window)
    page.action.renderer.set_parent_rendered_object(window)
    page.action.renderer.render()
    qaction = page.action.renderer.qt_object
    assert isinstance(qaction, QAction)
    assert qaction.text() == "Entrées"


def test_the_language_menu_relabels_the_window(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    language_menu = window.menuBar().actions()[2].menu()
    assert isinstance(language_menu, QMenu)
    english, french = language_menu.actions()
    assert (english.isChecked(), french.isChecked()) == (True, False)

    french.trigger()

    assert window.windowTitle() == "Formulaire de conduite"
    assert [action.text() for action in window.menuBar().actions()] == [
        "Fichier",
        "Conduite",
        "Langue",
    ]
    assert (english.isChecked(), french.isChecked()) == (False, True)
    main_pipe = view.pages.inputs.pipe_form.main_pipe.renderer
    assert isinstance(main_pipe, QtWidgetRenderer)
    assert isinstance(main_pipe.qt_object, QGroupBox)
    assert main_pipe.qt_object.title() == "Conduite principale"


def _rendered_chart(qtbot: QtBot) -> tuple[PipeChartMainView, QChart]:
    view = PipeChartMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.resize(900, 700)
    window.show()
    assert isinstance(view.chart.renderer, QtWidgetRenderer)
    chart = view.chart.renderer.qt_object
    assert isinstance(chart, QChart)
    return view, chart


def _plot_item(chart: QChart) -> pg.PlotItem:
    plot = chart.getPlotItem()
    assert isinstance(plot, pg.PlotItem)
    return plot


def _chart_scene(chart: QChart) -> pg.GraphicsScene:
    scene = chart.scene()
    assert isinstance(scene, pg.GraphicsScene)
    return scene


def _view_box(chart: QChart) -> pg.ViewBox:
    view_box = _plot_item(chart).getViewBox()
    assert isinstance(view_box, pg.ViewBox)
    return view_box


def test_the_chart_shows_its_titles_units_and_series(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    plot = _plot_item(chart)
    assert plot.titleLabel.text == "Pressure Drop"
    assert plot.getAxis("bottom").labelText == "Flow Rate"
    assert plot.getAxis("bottom").labelUnits == "L/s"
    assert plot.getAxis("left").labelUnits == "kPa"
    view.chart.x_unit = "m3/h"
    view.chart.y_title = "Drop"
    assert plot.getAxis("bottom").labelUnits == "m3/h"
    assert plot.getAxis("bottom").labelText == "Flow Rate"
    assert plot.getAxis("left").labelText == "Drop"

    view.chart.series = [
        Series(name="Pressure", x=[0, 1, 2, 3], y=[1, math.nan, 3, 4]),
        Series(name="Temperature", x=[0, 0.5], y=[2, 2]),  # an x of its own
    ]

    assert chart.legend_names() == ["Pressure", "Temperature"]
    pressure, temperature = plot.listDataItems()
    x, y = pressure.getData()
    assert list(x) == [0, 1, 2, 3]
    assert math.isnan(y[1])  # a gap: drawn with `connect="finite"`
    assert pressure.opts["connect"] == "finite"
    assert len(temperature.getData()[0]) == 2
    view.chart.series = view.chart.series[1:]
    assert chart.legend_names() == ["Temperature"]
    assert len(plot.listDataItems()) == 1


def test_new_series_keep_the_user_s_zoom(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.add_curve()
    view_box = _view_box(chart)
    view_box.setXRange(0.5, 1.0, padding=0)  # as the mouse wheel would

    view.pipe.diameter.value = 80
    view.add_curve()

    assert len(view.chart.series) == 2
    assert view_box.viewRange()[0] == [0.5, 1.0]


def test_hovering_the_chart_shows_the_values_at_the_cursor(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series(name="Pressure", x=[0, 1, 2], y=[10, 20, 30.5])]
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 2)
    assert chart.hover_text() == ""

    _chart_scene(chart).sigMouseMoved.emit(view_box.mapViewToScene(QPointF(1.05, 15)))

    qtbot.waitUntil(lambda: chart.hover_text() != "")
    lines = chart.hover_text().splitlines()
    assert lines[0].endswith(" L/s")
    assert lines[1] == "Pressure: 20.00 kPa"  # its trailing zeros kept, as on the web
    if hasattr(QFont, "Tag"):  # digits of one width, from Qt 6.7
        assert QFont.Tag("tnum") in chart._hover.textItem.font().featureTags()  # noqa: SLF001
    _chart_scene(chart).sigMouseMoved.emit(QPointF(-10, -10))  # off the plot
    qtbot.waitUntil(lambda: chart.hover_text() == "")


def test_a_step_series_holds_each_value_until_the_next_point(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series(name="Running", x=[0, 2, 5], y=[1, 3, 2], step=True)]
    (running,) = _plot_item(chart).listDataItems()

    x, y = running.getData()
    assert (list(x), list(y)) == ([0, 2, 2, 5, 5], [1, 1, 3, 3, 2])
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 5)
    # nearer 5 than 2, but still holding 2's value
    _chart_scene(chart).sigMouseMoved.emit(view_box.mapViewToScene(QPointF(4, 2)))
    qtbot.waitUntil(lambda: chart.hover_text() != "")
    assert chart.hover_text().splitlines()[1] == "Running: 3 kPa"  # a count, as it is

    view.chart.kind = ChartKind.SCATTER  # dots: as they are
    assert len(running.getData()[0]) == 3


def test_the_chart_follows_the_palette(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series(name="Pressure", x=[0, 1], y=[0, 1])]
    (curve,) = _plot_item(chart).listDataItems()
    assert curve.opts["pen"].color().name() == SERIES_COLORS[False][0]
    palette = chart.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))

    chart.setPalette(palette)

    assert curve.opts["pen"].color().name() == SERIES_COLORS[True][0]
    assert chart.backgroundBrush().color().name() == "#202020"
    assert _plot_item(chart).getAxis("left").textPen().color().name() == "#f0f0f0"


def test_a_scatter_series_is_drawn_as_dots_over_the_lines(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.add_curve()
    view.add_measurements()
    model, measured = _plot_item(chart).listDataItems()

    assert model.opts["symbol"] is None
    assert model.opts["pen"].color().name() == SERIES_COLORS[False][0]
    assert measured.opts["pen"].style() == Qt.PenStyle.NoPen
    assert measured.opts["symbol"] == "o"
    assert measured.opts["symbolBrush"].color().name() == SERIES_COLORS[False][1]
    assert chart.legend_names() == ["D = 50 mm", "Measured, D = 50 mm"]

    view.chart.kind = ChartKind.SCATTER  # the series without a kind of their own follow
    assert model.opts["symbol"] == "o"
    assert model.opts["pen"].style() == Qt.PenStyle.NoPen


def _chart_page_chart(qtbot: QtBot) -> tuple[ChartPagesMainView, QChart]:
    view = ChartPagesMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.resize(900, 900)
    window.show()
    view.router.current_route = "chart"
    energy = view.router.chart.energy
    assert isinstance(energy.renderer, QtWidgetRenderer)
    chart = energy.renderer.qt_object
    assert isinstance(chart, QChart)
    return view, chart


def test_a_bar_chart_groups_a_bar_per_series_in_each_category(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot)
    plot = _plot_item(chart)
    assert not any(isinstance(item, pg.PlotDataItem) for item in plot.items)
    heating, cooling = (item for item in plot.items if isinstance(item, pg.BarGraphItem))

    assert list(np.asarray(heating.opts["height"])) == [120, 80, 95]
    assert list(np.asarray(cooling.opts["height"])) == [30, 45]  # none in the bedroom
    # side by side in each category's group, centered on its index
    assert heating.opts["width"] == cooling.opts["width"] == pytest.approx(0.4)
    assert list(np.asarray(heating.opts["x0"])) == pytest.approx([-0.4, 0.6, 1.6])
    assert list(np.asarray(cooling.opts["x0"])) == pytest.approx([0.0, 2.0])
    assert pg.mkBrush(heating.opts["brush"]).color().name() == SERIES_COLORS[False][0]
    assert chart.legend_names() == ["Heating", "Cooling"]
    ticks = plot.getAxis("bottom")._tickLevels  # noqa: SLF001
    assert ticks == [[(0, "Kitchen"), (1, "Bedroom"), (2, "Office")]]

    view.router.chart.energy.kind = ChartKind.LINE  # its series as curves again
    assert sum(isinstance(item, pg.PlotDataItem) for item in plot.items) == 2
    assert not any(isinstance(item, pg.BarGraphItem) for item in plot.items)
    assert plot.getAxis("bottom")._tickLevels is None  # noqa: SLF001


def test_hovering_a_bar_chart_shows_its_category_s_values(qtbot: QtBot) -> None:
    _view, chart = _chart_page_chart(qtbot)
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] > 2)

    _chart_scene(chart).sigMouseMoved.emit(view_box.mapViewToScene(QPointF(1.1, 50)))

    qtbot.waitUntil(lambda: chart.hover_text() != "")
    # whole numbers, as they are: not 80.00, nor 4.528e+04 for a count of 45280
    assert chart.hover_text().splitlines() == ["Bedroom", "Heating: 80 kWh"]


def test_a_log_axis_leaves_out_what_it_cannot_show(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    plot = _plot_item(chart)
    view.chart.series = [Series(name="Decay", x=[0, 1, 10, 100], y=[5, -1, 10, 100])]

    view.chart.x_log = True
    view.chart.y_log = True

    assert plot.getAxis("bottom").logMode
    assert plot.getAxis("left").logMode
    (curve,) = (item for item in plot.items if isinstance(item, pg.PlotDataItem))
    # no x of 0 on a log axis: left out; a y of -1: a gap
    assert curve.xData is not None
    assert curve.yData is not None
    assert list(curve.xData) == [1, 10, 100]
    assert math.isnan(curve.yData[0])
    assert list(curve.yData[1:]) == [10, 100]
    view.chart.x_log = False
    assert not plot.getAxis("bottom").logMode
    assert list(curve.xData) == [0, 1, 10, 100]


def test_a_log_axis_shows_the_hovered_value_not_its_log(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series(name="Decay", x=[1, 10, 100], y=[3, 2, 1])]
    view.chart.x_log = True
    view_box = _view_box(chart)
    # the log range, 0 to 2: the linear one, 1 to 100, reaches 2 too
    qtbot.waitUntil(lambda: 2 <= view_box.viewRange()[0][1] < 3)

    # straight to the hover, not through the mouse's rate-limited proxy: its delay leaves
    # the range, still settling on the log axis, time to move under the cursor
    chart.show_hover(view_box.mapViewToScene(QPointF(1.02, 2)))  # x = 10^1.02

    assert chart.hover_text().splitlines() == ["10.47 L/s", "Decay: 2 kPa"]


def test_log_bars_rise_from_the_power_of_10_under_the_lowest(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot)
    energy = view.router.chart.energy
    energy.series = [Series(name="Heating", x=[0, 1, 2], y=[1000, 0, 50])]

    energy.y_log = True

    (bars,) = (item for item in _plot_item(chart).items if isinstance(item, pg.BarGraphItem))
    # none of 0 in the bedroom
    assert list(np.asarray(bars.opts["x0"])) == pytest.approx([-0.4, 1.6])
    assert bars.opts["y0"] == 1  # 10 kWh, under 50
    assert list(np.asarray(bars.opts["height"])) == pytest.approx([2, math.log10(50) - 1])
    assert _plot_item(chart).getAxis("left").logMode


@pytest.mark.parametrize(
    ("picked", "saved_as"),
    [
        ("drop", ["drop.svg"]),  # by the filter chosen
        ("drop.png", ["drop.png"]),  # by the name's own extension
        ("", []),  # cancelled
    ],
)
def test_save_image_saves_the_chart_as_it_shows(
    picked: str,
    saved_as: list[str],
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("matplotlib")
    view, chart = _rendered_chart(qtbot)
    view.add_curve()
    _view_box(chart).setRange(xRange=(0.5, 1.5), yRange=(0, 10), padding=0)
    asked: list[tuple[str, str]] = []

    def get_save_file_name(_parent: QWidget, caption: str, name: str, filters: str) -> tuple:
        asked.append((caption, name))
        assert filters.startswith("PDF (*.pdf)")  # vector first
        return (str(tmp_path / picked) if picked else ""), "SVG (*.svg)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", get_save_file_name)
    saved: list[ImageOptions] = []
    save = chartimage.save_chart_image

    def save_chart_image(chart_view: ChartView, path: Path, options: ImageOptions) -> None:
        saved.append(options)
        save(chart_view, path, options)

    monkeypatch.setattr(chartimage, "save_chart_image", save_chart_image)
    menu = _view_box(chart).menu
    assert isinstance(menu, QMenu)
    (action,) = (action for action in menu.actions() if action.text() == "Save Image…")

    action.trigger()

    assert asked == [("Save Image", "Pressure Drop.pdf")]
    assert [path.name for path in tmp_path.iterdir()] == saved_as
    # the zoom the user looks at
    assert [(options.x_range, options.y_range) for options in saved] == [
        (pytest.approx((0.5, 1.5)), pytest.approx((0, 10)))
    ] * len(saved_as)


def test_without_matplotlib_the_chart_offers_only_its_own_export(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chartimage, "is_available", lambda: False)

    _view, chart = _rendered_chart(qtbot)

    menu = _view_box(chart).menu
    assert isinstance(menu, QMenu)
    texts = [action.text() for action in menu.actions()]
    assert "Save Image…" not in texts
    # pyqtgraph's own, saving an image of the screen's chart
    assert [action.text() for action in _chart_scene(chart).contextMenu] == ["Export..."]


def test_a_click_on_the_plot_emits_its_point(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series(name="Decay", x=[1, 10, 100], y=[3, 2, 1])]
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 100)
    clicks: list[tuple[float, float]] = []
    view.chart.clicked.connect(lambda x, y: clicks.append((x, y)))

    chart.click(view_box.mapViewToScene(QPointF(10, 2)))
    view.chart.x_log = True
    chart.click(view_box.mapViewToScene(QPointF(1, 2)))  # the log of 10
    chart.click(QPointF(-10, -10))  # off the plot

    assert clicks == [pytest.approx((10, 2)), pytest.approx((10, 2))]


def test_a_series_of_its_own_color_is_drawn_so_filled_down_to_0(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [
        Series(name="Oval", x=[0, 1], y=[1, 1], color="#ffd700", fill=True),
        Series(name="Theme", x=[0, 1], y=[2, 2]),
    ]
    oval, theme = (item for item in _plot_item(chart).items if isinstance(item, pg.PlotDataItem))

    assert pg.mkPen(oval.opts["pen"]).color().name() == "#ffd700"
    assert (oval.opts["fillLevel"], pg.mkBrush(oval.opts["fillBrush"]).color().name()) == (
        0,
        "#ffd700",
    )
    assert pg.mkPen(theme.opts["pen"]).color().name() == SERIES_COLORS[False][1]
    assert theme.opts["fillLevel"] is None
    palette = chart.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    chart.setPalette(palette)
    assert pg.mkPen(oval.opts["pen"]).color().name() == "#ffd700"  # the same in a dark theme


def test_reference_lines_are_styled_labeled_and_in_range(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    plot = _plot_item(chart)
    view.chart.series = [Series(name="Decay", x=[1, 10], y=[3, 2])]

    view.chart.reference_lines = [
        ReferenceLine(40, "Max: {40}", color="#d03030", style=LineStyle.DOTTED),  # braces are text
        ReferenceLine(100, "Now", vertical=True),
    ]

    # labeled lines, unlike the hover's crosshair
    maximum, now = (item for item in plot.items if hasattr(item, "label"))
    assert (maximum.angle, maximum.value(), now.angle, now.value()) == (0, 40, 90, 100)
    assert maximum.label.toPlainText() == "Max: {40}"
    assert maximum.pen.color().name() == "#d03030"
    assert maximum.pen.style() == Qt.PenStyle.DotLine
    assert now.pen.style() == Qt.PenStyle.DashLine  # by default
    assert now.pen.color() == chart.palette().color(QPalette.ColorRole.WindowText)
    # each shows, though past the data
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 100 and view_box.viewRange()[1][1] >= 40)
    palette = chart.palette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))
    chart.setPalette(palette)
    assert now.pen.color().name() == "#f0f0f0"
    assert now.label.color.name() == "#f0f0f0"

    view.chart.x_log = True  # at its log, as pyqtgraph draws the series
    view.chart.reference_lines = [
        *view.chart.reference_lines,
        ReferenceLine(0, "Start", vertical=True),
    ]

    lines = [item for item in plot.items if hasattr(item, "label")]
    assert [line.value() for line in lines] == [40, 2]  # no x of 0 on a log axis


def test_the_chart_is_as_tall_as_its_view_says(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    assert chart.height() > 250  # its share of the window's 700 pixels

    view.chart.height = 250
    qtbot.waitUntil(lambda: chart.height() == 250)
    assert (chart.minimumHeight(), chart.maximumHeight()) == (250, 250)

    view.chart.height = None  # as tall as the layout makes it again
    assert (chart.minimumHeight(), chart.maximumHeight()) == (0, 16777215)
    qtbot.waitUntil(lambda: chart.height() > 250)


def _sorted_rooms(qtbot: QtBot, *, wide: bool = False) -> tuple[SortedRoomsMainView, QFilterTable]:
    view = SortedRoomsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    if wide:  # the filter bar on one row whatever the system's fonts: Windows' are wider
        window.resize(1600, window.height())
    window.show()
    qtbot.waitExposed(window)
    box = _widget(view.rooms)
    assert isinstance(box, QFilterTable)
    return view, box


def _shown_column(table: QTextTableView, column: int) -> list[str]:
    model = table.model()
    return [model.index(row, column).data() or "" for row in range(model.rowCount())]


def test_clicking_a_sortable_header_sorts_by_it_then_back_and_shows_the_order(
    qtbot: QtBot,
) -> None:
    view, box = _sorted_rooms(qtbot)
    table, header = box.table, box.table.horizontalHeader()

    def click_header(column: int) -> None:
        position = QPoint(header.sectionViewportPosition(column) + 5, header.height() // 2)
        qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=position)

    click_header(2)  # the occupants
    assert _shown_column(table, 2) == ["2", "9", "10", ""]
    assert header.isSortIndicatorShown()
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (
        2,
        Qt.SortOrder.AscendingOrder,
    )
    click_header(2)
    assert _shown_column(table, 2) == ["10", "9", "2", ""]
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    click_header(2)
    assert view.rooms.sort_column is None
    assert _shown_column(table, 0) == ["Hall", "kitchen", "Attic", "Bedroom"]
    assert not header.isSortIndicatorShown()

    # a table sorting by no column: its headers sort nothing, and it has no filter bar
    notes = _widget(view.notes)
    assert isinstance(notes, QFilterTable)
    assert not notes.table.horizontalHeader().sectionsClickable()
    assert not notes.bar.isVisible()
    assert box.bar.isVisible()


def test_the_filter_bar_searches_and_adds_filters_shown_as_chips(qtbot: QtBot) -> None:
    view, box = _sorted_rooms(qtbot, wide=True)
    bar, table = box.bar, box.table

    qtbot.keyClicks(bar.search, "ROOM")
    qtbot.waitUntil(lambda: view.rooms.search == "ROOM", timeout=SEARCH_DELAY_MS * 5)
    assert _shown_column(table, 0) == ["Bedroom"]
    assert bar.count.text() == "1 of 4"
    bar.search.selectAll()
    qtbot.keyClick(bar.search, Qt.Key.Key_Backspace)
    assert _shown_column(table, 0) == ["Hall", "kitchen", "Attic", "Bedroom"]
    assert not bar.count.isVisible()

    def add(column: str, text: str) -> None:
        if not bar.is_editing():
            qtbot.mouseClick(bar.add_filter, Qt.MouseButton.LeftButton)
        bar.column.setCurrentIndex(bar.column.findText(column))
        bar.value.selectAll()
        qtbot.keyClicks(bar.value, text)
        qtbot.keyClick(bar.value, Qt.Key.Key_Return)

    # a value that doesn't parse isn't added: the field says why, the editor stays
    add("Temperature", "warm")
    assert bar.is_editing()
    assert (bar.value.property("invalid"), bar.value.toolTip()) == (
        True,
        '"warm" isn\'t a number',
    )
    assert view.rooms.filters == {}
    assert bar.value.placeholderText() == ">=20, 18..24"
    add("Temperature", ">=20")
    assert not bar.is_editing()
    assert _shown_column(table, 0) == ["kitchen", "Bedroom"]
    (chip,) = bar.chips
    # laid out in the bar after "+ Filter", the count apart at the bar's right end
    QApplication.processEvents()  # the layout's pass
    assert (parent := chip.parentWidget()) is not None
    assert parent.rect().contains(chip.geometry())
    assert bar.add_filter.geometry().right() < chip.x()
    assert bar.count.geometry().right() == bar.rect().right()
    assert chip.open_button.accessibleName() == "Temperature: >=20"
    assert chip.open_button.toolTip() == "Edit the filter on Temperature"
    # its chip has the focus: Enter opens it again, to replace the filter on its column;
    # another column's combines
    qtbot.waitUntil(chip.open_button.hasFocus)
    qtbot.keyClick(chip.open_button, Qt.Key.Key_Return)
    assert bar.value.text() == ">=20"
    add("Temperature", ">=21")
    add("Heated", "true")
    assert view.rooms.filters == {1: ">=21", 3: "true"}
    assert _shown_column(table, 0) == ["Bedroom"]
    assert bar.clear.isVisible()

    qtbot.mouseClick(bar.chips[0].remove_button, Qt.MouseButton.LeftButton)
    assert view.rooms.filters == {3: "true"}
    add("Occupants", ">100")
    assert table.model().rowCount() == 0
    assert box.empty.isVisible()
    assert box.empty.text() == "No rows match the filters"
    qtbot.mouseClick(bar.clear, Qt.MouseButton.LeftButton)
    assert table.model().rowCount() == 4
    assert bar.chips == []


def test_the_filter_editor_s_toggle_makes_the_value_a_regular_expression(qtbot: QtBot) -> None:
    view, box = _sorted_rooms(qtbot)
    bar = box.bar

    qtbot.mouseClick(bar.add_filter, Qt.MouseButton.LeftButton)
    # only for text: a number column takes comparisons
    bar.column.setCurrentIndex(bar.column.findText("Temperature"))
    assert not bar.pattern.isVisible()
    bar.column.setCurrentIndex(bar.column.findText("Room"))
    assert bar.pattern.isVisible()
    qtbot.mouseClick(bar.pattern, Qt.MouseButton.LeftButton)
    assert bar.value.placeholderText() == "a regular expression, as Room [1-3]"
    qtbot.keyClicks(bar.value, "^(hall|attic)$")
    qtbot.keyClick(bar.value, Qt.Key.Key_Return)
    assert _shown_column(box.table, 0) == ["Hall", "Attic"]
    (chip,) = bar.chips
    assert chip.open_button.accessibleName() == "Room matches ^(hall|attic)$"

    # reopened, the toggle is on and the value the pattern as typed
    qtbot.mouseClick(chip.open_button, Qt.MouseButton.LeftButton)
    assert bar.pattern.isChecked()
    assert bar.value.text() == "^(hall|attic)$"
    bar.value.selectAll()
    qtbot.keyClicks(bar.value, "(hall")
    qtbot.keyClick(bar.value, Qt.Key.Key_Return)
    assert bar.value.toolTip() == '"(hall" isn\'t a valid regular expression'
    assert view.rooms.filters == {0: "/^(hall|attic)$/"}


def test_a_click_and_an_edit_on_a_sorted_filtered_table_reach_their_rows(qtbot: QtBot) -> None:
    view, box = _sorted_rooms(qtbot)
    rooms, table = view.rooms, box.table
    rooms.filters = {3: "true"}
    rooms.sort_by(0)
    rooms.sort_by(0)  # descending: the kitchen, then the bedroom
    emitted: list[list[int]] = []
    rooms.selection_changed.connect(emitted.append)

    center = table.visualRect(table.model().index(1, 0)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert rooms.selected_records == [Room("Bedroom", 21, 9, is_heated=True)]
    assert emitted == [[3]]

    edited: list[tuple[Room, Room]] = []
    rooms.record_edited.connect(lambda old, new: edited.append((old, new)))
    # renamed, the bedroom sorts first and stays selected
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    editor = table.focusWidget()
    assert isinstance(editor, QLineEdit)
    editor.selectAll()
    qtbot.keyClicks(editor, "Study")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)
    assert edited == [
        (Room("Bedroom", 21, 9, is_heated=True), Room("Study", 21, 9, is_heated=True))
    ]
    assert _shown_column(table, 0) == ["Study", "kitchen"]
    assert rooms.selected_rows == [3]
    assert [index.row() for index in table.selectionModel().selectedRows()] == [0]


def test_a_large_table_draws_the_rows_on_screen_reading_only_their_windows(
    qtbot: QtBot,
) -> None:
    view = MillionRowsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)
    container = _widget(view.table)
    assert isinstance(container, QDataFilterTable)
    table = container.table
    model = table.model()
    source = view.table.source
    assert isinstance(source, MillionSource)

    assert model.rowCount() == 1_000_000
    assert [model.headerData(column, Qt.Orientation.Horizontal) for column in range(2)] == [
        "Value",
        "Half",
    ]
    assert (model.index(1, 0).data(), model.index(1, 1).data()) == ("2", "0.5")
    table.scrollTo(model.index(500_000, 0), QAbstractItemView.ScrollHint.PositionAtTop)
    qtbot.waitUntil(lambda: 500_000 in source.read)
    assert model.headerData(500_000, Qt.Orientation.Vertical) == "500,001"
    # the rows drawn, by windows: never the million
    assert len(source.read) < 10 * SOURCE_TABLE_WINDOW

    source.size = 3
    source.changed.emit()
    assert model.rowCount() == 3


def test_a_large_table_s_header_clicks_sort_by_its_column_showing_the_order(
    qtbot: QtBot,
) -> None:
    view = MillionRowsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    container = _widget(view.table)
    assert isinstance(container, QDataFilterTable)
    table = container.table
    header = table.horizontalHeader()

    def click(column: int) -> None:
        position = QPoint(header.sectionViewportPosition(column) + 5, header.height() // 2)
        qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=position)

    assert not header.isSortIndicatorShown()
    click(1)
    assert (view.table.sort_column, view.table.sort_descending) == ("half", False)
    assert header.isSortIndicatorShown()
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (
        1,
        Qt.SortOrder.AscendingOrder,
    )
    click(1)
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    click(1)
    assert view.table.sort_column is None
    assert not header.isSortIndicatorShown()


def test_a_large_table_s_clicks_select_its_rows_and_a_double_click_activates_one(
    qtbot: QtBot,
) -> None:
    view = MillionRowsMainView()
    view.table.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    container = _widget(view.table)
    assert isinstance(container, QDataFilterTable)
    table = container.table
    model = table.model()
    activated: list[Any] = []
    view.table.row_activated.connect(activated.append)

    def click(row: int, modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
        center = table.visualRect(model.index(row, 0)).center()
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, modifier, center)

    click(1)
    click(4, Qt.KeyboardModifier.ShiftModifier)
    assert view.table.selected_ids == [1, 2, 3, 4]
    assert model.index(2, 1).data(Qt.ItemDataRole.BackgroundRole) is not None
    assert model.index(5, 1).data(Qt.ItemDataRole.BackgroundRole) is None
    click(2)  # selected: unselected
    assert view.table.selected_ids == [1, 3, 4]

    table.setCurrentIndex(model.index(6, 0))
    qtbot.keyClick(table, Qt.Key.Key_Space)
    qtbot.keyClick(table, Qt.Key.Key_Return)
    # a double click: a click, which selects the row, then the double click
    click(0)
    center = table.visualRect(model.index(0, 0)).center()
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert view.table.selected_ids == [1, 3, 4, 6, 0]
    assert activated == [6, 0]


def test_a_large_table_s_bar_searches_and_filters_its_columns_by_name(qtbot: QtBot) -> None:
    view = RoomsDataMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    box = _widget(view.rooms)
    assert isinstance(box, QDataFilterTable)
    bar, model = box.bar, box.table.model()

    def names() -> list[str]:
        return [model.index(row, 0).data() for row in range(model.rowCount())]

    assert bar.isVisible()
    assert [bar.column.itemText(i) for i in range(bar.column.count())] == ["Room", "Temperature"]
    qtbot.keyClicks(bar.search, "room")
    assert view.rooms.search == ""  # once the user stops typing: one search, not four
    qtbot.keyClick(bar.search, Qt.Key.Key_Return)  # or at once
    assert (view.rooms.search, names(), bar.count.text()) == ("room", ["Bedroom"], "1 of 3")
    bar.search.selectAll()
    qtbot.keyClick(bar.search, Qt.Key.Key_Backspace)
    assert (view.rooms.search, len(names()), bar.count.isVisible()) == ("", 3, False)

    qtbot.mouseClick(bar.add_filter, Qt.MouseButton.LeftButton)
    bar.column.setCurrentIndex(bar.column.findText("Temperature"))
    qtbot.keyClicks(bar.value, "warm")
    qtbot.keyClick(bar.value, Qt.Key.Key_Return)
    assert bar.value.toolTip() == '"warm" isn\'t a number'  # by the column's name
    bar.value.selectAll()
    qtbot.keyClicks(bar.value, ">19")
    qtbot.keyClick(bar.value, Qt.Key.Key_Return)
    assert view.rooms.filters == {"temperature": ">19"}
    assert names() == ["Kitchen", "Bedroom"]
    assert [chip.open_button.accessibleName() for chip in bar.chips] == ["Temperature: >19"]

    view.rooms.filters = {"temperature": ">30"}
    assert box.empty.isVisible()
    redrawn: list[object] = []
    model.dataChanged.connect(lambda *_args: redrawn.append(None))
    view.rooms.selected_ids = [0]  # a row the filter hides: nothing to redraw
    assert redrawn == []
    qtbot.mouseClick(bar.chips[0].remove_button, Qt.MouseButton.LeftButton)
    assert (view.rooms.filters, names(), box.empty.isVisible()) == (
        {},
        ["Kitchen", "Hall", "Bedroom"],
        False,
    )


def test_ctrl_c_copies_a_large_table_s_selected_rows_to_the_clipboard(qtbot: QtBot) -> None:
    view = MillionRowsMainView()
    view.table.selection_mode = SelectionMode.MULTIPLE
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    container = _widget(view.table)
    assert isinstance(container, QDataFilterTable)
    table, model = container.table, container.table.model()
    for row in (3, 1):
        center = table.visualRect(model.index(row, 0)).center()
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)

    qtbot.keyClick(table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)

    # in the table's order: the value, then its half
    assert QApplication.clipboard().text() == "2\t0.5\n6\t1.5"


def test_a_large_source_s_rows_are_ordered_in_a_job_the_old_order_shown_meanwhile(
    qtbot: QtBot,
) -> None:
    view = GatedMainView()
    view.render(RendererType.QT)
    _add_reference_to_signals(view, None)  # as the app does: the table finds the jobs
    qtbot.addWidget(_widget(view))
    box = _widget(view.table)
    assert isinstance(box, QDataFilterTable)
    model, rows = box.table.model(), box.table.viewport()
    source = view.table.source
    assert isinstance(source, GatedSource)

    def first() -> str:
        return str(model.index(0, 0).data())

    source.gate.clear()
    view.table.sort_column = "value"
    view.table.sort_descending = True  # while the job orders: one more job, once over

    assert view.table.is_ordering
    assert first() == "0"  # the old order, the window responsive
    assert rows.cursor().shape() == Qt.CursorShape.BusyCursor
    source.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    assert first() == str(source.size - 1)
    assert [sort.descending for sort in source.orders if sort is not None] == [False, True]
    assert rows.cursor().shape() != Qt.CursorShape.BusyCursor

    # New or Open drops the jobs, the ordering's too: it orders again
    source.gate.clear()
    view.table.sort_descending = False
    view.jobs.drop()
    assert view.table.is_ordering
    source.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    assert first() == "0"

    # the source changes while a job orders: counted and ordered in the next job, the
    # running job's order dropped
    source.gate.clear()
    view.table.sort_descending = True
    source.size = SOURCE_TABLE_JOB_ROWS - 1
    source.counted_on_main.clear()
    source.changed.emit()
    assert view.table.row_count == SOURCE_TABLE_JOB_ROWS  # the old order meanwhile
    source.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    assert (model.rowCount(), view.table.total) == (source.size, source.size)
    assert source.counted_on_main == [False]

    # a new source: neither a count nor "no rows match" before its rows' first order
    other = GatedSource()
    other.gate.clear()
    view.table.source = other
    assert view.table.is_ordering
    assert (view.table.row_count, view.table.count_text) == (0, "")
    assert box.empty.isHidden()
    other.gate.set()
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    assert model.rowCount() == other.size


def test_a_large_table_s_new_source_shows_its_columns_in_the_bar(qtbot: QtBot) -> None:
    view = RoomsDataMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    box = _widget(view.rooms)
    assert isinstance(box, QDataFilterTable)
    view.rooms.filters = {"name": "Hall"}

    # as an app swapping its rows: the bar shows the new source's columns, filtering by name
    view.rooms.source = ListSource(Room, {"name": T("Room")}, [Room("Hall", 18.0)])

    columns = [box.bar.column.itemText(index) for index in range(box.bar.column.count())]
    assert columns == ["Room"]
    assert [chip.open_button.text() for chip in box.bar.chips] == ["Room: Hall ✎"]


def test_a_large_table_draws_each_row_with_one_read_of_its_cells(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    read: list[int] = []
    rows = SourceTableView.rows

    def counted(table: SourceTableView, start: int, stop: int) -> list[tuple[Any, list[str]]]:
        read.append(start)
        return rows(table, start, stop)

    monkeypatch.setattr(SourceTableView, "rows", counted)
    view = MillionRowsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    box = _widget(view.table)
    assert isinstance(box, QDataFilterTable)
    read.clear()

    box.table.viewport().grab()

    # Qt asks each cell's text and colors apart: the row's cells are formatted once
    assert 0 < len(read) == len(set(read))
    last = read[-1]  # the row the model keeps
    view.table.column_formats = {"half": ".3f"}  # the same rows, formatted again
    assert box.table.model().index(last, 1).data() == f"{last / 2:.3f}"


@pytest.mark.parametrize(
    ("picked", "written"),
    [("rooms", ["rooms.csv"]), ("rooms.CSV", ["rooms.CSV"]), ("", [])],
    ids=["named", "with-extension", "cancelled"],
)
def test_a_large_table_s_button_exports_its_rows_as_csv(
    picked: str,
    written: list[str],
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = RoomsDataMainView()
    view.render(RendererType.QT)
    box = _widget(view.rooms)
    assert isinstance(box, QDataFilterTable)
    qtbot.addWidget(_widget(view))
    view.rooms.filters = {"temperature": ">19"}
    asked: list[tuple[str, str, str]] = []

    def get_save_file_name(_parent: QWidget, caption: str, name: str, filters: str) -> tuple:
        asked.append((caption, name, filters))
        return (str(tmp_path / picked) if picked else ""), filters

    monkeypatch.setattr(QFileDialog, "getSaveFileName", get_save_file_name)
    # a button above the rows, and the table's context menu, share the action
    (action,) = (action for action in box.table.actions() if action.text() == "Export CSV…")
    assert box.export.defaultAction() is action
    window = _widget(view)
    window.show()
    qtbot.waitExposed(window)
    assert box.export.isVisible()

    qtbot.mouseClick(box.export, Qt.MouseButton.LeftButton)

    assert asked == [("Export CSV", "table.csv", "CSV (*.csv)")]
    assert [path.name for path in tmp_path.iterdir()] == written
    for name in written:
        assert (tmp_path / name).read_text(encoding="utf-8").splitlines() == [
            "Room,Temperature,Occupants",
            "Kitchen,21.5,2",
            "Bedroom,19.5,1",
        ]


def _qt_widget(view: View) -> QWidget:
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QWidget)
    return widget


def _shown_tool_tip(widget: QWidget) -> str:
    """Get the text a tooltip shows: Qt reads one with a tag as HTML."""
    document = QTextDocument()
    document.setHtml(widget.toolTip())
    return document.toPlainText()


def test_a_text_like_html_shows_as_it_is(qtbot: QtBot) -> None:
    """A label or a tooltip reads a text with a tag as HTML; a `<none>` there shows nothing."""
    view = MarkupMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_qt_widget(view))

    note = _qt_widget(view.note)
    assert isinstance(note, QLabel)
    assert note.textFormat() == Qt.TextFormat.PlainText
    assert isinstance(view.form.name.renderer, RendererContainer)
    label_renderer = view.form.name.renderer.get_renderer("label")
    assert isinstance(label_renderer, QtWidgetRenderer)
    label = label_renderer.qt_object
    assert isinstance(label, QFormLabel)
    assert label.text_label.textFormat() == Qt.TextFormat.PlainText
    assert _shown_tool_tip(label.help_button) == MARKUP
    assert view.form.name.help == MARKUP  # read back as set, not escaped
    help_browser = _qt_widget(view.help)
    assert isinstance(help_browser, QTextBrowser)
    assert help_browser.toPlainText().strip() == MARKUP  # raw HTML is text, as on the web
    box = _qt_widget(view.notes)
    assert isinstance(box, QFilterTable)
    (chip,) = box.bar.chips
    assert _shown_tool_tip(chip.open_button) == f"Edit the filter on {MARKUP}"

    view.warning.open()
    dialog = _qt_widget(view.warning)
    assert isinstance(dialog, QMessageBox)
    assert dialog.textFormat() == Qt.TextFormat.PlainText
    view.warning.reject()


def _widgets_of(view: View) -> list[object]:
    """Get the widgets of `view` and of its children, depth first."""
    renderer = view.renderer
    if isinstance(renderer, RendererContainer):
        widgets: list[object] = []
        for part in renderer.renderers:
            assert isinstance(part, QtWidgetRenderer)
            widgets.append(part.qt_object)
    else:
        widgets = [getattr(renderer, "qt_object", None)]
    for child_view in view.children_views:
        widgets.extend(_widgets_of(child_view))
    return widgets


@pytest.mark.parametrize(
    "main_view_type",
    [
        PipeMainView,
        PipeCatalogueMainView,
        ChartPagesMainView,
        DialogsMainView,
        GridMainView,
        PipesMainView,
        RecordMainView,
        SidebarMainView,
        SplitterMainView,
        TabsMainView,
        ToolBarMainView,
        CellWidgetsMainView,
        RoomsDataMainView,
        HelpMainView,
        JobsMainView,
        BookingMainView,
        DataFileMainView,
        EditedPipeMainView,
        HoursMainView,
        WorkersMainView,
    ],
)
def test_a_main_view_rendered_again_keeps_every_widget(
    qtbot: QtBot, main_view_type: type[MainView]
) -> None:
    view = main_view_type()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    before = _widgets_of(view)

    view.render(RendererType.QT)

    after = _widgets_of(view)
    assert [id(widget) for widget in after] == [id(widget) for widget in before]


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


def test_a_view_shown_before_its_widget_is_built_raises(qtbot: QtBot) -> None:
    view = LabelView()
    renderer = create_renderer(RendererType.QT, "label", view)
    assert renderer is not None
    view.renderer = renderer

    with pytest.raises(NoRenderedObjectError):
        view.text = "Too early"
    with pytest.raises(NoRenderedObjectError):
        renderer.refresh()


def test_a_combobox_picked_gives_the_view_its_value(qtbot: QtBot) -> None:
    view = TranslatedMainView()
    view.render(RendererType.QT)
    size = view.shape.size
    combobox = _field_widget(size)
    assert isinstance(combobox, QComboBox)
    qtbot.addWidget(combobox)
    seen: list[object] = []
    size.value_changed.connect(seen.append)
    combobox.show()
    combobox.setFocus()

    qtbot.keyClick(combobox, Qt.Key.Key_Up)
    size.value = None  # set in code: no item, and not reported

    assert (seen, combobox.currentIndex()) == ([Size.SMALL], -1)


@pytest.mark.parametrize(
    ("log_type", "style"),
    [
        (LogType.ERROR, "QLabel { color : red; }"),
        (LogType.WARNING, "QLabel { color : orange; }"),
        (LogType.INFO, ""),
    ],
)
def test_a_row_s_message_is_coloured_by_its_type(
    qtbot: QtBot, log_type: LogType, style: str
) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    name = view.pages.inputs.pipe_form.name
    assert isinstance(name.renderer, RendererContainer)
    log = name.renderer.get_renderer("log")
    assert isinstance(log, QtWidgetRenderer)
    assert isinstance(log.qt_object, QLabel)
    qtbot.addWidget(_widget(view))

    name.log_message = "Check the name"
    name.log_type = log_type

    assert (log.qt_object.text(), log.qt_object.styleSheet()) == ("Check the name", style)


def test_a_row_without_a_label_spans_its_form(qtbot: QtBot) -> None:
    view = NoteMainView()
    view.render(RendererType.QT)
    form = _widget(view.form)
    qtbot.addWidget(_widget(view))
    layout = form.layout()
    assert isinstance(layout, QFormLayout)

    row = layout.itemAt(0, QFormLayout.ItemRole.SpanningRole)

    assert layout.itemAt(0, QFormLayout.ItemRole.LabelRole) is None
    assert row is not None
    row_widget = row.widget()
    assert row_widget is not None
    assert row_widget.isAncestorOf(_field_widget(view.form.note))


def test_a_tree_keeps_its_node_selected_when_the_user_deselects_it(qtbot: QtBot) -> None:
    view = SiteMainView()
    view.render(RendererType.QT)
    site = view.site
    tree = _widget(site)
    assert isinstance(tree, QTreeWidget)
    qtbot.addWidget(tree)
    tree.show()
    site.selected = ("Building A", "Floor 1")
    selections: list[tuple[str, ...]] = []
    site.selection_changed.connect(selections.append)
    item = _tree_item(tree, "Building A", "Floor 1")

    qtbot.mouseClick(
        tree.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        tree.visualItemRect(item).center(),
    )

    assert tree.selectedItems() == [item]
    assert (site.selected, selections) == (("Building A", "Floor 1"), [])


def test_an_action_shows_its_icon_until_it_has_none(qtbot: QtBot, tmp_path: Path) -> None:
    icon = tmp_path / "run.png"
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("#2563eb"))
    assert pixmap.save(str(icon))
    view = ToolBarMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    run = view.toolbar.run
    assert isinstance(run.renderer, QtActionRenderer)
    action = run.renderer.qt_object
    assert isinstance(action, QAction)

    run.icon = str(icon)
    shown = not action.icon().isNull()
    run.icon = None

    assert (shown, action.icon().isNull()) == (True, True)


def test_exit_closes_the_window(qtbot: QtBot) -> None:
    view = HelpMainView()
    _add_reference_to_signals(view, None)  # `main_view` for the action, as an app does
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    view.file_menu.exit_app.triggered.emit()

    assert not window.isVisible()


def test_a_router_without_pages_shows_none(qtbot: QtBot) -> None:
    router = Router()
    router.render(RendererType.QT)
    stack = _widget(router)
    qtbot.addWidget(stack)

    assert isinstance(stack, QStackedWidget)
    assert stack.count() == 0


def test_a_window_shown_another_main_view_trades_its_toolbars_and_sidebar(
    qtbot: QtBot,
) -> None:
    first = ToolBarMainView()
    first.render(RendererType.QT)
    window = _widget(first)
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)

    def parts() -> tuple[int, int]:
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        direct = Qt.FindChildOption.FindDirectChildrenOnly
        return len(window.findChildren(QToolBar, "", direct)), len(
            window.findChildren(QDockWidget, "", direct)
        )

    shown = [parts()]
    for view in (SidebarMainView(), ToolBarMainView()):  # e.g. the changed code on a reload
        view.renderer = QtMainRenderer(view, window)
        view.render(RendererType.QT)
        shown.append(parts())

    # the edit toolbar and the pages' one; the pages' one and the sidebar; back again
    assert shown == [(2, 0), (1, 1), (2, 0)]


def test_a_file_saved_under_any_extension_keeps_the_name_typed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = HelpMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    typed = tmp_path / "notes"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_args: (str(typed), "All files (*)")),
    )

    assert view.ask_save_filepath({"All files": ("",)}) == typed


def test_a_check_all_box_follows_its_column_turning_read_only_or_plain(qtbot: QtBot) -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    model = _table(view.variables).model()

    def box() -> QImage | None:
        icon = model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DecorationRole)
        return None if icon is None else icon.pixmap(16, 16).toImage()

    enabled = box()
    view.variables.editable_columns = [2]
    disabled = box()
    view.variables.cell_widgets = {2: CellWidget.combobox(["Input", "Output"])}

    assert enabled is not None
    assert disabled is not None
    assert disabled != enabled  # drawn disabled
    assert box() is None  # a plain column again


def test_a_click_with_the_left_button_alone_emits_its_point(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    qtbot.waitExposed(chart.window())
    view.chart.series = [Series(name="Decay", x=[1, 10, 100], y=[1, 10, 100])]
    view_box = _view_box(chart)
    view.chart.y_log = True
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 100 and view_box.viewRange()[1][1] < 3)
    clicks: list[tuple[float, float]] = []
    view.chart.clicked.connect(lambda x, y: clicks.append((x, y)))
    point = chart.mapFromScene(view_box.mapViewToScene(QPointF(10, 1)))  # the log of 10

    # first: pyqtgraph takes a click soon after another for a double one
    qtbot.mouseClick(chart.viewport(), Qt.MouseButton.LeftButton, pos=point)
    qtbot.mouseClick(chart.viewport(), Qt.MouseButton.MiddleButton, pos=point)
    qtbot.mouseDClick(chart.viewport(), Qt.MouseButton.LeftButton, pos=point)

    (click,) = clicks
    assert click == pytest.approx((10, 10), rel=0.05)  # within the pixel the mouse hit


def test_a_log_chart_s_shown_range_is_its_values_not_their_logs(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series(name="Decay", x=[1, 10, 100], y=[1, 10, 100])]
    view.chart.x_log = True
    view.chart.y_log = True

    _view_box(chart).setRange(xRange=(0, 2), yRange=(1, 3), padding=0)

    assert chart.shown_range() == (pytest.approx((1, 100)), pytest.approx((10, 1000)))


def test_the_hover_leaves_out_what_isn_t_drawn_there(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot)
    energy = view.router.chart.energy
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] > 2)

    view_box.setRange(xRange=(-3, 5), padding=0)  # zoomed out, past the categories
    chart.show_hover(view_box.mapViewToScene(QPointF(4, 50)))
    past = chart.hover_text()
    energy.kind = ChartKind.LINE
    energy.series = [
        Series(name="Heating", x=[0, 1, 2], y=[10, 20, 30]),
        Series(name="Unknown", x=[0, 1, 2], y=[math.nan] * 3),  # no point drawn
    ]
    chart.show_hover(view_box.mapViewToScene(QPointF(1, 20)))

    assert past == ""
    assert chart.hover_text().splitlines()[1:] == ["Heating: 20 kWh"]


def test_a_table_s_keys_and_edits_report_only_what_changes(qtbot: QtBot) -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.variables)
    model, header = table.model(), table.horizontalHeader()
    assert isinstance(header, QCheckHeader)
    clicks: list[tuple[int, int]] = []
    edits: list[tuple[int, int, str]] = []
    view.variables.cell_clicked.connect(lambda row, column: clicks.append((row, column)))
    view.variables.cell_edited.connect(lambda row, column, text: edits.append((row, column, text)))

    # Space on a link's cell clicks it
    table.setFocus()
    table.setCurrentIndex(model.index(0, 4))
    qtbot.keyClick(table, Qt.Key.Key_Space)
    # a button's or a link's column has no editor, even editable
    view.variables.editable_columns = [0, 1, 2, 3, 4]
    link_flags = model.flags(model.index(0, 4))
    # Escape, or Enter on the text as it was, edits nothing
    cell = table.visualRect(model.index(0, 1)).center()
    for key in (Qt.Key.Key_Escape, Qt.Key.Key_Return):
        qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=cell)
        qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=cell)
        editor = table.focusWidget()
        assert isinstance(editor, QLineEdit)
        qtbot.keyClick(editor, key)
        qtbot.waitUntil(lambda: table.state() is not QAbstractItemView.State.EditingState)
    # the right button on the header's box checks nothing
    box = QPoint(header.sectionViewportPosition(0) + header.box_width() // 2, header.height() // 2)
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.RightButton, pos=box)

    assert clicks == [(0, 4)]
    assert not link_flags & Qt.ItemFlag.ItemIsEditable
    assert edits == []
    assert [row[0] for row in view.variables.rows] == ["True", "false"]
    # as a Qt model: nothing for no cell, and only an edit changes one
    assert model.data(QModelIndex()) is None
    assert model.setData(model.index(0, 1), "Width", Qt.ItemDataRole.DisplayRole) is False


def test_a_disabled_cell_is_drawn_disabled(qtbot: QtBot) -> None:
    view = CellWidgetsMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.resize(800, 400)
    window.show()
    qtbot.waitExposed(window)
    table = _table(view.variables)
    button = table.visualRect(table.model().index(0, 3))

    def drawn() -> QImage:
        QApplication.processEvents()
        return table.viewport().grab(button).toImage()

    enabled = drawn()
    view.variables.cell_styles = {(0, 3): CellStyle(is_enabled=False)}

    assert drawn() != enabled


def test_a_header_group_s_name_is_drawn_over_its_columns(qtbot: QtBot) -> None:
    view = StyledTablesMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    header = _table(view.points).horizontalHeader()

    def drawn() -> QImage:
        QApplication.processEvents()
        return header.grab().toImage()

    named = drawn()
    view.points.header_groups = [HeaderGroup("", 2, 2)]

    assert drawn() != named


def test_a_table_without_headers_has_no_columns(qtbot: QtBot) -> None:
    view = TableView()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))

    model = _table(view).model()

    assert (model.rowCount(), model.columnCount()) == (0, 0)


def test_a_dialog_shown_again_at_once_keeps_its_native_window(qtbot: QtBot) -> None:
    dialog = QMessageBox()
    qtbot.addWidget(dialog)
    release_when_hidden(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    dialog.hide()
    dialog.show()
    QApplication.processEvents()  # the release the hide queued

    assert dialog.testAttribute(Qt.WidgetAttribute.WA_WState_Created)


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


def test_a_filter_s_chip_opens_on_space_and_its_editor_closes_on_escape(qtbot: QtBot) -> None:
    view, box = _sorted_rooms(qtbot)
    bar = box.bar
    view.rooms.filters = {3: "true"}
    (chip,) = bar.chips

    qtbot.keyClick(chip.open_button, Qt.Key.Key_Space)
    opened = (bar.is_editing(), bar.value.text())
    qtbot.keyClick(bar.value, Qt.Key.Key_Escape)
    view.rooms.search = "kit"  # set in code: shown in the field

    assert opened == (True, "true")
    assert not bar.is_editing()
    assert view.rooms.filters == {3: "true"}
    assert bar.search.text() == "kit"


def test_a_signal_disconnected_hears_its_widget_no_more(qtbot: QtBot) -> None:
    view = InputView()
    view.render(RendererType.QT)
    field = _widget(view)
    qtbot.addWidget(field)
    edits: list[str] = []
    view.text_edited.connect(edits.append)
    field.show()
    field.setFocus()

    view.text_edited.disconnect()
    qtbot.keyClicks(field, "a")

    assert edits == []
    assert view.text == "a"  # the field still gives the view its text


class _FailingGatedSource(GatedSource):
    """A large source whose order, asked in a job, fails: e.g. its database gone."""

    def ordered_ids(self, sort: Sort | None, search: str, filters: Mapping[str, Filter]) -> range:
        if threading.current_thread() is not threading.main_thread():
            msg = "the database is gone"
            raise OSError(msg)
        return super().ordered_ids(sort, search, filters)


def test_a_large_table_keeps_its_order_when_a_job_fails_or_was_overtaken(
    qtbot: QtBot,
) -> None:
    view = GatedMainView()
    view.render(RendererType.QT)
    _add_reference_to_signals(view, None)  # as the app does: the table finds the jobs
    qtbot.addWidget(_widget(view))
    shown = view.table.row_count

    view.table.source = _FailingGatedSource()  # its first order fails, in its job
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    failed = view.table.row_count
    source = GatedSource()
    view.table.source = source
    qtbot.waitUntil(lambda: not view.table.is_ordering)
    source.gate.clear()
    view.table.sort_descending = True  # a job, then a small source answered at once
    view.table.source = ListSource(Room, {"name": T("Room")}, [Room("Hall", 18.0)])
    source.gate.set()
    qtbot.waitUntil(lambda: not view.jobs.is_running)  # the job's answer, come late

    assert shown > 0
    assert failed == 0  # no order to show yet, its failure logged
    assert view.table.row_count == 1  # the overtaken job's order dropped


def test_a_large_table_s_bar_clears_its_filters(qtbot: QtBot) -> None:
    view = RoomsDataMainView()
    view.rooms.filters = {"name": "Hall", "temperature": ">10"}  # two: the bar clears them
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    box = _widget(view.rooms)
    assert isinstance(box, QDataFilterTable)

    qtbot.mouseClick(box.bar.clear, Qt.MouseButton.LeftButton)

    assert view.rooms.filters == {}


def test_a_large_table_qt_doesn_t_render_still_orders_its_rows_in_a_job(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(QT_RENDERERS, "source_table")  # e.g. a backend lacking it
    view = GatedMainView()
    view.render(RendererType.QT)
    _add_reference_to_signals(view, None)  # as the app does: the table finds the jobs
    qtbot.addWidget(_widget(view))

    view.table.sort_descending = True
    ordering = view.table.is_ordering
    qtbot.waitUntil(lambda: not view.table.is_ordering)

    assert view.table.renderer is None
    assert ordering  # in a job, as in a table shown


def test_a_none_choice_is_shown_selected_and_picked_back(qtbot: QtBot) -> None:
    view = FiltersMainView()
    view.render(RendererType.QT)
    region, shown = view.form.region, view.form.shown
    combobox, radios = _field_widget(region), _field_widget(shown)
    assert isinstance(combobox, QComboBox)
    qtbot.addWidget(combobox)
    qtbot.addWidget(radios)
    picked: list[object] = []
    region.value_changed.connect(picked.append)

    assert combobox.currentText() == "All regions"
    assert [b.text() for b in radios.findChildren(QRadioButton) if b.isChecked()] == ["All regions"]
    region.value = "south"
    assert combobox.currentText() == "South"
    combobox.setCurrentIndex(0)  # what the user's pick does

    assert (region.value, picked) == (None, [None])
