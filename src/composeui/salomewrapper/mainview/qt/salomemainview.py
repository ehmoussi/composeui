r"""Main view."""

from composeui.core.qt.fileview import FileView
from composeui.core.qt.view import View
from composeui.mainview.qt.messageview import MessageView
from composeui.mainview.qt.progresspopupview import ProgressPopupView
from composeui.salomewrapper.core.qt.salomecentralview import SalomeCentralView
from composeui.salomewrapper.core.qt.salometree import SalomeTree
from composeui.salomewrapper.core.qt.salomeviews import SalomeViews
from composeui.salomewrapper.mainview.isalomemainview import ISalomeMainView

import SalomePyQt
from qtpy.QtWidgets import QMainWindow, QMenu
from salome.gui import helper

from dataclasses import dataclass, field
from typing import cast


@dataclass(eq=False)
class SalomeMainView(View, ISalomeMainView):
    """Salome main view."""

    view: QMainWindow = field(init=False)
    message_view: MessageView = field(init=False)
    file_view: FileView = field(init=False)
    progress_popup_view: ProgressPopupView = field(init=False)
    salome_tree: SalomeTree = field(init=False)
    salome_views: SalomeViews = field(init=False)
    central_view: SalomeCentralView = field(init=False)

    def __post_init__(self) -> None:
        self.view = self._get_salome_desktop()
        super().__post_init__()
        # message view
        self.message_view = MessageView(self.view)
        # file view
        self.file_view = FileView(self.view)
        # progress view
        self.progress_popup_view = ProgressPopupView(self.view)

    def create_central_views(self) -> None:
        # central view
        self.central_view = SalomeCentralView(
            module_name=self.module_name,
            view_type=f"central_view_{self.module_name}",
            main_id=None,
        )
        self.central_view.is_closable = False
        self.salome_tree = SalomeTree()
        self.salome_views = SalomeViews(
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
