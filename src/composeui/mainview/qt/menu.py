r"""Toolbar View."""

from composeui.core.interfaces.iactionview import IActionView
from composeui.core.qt.actionview import ActionView
from composeui.core.qt.view import View
from composeui.mainview.interfaces.imenu import IMenu

from qtpy.QtWidgets import QMenu
from typing_extensions import OrderedDict

from dataclasses import dataclass, field, fields, make_dataclass
from typing import Tuple, Type


@dataclass(eq=False)
class Menu(View, IMenu):
    r"""Menu."""

    view: QMenu = field(init=False)
    _actions: OrderedDict[str, ActionView] = field(
        init=False, repr=False, default_factory=OrderedDict[str, ActionView]
    )
    _sub_menus: OrderedDict[str, "Menu"] = field(
        init=False, repr=False, default_factory=OrderedDict[str, "Menu"]
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = QMenu()
        self.add_actions()
        self.add_sub_menus()

    def add_action(self, name: str) -> None:
        action_view = ActionView()
        # replace the IActionView with an ActionView
        setattr(self, name, action_view)
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

    @property  # type:ignore[misc]
    def title(self) -> str:
        return str(self.view.title())

    @title.setter
    def title(self, value: str) -> None:
        self.view.setTitle(value)
        self.view.menuAction().setText(value)

    @property
    def actions(self) -> OrderedDict[str, ActionView]:
        return self._actions

    @property
    def sub_menus(self) -> OrderedDict[str, "Menu"]:
        return self._sub_menus

    @property
    def sections(self) -> Tuple[str, ...]:
        return tuple(action.data() for action in self.view.actions() if action.isSeparator())

    @sections.setter
    def sections(self, value: Tuple[str, ...]) -> None:
        for before_action in value:
            action_view = self._actions[before_action]
            if isinstance(action_view, ActionView):
                separator = self.view.insertSection(action_view.view, "")
                separator.setData(before_action)

    @classmethod
    def from_imenu(cls, imenu: IMenu) -> "Menu":
        """Create a Menu instance from an IMenu."""
        imenu_type = type(imenu)
        cls_name = imenu_type.__name__
        if cls_name.startswith("I") and cls_name[1].isupper():
            cls_name = imenu_type.__name__[1:]
        menu_type: Type[Menu] = make_dataclass(
            cls_name, (), bases=(Menu, imenu_type), eq=False
        )
        return menu_type()
