"""Tests of the Qt main window, its router and its sidebar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtCore import QEvent, QObject, Qt
from qtpy.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QWidget,
)
from typing_extensions import override

from composeui.core.application import _add_reference_to_signals
from composeui.core.registry import RendererType
from composeui.core.view import (
    Router,
    StreamContent,
)
from composeui.qtcore._renderers.navigation import QtMainRenderer, QtMainWindow
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qsidebar import QSidebar
from examples.pipeform import PipeMainView
from tests.downloading import ReportMainView
from tests.markdown import HelpMainView
from tests.pages import (
    PagesMainView,
)
from tests.sidebar import SidebarMainView
from tests.toolbar import ToolBarMainView

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from pytestqt.qtbot import QtBot


from tests.qtcore.support import _dialog_window, _qt_widget, _shown_buttons, _widget


def test_an_app_s_file_is_saved_where_the_user_picks_one_dialog_at_a_time(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = ReportMainView()
    view.status_bar.timeout = 0  # no timer clearing the message after the test
    _add_reference_to_signals(view, None)  # as the app does
    view.render(RendererType.QT)
    qtbot.addWidget(_widget(view))
    answers = [
        tmp_path / "a.csv",
        None,
        tmp_path / "missing" / "b.csv",
        tmp_path / "c.csv",
        tmp_path / "d.csv",
    ]
    asked: list[str] = []

    def get_save_file_name(_parent: QWidget, _caption: str, name: str) -> tuple[str, str]:
        asked.append(name)
        if len(asked) == 1:  # e.g. a job's callback, in the dialog's own event loop
            view.download("second.txt", b"second")
            assert asked == ["report é.csv"]  # asked once this dialog is closed
        answer = answers[len(asked) - 1]
        return ("" if answer is None else str(answer)), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", get_save_file_name)
    export = _widget(view.export)

    qtbot.mouseClick(export, Qt.MouseButton.LeftButton)
    assert asked == ["report é.csv", "second.txt"]
    assert sorted(tmp_path.iterdir()) == [tmp_path / "a.csv"]  # the second cancelled
    assert (tmp_path / "a.csv").read_bytes() == b"a,b\n1,2\n"
    assert view.status_bar.message == "Saved a.csv."

    qtbot.mouseClick(export, Qt.MouseButton.LeftButton)  # into a folder that doesn't exist
    assert view.notification.message.startswith("Can't save to b.csv: ")
    assert sorted(tmp_path.iterdir()) == [tmp_path / "a.csv"]

    view.report = tmp_path / "a.csv"  # a file the app wrote: copied, and kept
    qtbot.mouseClick(export, Qt.MouseButton.LeftButton)
    assert (tmp_path / "c.csv").read_bytes() == b"a,b\n1,2\n"
    assert sorted(tmp_path.iterdir()) == [tmp_path / "a.csv", tmp_path / "c.csv"]

    view.report = StreamContent(lambda sink: sink.write(b"streamed"))  # written in a job
    qtbot.mouseClick(export, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: view.status_bar.message == "Saved d.csv.")
    assert (tmp_path / "d.csv").read_bytes() == b"streamed"


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
    assert isinstance(window, QtMainWindow)
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


class _WindowsShown(QObject):
    """Record the windows Qt shows, e.g. a widget shown before it's in a layout."""

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[QWidget] = []

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
            self.shown.append(watched)
        return False


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
    name = _widget(view.router.inputs.name)
    assert name.isVisible()
    # a page is built the first time it's shown, from its views as they are then
    assert view.router.results.total.renderer is None
    view.router.results.total.text = "Total: 3"

    results_button = toolbar.widgetForAction(actions["Results"])
    windows = _WindowsShown()
    app = QApplication.instance()
    assert app is not None
    app.installEventFilter(windows)
    qtbot.mouseClick(results_button, Qt.MouseButton.LeftButton)
    app.removeEventFilter(windows)
    assert windows.shown == []  # none of its widgets flashes as a window, as it's built
    assert view.router.current_route == "results"
    total = _widget(view.router.results.total)
    assert isinstance(total, QLabel)
    assert total.text() == "Total: 3"
    assert total.isVisible()  # at once, not at the event loop's next turn
    assert total.window() is window  # in the window, not a window of its own
    assert not name.isVisible()
    # clicking the shown page's entry again leaves it checked, the other unchecked
    qtbot.mouseClick(results_button, Qt.MouseButton.LeftButton)
    assert actions["Results"].isChecked()
    assert not actions["Inputs"].isChecked()

    view.router.navigate("inputs")  # from app code
    assert name.isVisible()
    assert actions["Inputs"].isChecked()
    assert not actions["Results"].isChecked()
    view.router.navigate("results")
    assert _widget(view.router.results.total) is total  # built once
    view.router.results.is_visible = False
    assert not total.isVisible()


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


def test_closing_the_window_asks_before_it_discards_unsaved_changes(qtbot: QtBot) -> None:
    view, window, _box = _dialog_window(qtbot)
    qtbot.waitExposed(window)
    view._mark_saved()  # noqa: SLF001 (as the app's start does)
    view.minimum_width = 800  # a field the study keeps

    window.close()  # as its title bar's button does
    box = _qt_widget(view.discard_changes)
    assert isinstance(box, QMessageBox)
    assert box.isVisible()
    assert window.isVisible()
    _shown_buttons(box)["Cancel"].click()
    qtbot.waitUntil(lambda: not box.isVisible())
    assert window.isVisible()

    window.close()
    _shown_buttons(box)["Discard"].click()
    qtbot.waitUntil(lambda: not window.isVisible())


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
    assert isinstance(window, QtMainWindow)
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
