r"""Main view."""

from composeui.core.qt.qtfileview import QtFileView
from composeui.core.qt.qtview import QtView
from composeui.mainview.qt.qtmessageview import QtMessageView
from composeui.mainview.qt.qtprogresspopupview import QtProgressPopupView
from composeui.salomewrapper.core.qt.qtsalomecentralview import QtSalomeCentralView
from composeui.salomewrapper.core.qt.qtsalometree import QtSalomeTree
from composeui.salomewrapper.core.qt.qtsalomeviews import QtSalomeViews
from composeui.salomewrapper.mainview.isalomemainview import SalomeMainView

import SalomePyQt
from qtpy.QtWidgets import QMainWindow, QMenu
from salome.gui import helper

from dataclasses import dataclass, field
from typing import cast


@dataclass(eq=False)
class QtSalomeMainView(QtView, SalomeMainView):
    """Salome main view."""

    view: QMainWindow = field(init=False)
    message_view: QtMessageView = field(init=False)
    file_view: QtFileView = field(init=False)
    progress_popup_view: QtProgressPopupView = field(init=False)
    salome_tree: QtSalomeTree = field(init=False)
    salome_views: QtSalomeViews = field(init=False)
    central_view: QtSalomeCentralView = field(init=False)

    def __post_init__(self) -> None:
        self.view = self._get_salome_desktop()
        super().__post_init__()
        # message view
        self.message_view = QtMessageView(self.view)
        # file view
        self.file_view = QtFileView(self.view)
        # progress view
        self.progress_popup_view = QtProgressPopupView(self.view)

    def create_central_views(self) -> None:
        # central view
        self.central_view = QtSalomeCentralView(
            module_name=self.module_name,
            view_type=f"central_view_{self.module_name}",
            main_id=None,
        )
        self.central_view.is_closable = False
        self.salome_tree = QtSalomeTree()
        self.salome_views = QtSalomeViews(
            module_name=self.module_name,
            main_id=self.central_view.get_view_id(),
        )

    @property  # type: ignore[misc]
    def is_visible(self) -> bool:
        return self.central_view.is_active

    @is_visible.setter
    def is_visible(self, is_visible: bool) -> None:
        self._set_visible(is_visible)

    def _set_visible(self, is_visible: bool) -> None:
        self._show_salome_default_menu(not is_visible)
        if is_visible:
            self.central_view.is_visible = True
            self.central_view.is_active = True
        else:
            self.central_view.is_visible = False

    @property  # type: ignore[misc]
    def title(self) -> str:
        return self.central_view.title

    @title.setter
    def title(self, title: str) -> None:
        self.central_view.title = title

    @property  # type: ignore[misc]
    def closed(self) -> bool:
        return False

    @closed.setter
    def closed(self, closed: bool) -> None:
        if closed:
            self.view.close()

    def _show_salome_default_menu(self, is_visible: bool) -> None:
        menu_ids = [
            SalomePyQt.File,
            SalomePyQt.Edit,
            SalomePyQt.Tools,
            SalomePyQt.Window,
            # SalomePyQt.View
        ]
        for menu_id in menu_ids:
            menu: QMenu = helper.sgPyQt.getPopupMenu(menu_id)
            for action in menu.actions():
                action.setVisible(is_visible)

    def _get_salome_desktop(self) -> QMainWindow:
        return cast(QMainWindow, helper.sgPyQt.getDesktop())
