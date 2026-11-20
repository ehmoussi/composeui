"""Qt main window, router and sidebar renderers."""

from __future__ import annotations

import functools
import weakref
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from qtpy.QtCore import Qt
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMenuBar,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from typing_extensions import override

from composeui.core._views.files import save_download
from composeui.core.registry import RendererType
from composeui.core.renderer import MainRenderer
from composeui.core.view import MainView, Router, SidebarView, View
from composeui.qtcore._renderers.actions import QtActionRenderer, QtMenuRenderer, QtToolBarRenderer
from composeui.qtcore._renderers.containers import (
    QtPageRenderer,
    _add_content_widget,
    _adopt_dialogs,
)
from composeui.qtcore._renderers.content import QtStatusBarRenderer
from composeui.qtcore._renderers.files import _file_filters
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qcolumnlayout import QColumnLayout
from composeui.qtcore.widgets.qplaintext import plain_tool_tip
from composeui.qtcore.widgets.qsidebar import QSidebar

if TYPE_CHECKING:
    from collections.abc import Callable

    from qtpy.QtGui import QCloseEvent

    from composeui.core.view import DownloadedFile


class QtSidebarRenderer(QtWidgetRenderer[SidebarView, QSidebar]):
    """A dock on the window's left: its title and a button retracting it, then its views."""

    def __init__(self, view: SidebarView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "toggle_text": self._refresh_toggle_text,
                "is_expanded": self._refresh_is_expanded,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QSidebar()
            for view in self._view.children_views:
                _add_content_widget(self._rendered_object.content_layout, view)
            self._rendered_object.finish_content()
            # first, so the view's callbacks see the new state
            self._connect(
                self._rendered_object.expanded_changed,
                self._update_expanded,
                self._view.toggled.call_callbacks,
            )
            self.refresh()

    @staticmethod
    def _refresh_title(_view: SidebarView, rendered_object: QSidebar, value: str) -> None:
        rendered_object.set_title(value)

    @staticmethod
    def _refresh_toggle_text(_view: SidebarView, rendered_object: QSidebar, value: str) -> None:
        rendered_object.toggle.setToolTip(plain_tool_tip(value))
        rendered_object.toggle.setAccessibleName(value)

    @staticmethod
    def _refresh_is_expanded(_view: SidebarView, rendered_object: QSidebar, value: bool) -> None:
        rendered_object.set_expanded(value)

    def _update_expanded(self, is_expanded: bool) -> None:
        with self.stop_refresh():
            self._view.is_expanded = is_expanded


class QtRouterRenderer(QtWidgetRenderer[Router, QStackedWidget]):
    """The pages, stacked, and a toolbar of their actions that the window docks.

    Each page sits in a slot of its own: the stack shows and hides its slots, which
    leaves the page's own `is_visible` to the page. A page is built the first time it's
    shown, so an app's many pages don't slow its start.
    """

    #: read by `Router`: it renders only the page shown, and this renderer the others
    renders_on_demand = True

    def __init__(self, view: Router) -> None:
        super().__init__(view)
        #: the toolbar of the pages' actions, docked by the main window
        self.toolbar: QToolBar | None = None
        self._slots: dict[str, QWidget] = {}
        self._refresh_dispatcher.update({"current_route": self._refresh_current_route})

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QStackedWidget()
            self.toolbar = QToolBar()
            self.toolbar.setMovable(False)
            self.toolbar.toggleViewAction().setVisible(False)  # no way to close it
            for page in self._view.pages:
                assert isinstance(page.action.renderer, QtActionRenderer)
                page.action.renderer.set_parent_rendered_object(self.toolbar)
                page.action.renderer.render()
                assert page.action.renderer.qt_object is not None
                self.toolbar.addAction(page.action.renderer.qt_object)
                slot = QWidget()
                QVBoxLayout(slot).setContentsMargins(0, 0, 0, 0)
                self._slots[page.route] = slot
                self._rendered_object.addWidget(slot)
                if page.renderer is None:
                    # its dialogs, rendered already, open over the window before it's built
                    _adopt_dialogs(page, self._rendered_object)
            self.refresh()

    def _refresh_current_route(
        self, _view: Router, rendered_object: QStackedWidget, value: str
    ) -> None:
        slot = self._slots.get(value)
        if slot is not None:
            self._fill_slot(value, slot)
            rendered_object.setCurrentWidget(slot)

    def _fill_slot(self, route: str, slot: QWidget) -> None:
        """Put the page on `route` in its slot, building the page the first time it's shown."""
        layout = slot.layout()
        assert layout is not None
        if layout.count() > 0:
            return
        page = self._view.page(route)
        assert page is not None
        if page.renderer is None:
            page.render(RendererType.QT)
        assert isinstance(page.renderer, QtPageRenderer)
        assert page.renderer.qt_object is not None
        layout.addWidget(page.renderer.qt_object)
        # its visibility once in the slot: reparenting the widget hid it
        page.renderer.qt_object.setVisible(page.is_visible)


class QtMainWindow(QMainWindow):
    """The main view's window, which asks before a close loses the study's unsaved changes."""

    def __init__(self) -> None:
        super().__init__()
        #: whether a close goes on now, else it's refused; None lets every close go on, e.g.
        #: a reload's, which saved the study
        self.may_close: Callable[[], bool] | None = None

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self.may_close is None or self.may_close():
            super().closeEvent(event)
        else:
            event.ignore()


def _may_close(check: weakref.WeakMethod[Callable[[], bool]]) -> bool:
    """Call `check` to tell whether a window closes; a main view gone lets it."""
    method = check()
    return method is None or method()


class QtMainRenderer(
    QtWidgetRenderer[MainView, QtMainWindow], MainRenderer[MainView, QtMainWindow]
):
    def __init__(self, view: MainView, window: QtMainWindow | None = None) -> None:
        super().__init__(view)
        #: set by `close`: the app closes the window, once the user agreed if asked
        self._is_closing = False
        #: another main view's window to show this one in, in place of its parts, e.g.
        #: the previous code's on a reload: the window keeps its place and size
        self._window = window
        #: the downloads not asked yet: one asked while the save dialog is open waits for it
        self._downloads: deque[DownloadedFile] = deque()
        self._is_asking = False
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
                "state_filepath": self._refresh_state_filepath,
                "minimum_width": self._refresh_minimum_width,
                "minimum_height": self._refresh_minimum_height,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            if self._window is None:
                self._rendered_object = QtMainWindow()
            else:
                self._rendered_object = self._window
                self._clear_window(self._window)
            # this main view's, also in a window that another one showed; weak, as the
            # window's slots: the window outlives the views it showed
            self._rendered_object.may_close = functools.partial(
                _may_close, weakref.WeakMethod(self._may_close)
            )
            self._rendered_object.setMinimumSize(
                self._view.minimum_width, self._view.minimum_height
            )
            if self._view.app_icon is not None:
                self._rendered_object.setWindowIcon(QIcon(str(self._view.app_icon)))
            self._add_child_widgets(self._view, self._rendered_object)
            self.refresh()

    @override
    def open_file(self) -> Path | None:
        """Return an existing file selected by the user."""
        assert self._rendered_object is not None
        filepath_str, selected_filter = QFileDialog.getOpenFileName(
            self._rendered_object, "Open File", "", self._build_extensions()
        )
        return self._build_filepath(filepath_str, selected_filter)

    @override
    def save_file(self) -> Path | None:
        assert self._rendered_object is not None
        filepath_str, selected_filter = QFileDialog.getSaveFileName(
            self._rendered_object, "Save File", "", self._build_extensions()
        )
        return self._build_filepath(filepath_str, selected_filter)

    @override
    def download(self, file: DownloadedFile) -> None:
        self._downloads.append(file)
        # the dialog runs an event loop of its own, where a job's callback may download too
        if self._is_asking:
            return
        self._is_asking = True
        try:
            while self._downloads:
                file = self._downloads.popleft()
                path, _chosen = QFileDialog.getSaveFileName(
                    self._rendered_object, "", file.filename
                )
                if path != "":
                    save_download(self._view, Path(path), file.content)
        finally:
            self._is_asking = False

    @override
    def close(self) -> None:
        assert self._rendered_object is not None
        self._is_closing = True
        self._rendered_object.close()

    def _may_close(self) -> bool:
        """Tell whether the window's close goes on; else ask the user, who may close it."""
        view = self._view
        if self._is_closing or not view.has_file_menu or not view.has_unsaved_changes():
            return True
        # `MainView.close`, as Exit, which drops the jobs too
        view.discard_changes.ask(view.close)
        return False

    def _build_filepath(self, filepath_str: str, selected_filter: str) -> Path | None:
        if filepath_str == "":
            return None
        name_extension = selected_filter.split("(", maxsplit=1)[0].strip()
        filepath = Path(filepath_str)
        extensions = self._view.file_view.extensions.get(name_extension)
        if extensions is not None and all(
            not self._has_extension(filepath, extension) for extension in extensions
        ):
            filepath = Path(filepath_str + extensions[0])
        return filepath

    @staticmethod
    def _has_extension(filepath: Path, extension: str) -> bool:
        parts = [f".{e}" for e in extension.split(".") if e != ""]
        if len(parts) > 0:
            return filepath.suffixes[-len(parts) :] == parts
        return False

    def _build_extensions(self) -> str:
        return _file_filters(self._view.file_view.extensions)

    @staticmethod
    def _clear_window(window: QMainWindow) -> None:
        """Remove what another main view set on `window`: its bars, menus, sidebar and icon.

        Its content goes once replaced (`setCentralWidget`).
        """
        window.setWindowIcon(QIcon())  # set again only if this main view has one
        # the previous bars are deleted
        window.setMenuBar(QMenuBar())
        window.setStatusBar(None)  # type: ignore[arg-type]  # Qt takes none: it removes the bar
        for child in window.findChildren(QWidget, "", Qt.FindChildOption.FindDirectChildrenOnly):
            if isinstance(child, QToolBar):
                window.removeToolBar(child)
            elif isinstance(child, QDockWidget):
                window.removeDockWidget(child)
            elif not isinstance(child, QMenu):
                continue
            child.deleteLater()

    @staticmethod
    def _add_child_widgets(view: MainView, rendered_object: QMainWindow) -> None:
        central_widget = QWidget()
        central_layout = QColumnLayout()
        central_widget.setLayout(central_layout)
        for child_view in view.children_views:
            if QtMainRenderer._add_window_part(child_view, rendered_object):
                continue
            if isinstance(child_view.renderer, QtRouterRenderer):
                toolbar = child_view.renderer.toolbar
                stack = child_view.renderer.qt_object
                assert toolbar is not None
                assert stack is not None
                rendered_object.addToolBar(toolbar)
                # it takes the window's spare height, for its pages: each scrolls once too tall
                central_layout.addWidget(stack)
            else:
                _add_content_widget(central_layout, child_view)
        central_layout.add_spare_space()
        central_layout.update()
        rendered_object.setCentralWidget(central_widget)

    @staticmethod
    def _add_window_part(child_view: View, rendered_object: QMainWindow) -> bool:
        """Add a part of the window around the content, if `child_view` is one.

        Its menus, status bar, toolbars and sidebar; return whether `child_view` is one.
        """
        renderer = child_view.renderer
        if isinstance(renderer, QtMenuRenderer):
            renderer.set_parent_rendered_object(rendered_object)
            renderer.render()
            assert renderer.qt_object is not None
            rendered_object.menuBar().addMenu(renderer.qt_object)
        elif isinstance(renderer, QtStatusBarRenderer):
            assert isinstance(renderer.qt_object, QStatusBar)
            rendered_object.setStatusBar(renderer.qt_object)
        elif isinstance(renderer, QtToolBarRenderer):
            assert renderer.qt_object is not None
            rendered_object.addToolBar(renderer.qt_object)
        elif isinstance(renderer, QtSidebarRenderer):
            assert renderer.qt_object is not None
            rendered_object.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, renderer.qt_object)
        else:
            return False
        return True

    @staticmethod
    def _refresh_title(_view: MainView, rendered_object: QMainWindow, value: str) -> None:
        rendered_object.setWindowTitle(value)

    @staticmethod
    def _refresh_state_filepath(
        _view: MainView, rendered_object: QMainWindow, value: Path
    ) -> None: ...

    @staticmethod
    def _refresh_minimum_width(_view: MainView, rendered_object: QMainWindow, value: int) -> None:
        rendered_object.setMinimumWidth(value)

    @staticmethod
    def _refresh_minimum_height(_view: MainView, rendered_object: QMainWindow, value: int) -> None:
        rendered_object.setMinimumHeight(value)
