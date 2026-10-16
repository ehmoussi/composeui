"""End-to-end coverage for the Qt backend (roadmap item 3).

Unlike `tests/test_pipeview.py`, which drives view/model logic by calling methods
and manually emitting signals, these tests actually render a widget tree with Qt,
assert on the real widget's state, and drive interactions through the widget layer
(typed keystrokes, a real radio-button click, a triggered `QAction`) to prove the
round trip back into the view - the same style `tests/test_textual_renderer.py`
already uses for the Textual backend.
"""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

import pytest
from qtpy.QtCore import QPoint, QPointF, Qt
from qtpy.QtGui import QAction, QColor, QPalette
from qtpy.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStatusBar,
    QTableView,
    QToolBar,
    QWidget,
)

from composeui.core.application import _add_reference_to_signals
from composeui.core.chartcolors import SERIES_COLORS
from composeui.core.renderer import MainRenderer, RendererContainer
from composeui.core.view import (
    ActionView,
    ButtonVariant,
    ChartKind,
    DialogKind,
    EditRefusedError,
    LabelView,
    RendererType,
    SelectionMode,
    Series,
    replace_cell,
)
from composeui.qtcore.qtrenderer import QtActionRenderer, QtWidgetRenderer
from composeui.qtcore.widgets.qchart import QChart
from examples.pipechart import PipeChartMainView
from examples.pipeform import EdgeType, PipeMainView
from tests.dialogs import DialogsMainView
from tests.grid import GridMainView
from tests.horizontal import ButtonsMainView, HorizontalMainView
from tests.pages import InputsPage, PagesMainView
from tests.tables import EditableTableMainView
from tests.toolbar import ToolBarMainView
from tests.translated import Size, TranslatedMainView
from tests.vertical import VerticalMainView

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.core.view import View


def _field_widget(view: object) -> QWidget:
    renderer = view.renderer  # type: ignore[attr-defined]
    assert isinstance(renderer, RendererContainer)
    field_renderer = renderer.get_renderer("field")
    assert isinstance(field_renderer, QtWidgetRenderer)
    widget = field_renderer.qt_object
    assert widget is not None
    return widget


def test_label_renderer_pushes_view_state_to_the_widget(qtbot: QtBot) -> None:
    view = LabelView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QLabel)

    view.text = "hello"
    assert widget.text() == "hello"


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

    # `update_state` (the other direction: widget -> view) is exercised too.
    name_widget.setText("direct")
    field_renderer = view.pages.inputs.pipe_form.name.renderer
    assert isinstance(field_renderer, RendererContainer)
    field_renderer.get_renderer("field").update_state()
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
    # each next to the one before, not spread over the width
    assert buttons[-1].geometry().right() < edge_widget.width() // 2


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
    table = view.pages.results.summary.renderer.qt_object
    assert isinstance(table, QTableView)
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
    assert isinstance(name_label.qt_object, QLabel)
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


def test_form_label_renderer_shows_the_row_label(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    renderer = view.pages.inputs.pipe_form.edge_type.renderer
    assert isinstance(renderer, RendererContainer)
    label_renderer = renderer.get_renderer("label")
    assert isinstance(label_renderer, QtWidgetRenderer)
    label_widget = label_renderer.qt_object
    assert isinstance(label_widget, QLabel)
    assert label_widget.text() == "Edge Type"


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

    menus = [action.menu() for action in window.menuBar().actions()]
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
    data = json.loads(saved_path.read_text())
    assert data["pages"]["inputs"]["pipe_form"]["name"]["text"] == "saved_name"


def _widget(view: View) -> QWidget:
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QWidget)
    return widget


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
        qtbot.waitUntil(lambda height=height: window.height() == height)
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
    assert box.parentWidget().window() is window
    assert box.windowTitle() == "Clear the name"
    assert box.text() == "The name will be lost."
    buttons = _shown_buttons(box)
    assert list(buttons) == ["Clear", "Cancel"]

    qtbot.keyClick(box, Qt.Key.Key_Escape)
    assert not box.isVisible()
    assert not view.confirm_clear.is_visible
    assert view.name.text == "Ada"

    view.confirm_clear.open()
    qtbot.mouseClick(buttons["Clear"], Qt.MouseButton.LeftButton)
    assert not box.isVisible()
    assert view.name.text == ""


def test_a_message_has_one_button_and_escape_or_closing_accepts_it(qtbot: QtBot) -> None:
    view, _window, box = _dialog_window(qtbot)
    dialog = view.confirm_clear
    dialog.kind = DialogKind.MESSAGE

    dialog.open()
    assert list(_shown_buttons(box)) == ["Clear"]
    qtbot.keyClick(box, Qt.Key.Key_Escape)
    assert view.name.text == ""

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
    table = _widget(view.tables.narrow)
    assert isinstance(table, QTableView)
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
    table = _widget(view.tables.narrow)
    assert isinstance(table, QTableView)
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
    table = _widget(view.places)
    assert isinstance(table, QTableView)
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


def test_the_chart_shows_its_titles_units_and_series(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    plot = chart.getPlotItem()
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
    view_box = chart.getPlotItem().vb
    view_box.setXRange(0.5, 1.0, padding=0)  # as the mouse wheel would

    view.pipe.diameter.value = 80
    view.add_curve()

    assert len(view.chart.series) == 2
    assert view_box.viewRange()[0] == [0.5, 1.0]


def test_hovering_the_chart_shows_the_values_at_the_cursor(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series(name="Pressure", x=[0, 1, 2], y=[10, 20, 30])]
    qtbot.waitUntil(lambda: chart.getPlotItem().vb.viewRange()[0][1] >= 2)
    view_box = chart.getPlotItem().vb
    assert chart.hover_text() == ""

    chart.scene().sigMouseMoved.emit(view_box.mapViewToScene(QPointF(1.05, 15)))

    qtbot.waitUntil(lambda: chart.hover_text() != "")
    lines = chart.hover_text().splitlines()
    assert lines[0].endswith(" L/s")
    assert lines[1] == "Pressure: 20 kPa"
    chart.scene().sigMouseMoved.emit(QPointF(-10, -10))  # off the plot
    qtbot.waitUntil(lambda: chart.hover_text() == "")


def test_the_chart_follows_the_palette(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series(name="Pressure", x=[0, 1], y=[0, 1])]
    (curve,) = chart.getPlotItem().listDataItems()
    assert curve.opts["pen"].color().name() == SERIES_COLORS[False][0]
    palette = chart.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))

    chart.setPalette(palette)

    assert curve.opts["pen"].color().name() == SERIES_COLORS[True][0]
    assert chart.backgroundBrush().color().name() == "#202020"
    assert chart.getPlotItem().getAxis("left").textPen().color().name() == "#f0f0f0"


def test_a_scatter_series_is_drawn_as_dots_over_the_lines(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.add_curve()
    view.add_measurements()
    model, measured = chart.getPlotItem().listDataItems()

    assert model.opts["symbol"] is None
    assert model.opts["pen"].color().name() == SERIES_COLORS[False][0]
    assert measured.opts["pen"].style() == Qt.PenStyle.NoPen
    assert measured.opts["symbol"] == "o"
    assert measured.opts["symbolBrush"].color().name() == SERIES_COLORS[False][1]
    assert chart.legend_names() == ["D = 50 mm", "Measured, D = 50 mm"]

    view.chart.kind = ChartKind.SCATTER  # the series without a kind of their own follow
    assert model.opts["symbol"] == "o"
    assert model.opts["pen"].style() == Qt.PenStyle.NoPen
