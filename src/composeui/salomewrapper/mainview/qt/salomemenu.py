r"""Toolbar View."""

from composeui.core.interfaces.iactionview import IActionView
from composeui.core.qt.actionview import ActionView
from composeui.core.qt.view import View
from composeui.mainview.interfaces.imenu import IMenu
from composeui.mainview.qt.menu import Menu

from qtpy.QtWidgets import QAction, QMenu
from salome.gui import helper
from typing_extensions import OrderedDict

from dataclasses import dataclass, field, fields, make_dataclass
from typing import Type


@dataclass(eq=False)
class SalomeMenu(View, IMenu):
    r"""Menu."""

    name: str
    index: int

    view: QMenu = field(init=False)

    menu_id: int = field(init=False)

    _actions: OrderedDict[str, ActionView] = field(
        init=False, repr=False, default_factory=OrderedDict[str, ActionView]
    )
    _sub_menus: OrderedDict[str, "Menu"] = field(
        init=False, repr=False, default_factory=OrderedDict[str, "Menu"]
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
        action_view = ActionView()
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
    def from_imenu(cls, name: str, index: int, imenu: IMenu) -> "SalomeMenu":
        """Create a Menu instance from an IMenu."""
        imenu_type = type(imenu)
        cls_name = imenu_type.__name__[1:]
        menu_type: Type[SalomeMenu] = make_dataclass(
            cls_name, (), bases=(SalomeMenu, imenu_type), eq=False
        )
        return menu_type(name, index)


@dataclass(eq=False)
class CheckableSalomeMenu(SalomeMenu):
    r"""Checkable Salome Menu."""

    def __post_init__(self) -> None:
        super().__post_init__()
        for action in self._actions.values():
            action.view.setCheckable(True)
