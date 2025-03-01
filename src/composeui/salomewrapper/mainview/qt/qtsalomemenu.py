r"""Toolbar View."""

from composeui.core.qt.qtactionview import QtActionView
from composeui.core.qt.qtview import QtView
from composeui.core.views.iactionview import IActionView
from composeui.mainview.interfaces.imenu import IMenu
from composeui.mainview.qt.qtmenu import QtMenu

from qtpy.QtWidgets import QAction, QMenu
from salome.gui import helper
from typing_extensions import OrderedDict

from dataclasses import dataclass, field, fields, make_dataclass
from typing import Type


@dataclass(eq=False)
class QtSalomeMenu(QtView, IMenu):
    r"""Menu."""

    name: str
    index: int

    view: QMenu = field(init=False)

    menu_id: int = field(init=False)

    _actions: OrderedDict[str, QtActionView] = field(
        init=False, repr=False, default_factory=OrderedDict
    )
    _sub_menus: OrderedDict[str, "QtMenu"] = field(
        init=False, repr=False, default_factory=OrderedDict
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        self.menu_id = helper.sgPyQt.createMenu(
            f"_{self.index}_{self.name}", -1, -1, self.index
        )
        menu_action: QAction = helper.sgPyQt.action(self.menu_id)
        self.view = menu_action.menu()
        self.add_actions()
        self.add_sub_menus()

    def add_action(self, name: str) -> None:
        action_view = QtActionView()
        # replace the IActionView with an ActionView
        setattr(self, name, action_view)
        helper.sgPyQt.createMenu(action_view.view, self.menu_id)
        action_view.data = name
        self._actions[name] = action_view
        self.view.addAction(action_view.view)

    def add_actions(self) -> None:
        for action_field in fields(self):
            if action_field.type is IActionView:
                self.add_action(action_field.name)

    def add_sub_menus(self) -> None:
        for action_field in fields(self):
            if action_field.type is IMenu:
                # TODO: add an example with submenus
                raise NotImplementedError("Submenus are not implemented yet")

    @property  # type: ignore[misc]
    def title(self) -> str:
        return str(self.view.title())

    @title.setter
    def title(self, value: str) -> None:
        self.view.setTitle(value)
        # TODO: Remove ?
        self.view.menuAction().setText(value)

    @classmethod
    def from_imenu(cls, name: str, index: int, imenu: IMenu) -> "QtSalomeMenu":
        """Create a Menu instance from an IMenu."""
        imenu_type = type(imenu)
        cls_name = imenu_type.__name__[1:]
        menu_type: Type[QtSalomeMenu] = make_dataclass(
            cls_name, (), bases=(QtSalomeMenu, imenu_type), eq=False
        )
        return menu_type(name, index)


@dataclass(eq=False)
class CheckableSalomeMenu(QtSalomeMenu):
    r"""Checkable Salome Menu."""

    def __post_init__(self) -> None:
        super().__post_init__()
        for action in self._actions.values():
            action.view.setCheckable(True)
