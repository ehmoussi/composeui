"""Tests of what every Qt renderer shares."""

from __future__ import annotations

import gc
import weakref
from typing import TYPE_CHECKING

import pytest
from qtpy.QtCore import Qt
from qtpy.QtGui import (
    QTextDocument,
)
from qtpy.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QTextBrowser,
    QWidget,
)

from composeui.core.application import _add_reference_to_signals
from composeui.core.registry import RendererType, create_renderer
from composeui.core.renderer import NoRenderedObjectError, RendererContainer
from composeui.core.view import (
    InputView,
    LabelView,
    Router,
    TabView,
)
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qexpander import QExpander
from composeui.qtcore.widgets.qfiltertable import QFilterTable
from composeui.qtcore.widgets.qformlabel import QFormLabel
from examples.pipecatalogue import PipeCatalogueMainView
from examples.pipeform import PipeMainView
from tests.bookings import BookingMainView
from tests.charts import ChartPagesMainView
from tests.choices import ChoicesMainView
from tests.console import RunMainView
from tests.datafiles import DataFileMainView
from tests.dialogs import DialogsMainView
from tests.expander import RecordMainView
from tests.formdialog import PipeMainView as EditedPipeMainView
from tests.grid import GridMainView
from tests.hours import HoursMainView
from tests.listview import PIPES, PipeExpander, PipesMainView
from tests.markdown import HelpMainView
from tests.markup import MARKUP, MarkupMainView
from tests.menubutton import MenuButtonMainView
from tests.metrics import JobsMainView
from tests.ranges import RangesMainView
from tests.sidebar import SidebarMainView
from tests.splitter import SplitterMainView
from tests.tables import (
    CellWidgetsMainView,
    RoomsDataMainView,
)
from tests.tabs import TabsMainView
from tests.toolbar import ToolBarMainView
from tests.translated import Size, TranslatedMainView
from tests.workers import WorkersMainView

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from composeui.core.view import MainView, View

from tests.qtcore.support import _field_widget, _qt_widget, _widget


def test_a_failed_refresh_leaves_the_widget_s_signals_as_they_were(qtbot: QtBot) -> None:
    view = InputView(text="before")
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    widget = view.renderer.qt_object
    assert isinstance(widget, QLineEdit)
    qtbot.addWidget(widget)
    with pytest.raises(AttributeError):
        view.renderer.refresh_attribute("no_such_attribute", 1)
    qtbot.keyClicks(widget, "!")
    assert view.text == "before!"
    widget.blockSignals(True)  # noqa: FBT003 (Qt's API)
    with pytest.raises(AttributeError):
        view.renderer.refresh_attribute("no_such_attribute", 1)
    assert widget.signalsBlocked()
    view.renderer.refresh()
    assert widget.signalsBlocked()


def test_a_view_rendered_alone_shows_and_hides_as_the_view_says(qtbot: QtBot) -> None:
    view = LabelView(text="Alone")
    view.render(RendererType.QT)
    label = _widget(view)
    qtbot.addWidget(label)
    assert not label.isVisible()  # no window of its own until the app shows it
    label.show()

    view.is_visible = False
    assert not label.isVisible()
    view.is_visible = True
    assert label.isVisible()


def _rendered_pipes_holding_their_main_view() -> tuple[PipesMainView, QWidget]:
    """Render pipes whose widgets' callbacks hold the main view, as an app's closures do.

    Built here, so the closures keep the main view: a `del` in the test would empty them.
    """
    view = PipesMainView()
    view.status_bar.timeout = 0  # no timer to clear the message
    _add_reference_to_signals(view, None)
    view.pipes.items = PIPES[:1]
    view.render(RendererType.QT)
    view.pipes.items = PIPES  # a record's view built after the render too
    for pipe in view.pipes.item_views:
        assert isinstance(pipe, PipeExpander)
        # fewer arguments than `toggled` emits, so the signal wraps it
        pipe.toggled.connect(lambda: view.status_bar.show_message("Toggled"))
    return view, _widget(view)


@pytest.mark.usefixtures("qtbot")  # its QApplication; not `addWidget`, which keeps the window
def test_a_window_s_widgets_run_the_callbacks_and_keep_none_of_its_views() -> None:
    view, window = _rendered_pipes_holding_their_main_view()
    expander = _widget(view.pipes.item_views[-1])
    assert isinstance(expander, QExpander)
    expander.header.click()
    assert view.status_bar.message == "Toggled"
    reference = weakref.ref(view)

    del view
    gc.collect()

    # the window lives on, but its slots hold the views weakly: it can't keep the app alive
    assert reference() is None
    window.deleteLater()


def test_a_callback_s_error_on_a_widget_s_signal_is_reported_and_the_next_ones_run(
    qtbot: QtBot,
) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    insulated = view.pages.inputs.pipe_form.insulated
    checkbox = _field_widget(insulated)
    assert isinstance(checkbox, QCheckBox)
    toggled: list[bool] = []

    def fail() -> None:
        msg = "No insulation"
        raise ValueError(msg)

    insulated.toggled.connect(fail)
    insulated.toggled.connect(toggled.append)

    with qtbot.capture_exceptions() as exceptions:
        checkbox.click()

    # as when each callback was a slot of its own
    assert [str(error) for _, error, _ in exceptions] == ["No insulation"]
    assert toggled == [True]


@pytest.mark.usefixtures("qtbot")
def test_a_call_for_the_main_thread_is_dropped_once_its_renderer_is_collected() -> None:
    called: list[str] = []
    gone = LabelView()
    gone.render(RendererType.QT)
    kept = LabelView()
    kept.render(RendererType.QT)
    assert gone.renderer is not None
    assert kept.renderer is not None
    gone.renderer.call_on_main_thread(lambda: called.append("gone"))
    kept.renderer.call_on_main_thread(lambda: called.append("kept"))

    del gone  # e.g. the main view a reload replaced
    gc.collect()
    QApplication.processEvents()

    assert called == ["kept"]


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


def _show_every_page_and_tab(view: View) -> None:
    """Show each page of `view`'s routers and each tab of its tab views: Qt builds them."""
    for child_view in view.children_views:
        if isinstance(child_view, Router):
            for page in child_view.pages:
                child_view.navigate(page.route)
        elif isinstance(child_view, TabView):
            for index in range(len(child_view.tabs)):
                child_view.current_index = index
        _show_every_page_and_tab(child_view)


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
        MenuButtonMainView,
        CellWidgetsMainView,
        RoomsDataMainView,
        HelpMainView,
        RunMainView,
        JobsMainView,
        BookingMainView,
        DataFileMainView,
        EditedPipeMainView,
        HoursMainView,
        WorkersMainView,
        ChoicesMainView,
        RangesMainView,
    ],
)
def test_a_main_view_rendered_again_keeps_every_widget(
    qtbot: QtBot, main_view_type: type[MainView]
) -> None:
    view = main_view_type()
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    _show_every_page_and_tab(view)  # built once shown: all of them, to keep them all
    before = _widgets_of(view)

    view.render(RendererType.QT)

    after = _widgets_of(view)
    assert [id(widget) for widget in after] == [id(widget) for widget in before]


def test_a_view_shown_before_its_widget_is_built_raises(qtbot: QtBot) -> None:
    view = LabelView()
    renderer = create_renderer(RendererType.QT, "label", view)
    assert renderer is not None
    view.renderer = renderer

    with pytest.raises(NoRenderedObjectError):
        view.text = "Too early"
    with pytest.raises(NoRenderedObjectError):
        renderer.refresh()


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
