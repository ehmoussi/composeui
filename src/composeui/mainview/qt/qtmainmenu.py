r"""View of the menu."""

from composeui.core.qt.qtview import QtView
from composeui.mainview.qt.qtmenu import QtMenu
from composeui.mainview.views.menu import Menu

from qtpy.QtWidgets import QMainWindow, QMenuBar
from typing_extensions import OrderedDict

from dataclasses import dataclass, field, fields


# Don't inherit from IMainMenu because it contains only menus
# and it messes with the 2nd level of inheritance when trying to create menus.
@dataclass(eq=False)
class QtMainMenu(QtView):
    r"""Main Menu View."""

    view: QMenuBar = field(init=False)
    main_view: QMainWindow
    menus: OrderedDict[str, QtMenu] = field(
        init=False, repr=False, default_factory=OrderedDict[str, QtMenu]
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = self.main_view.menuBar()
        self.add_menus()

    def add_menu(self, name: str, menu: QtMenu) -> None:
        self.menus[name] = menu
        self.view.addMenu(menu.view)

    def add_menus(self) -> None:
        """Add all menus of the interface to the main menu."""
        for menu_field in fields(self):
            imenu = getattr(self, menu_field.name)
            if isinstance(imenu, Menu):
                menu = QtMenu.from_imenu(imenu)
                setattr(self, menu_field.name, menu)
                self.add_menu(menu_field.name, menu)
