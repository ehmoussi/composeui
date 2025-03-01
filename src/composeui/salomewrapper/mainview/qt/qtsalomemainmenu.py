r"""View of the menu."""

from composeui.core.qt.qtview import QtView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.interfaces.imenu import IMenu
from composeui.salomewrapper.mainview.qt.qtsalomemenu import QtSalomeMenu

from typing_extensions import OrderedDict

from dataclasses import dataclass, field, fields


@dataclass(eq=False)
class QtSalomeMainMenu(QtView, IMainMenu):
    r"""Salome main menu View."""

    menus: OrderedDict[str, QtSalomeMenu] = field(
        init=False, repr=False, default_factory=OrderedDict[str, QtSalomeMenu]
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = None
        self.add_menus()

    def add_menus(self) -> None:
        """Add all menus of the interface to the main menu."""
        index = 0
        for menu_field in fields(self):
            imenu = getattr(self, menu_field.name)
            if isinstance(imenu, IMenu):
                name = menu_field.name
                menu = QtSalomeMenu.from_imenu(name, index, imenu)
                setattr(self, name, menu)
                self.menus[name] = menu
                index += 1
