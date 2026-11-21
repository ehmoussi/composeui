"""Tests of the Qt forms and their rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QToolTip,
    QWidget,
)

from composeui.core.registry import RendererType
from composeui.core.renderer import RendererContainer
from composeui.core.view import (
    LogType,
)
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qformlabel import QFormLabel
from examples.pipeform import PipeMainView
from tests.folderform import StudyMainView
from tests.lonerows import LoneRowsMainView
from tests.unlabelled import NoteMainView

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


from tests.qtcore.support import _field_widget, _table, _widget


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


def test_a_form_shows_its_other_views_between_its_rows_in_their_order(qtbot: QtBot) -> None:
    view = StudyMainView()
    view.render(RendererType.QT)
    window = _widget(view)
    qtbot.addWidget(window)
    window.show()
    form = view.open_dialog.form
    layout = _widget(form).layout()
    assert isinstance(layout, QFormLayout)
    folder = _field_widget(form.folder)
    up, table = _widget(form.buttons.up), _table(form.entries)

    # each view spans the form, after the row before it
    rows = [layout.getWidgetPosition(_widget(child)) for child in (form.buttons, form.entries)]
    assert rows == [(1, QFormLayout.ItemRole.SpanningRole), (2, QFormLayout.ItemRole.SpanningRole)]
    qtbot.mouseClick(_widget(view.open), Qt.MouseButton.LeftButton)
    dialog = _widget(view.open_dialog)
    assert dialog.isVisible()
    assert all(dialog.isAncestorOf(widget) for widget in (folder, up, table))

    qtbot.mouseClick(up, Qt.MouseButton.LeftButton)

    assert dialog.isVisible()  # a button of its form leaves it open
    assert isinstance(folder, QLineEdit)
    assert folder.text() == "/studies"
    assert table.model().index(0, 0).data() == "beam"


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
