r"""Salome Toolbar View."""

from composeui.core.interfaces.iactionview import IActionView
from composeui.core.qt.actionview import ActionView
from composeui.core.qt.view import View
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar, IToolBar

from PyQt5.QtWidgets import QToolBar  # need the real QToolbar or the findChildren may fail :/
from qtpy.QtWidgets import QActionGroup, QMainWindow
from salome.gui import helper

from dataclasses import dataclass, field, fields, make_dataclass
from typing import List, Type, cast


@dataclass(eq=False)
class SalomeToolBar(View, IToolBar):
    r"""Salome Toolbar."""

    module_name: str
    name: str

    view: QToolBar = field(init=False)

    toolbar_id: int = field(init=False)

    _actions: List[ActionView] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self._internal_name = f"{self.name}_{self.module_name}"
        self.toolbar_id = int(
            helper.sgPyQt.createTool(
                self._internal_name.replace("_", " ").title(),
                self._internal_name,
            )
        )
        if self.toolbar_id == -1:
            msg = f"Failed to add the toolbar '{self.name}'"
            raise ValueError(msg)
        main_window = cast(QMainWindow, helper.sgPyQt.getDesktop())
        toolbars = main_window.findChildren(QToolBar, self._internal_name)
        if len(toolbars) == 0:
            msg = f"Toolbar '{self.name}' ({self._internal_name}) not found"
            raise ValueError(msg)
        elif len(toolbars) > 1:
            msg = f"Multiple toolbars '{self.name}' ({self._internal_name}) found"
            raise ValueError(msg)
        else:
            self.view = toolbars[0]
        self.view.toggleViewAction().setVisible(False)
        self.view.setFloatable(False)
        self._add_actions()

    def _add_actions(self) -> None:
        r"""Add actions to toolbar."""
        for action_field in fields(self):
            if action_field.type is IActionView:
                self.add_action(action_field.name)

    def add_action(self, name: str) -> None:
        action = ActionView()
        setattr(self, name, action)
        self._actions.append(action)
        helper.sgPyQt.createTool(action.view, self.toolbar_id, -1, -1)
        action.view.setData(name)

    @property  # type: ignore[misc]
    def title(self) -> str:
        return self.view.windowTitle()

    @title.setter
    def title(self, title: str) -> None:
        self.view.setWindowTitle(title)

    @property  # type: ignore[misc]
    def is_movable(self) -> bool:
        return self.view.isMovable()

    @is_movable.setter
    def is_movable(self, is_movable: bool) -> None:
        self.view.setMovable(is_movable)

    @classmethod
    def from_itoolbar(cls, module_name: str, name: str, itoolbar: IToolBar) -> "SalomeToolBar":
        """Create a SalomeToolBar instance from an IToolBar."""
        itoolbar_type = type(itoolbar)
        cls_name = itoolbar_type.__name__
        if cls_name.startswith("I") and cls_name[1].isupper():
            cls_name = itoolbar_type.__name__[1:]
        toolbar_type: Type[SalomeToolBar] = make_dataclass(
            cls_name, (), bases=(SalomeToolBar, itoolbar_type), eq=False
        )
        return toolbar_type(module_name, name)


@dataclass(eq=False)
class CheckableSalomeToolBar(SalomeToolBar, ICheckableToolBar):
    r"""Checkable Salome Toolbar."""

    def __post_init__(self) -> None:
        super().__post_init__()
        self._actions_group = QActionGroup(self.view)
        self.add_actions_to_group()
        # assign signals
        self.toggled.add_qt_signals(
            *[(action, action.toggled) for action in self._actions_group.actions()]
        )

    def add_actions_to_group(self) -> None:
        for action in self._actions:
            action.view.setCheckable(True)
            self._actions_group.addAction(action.view)
        if len(self._actions) == 1:
            self._actions_group.setExclusive(False)

    @property  # type: ignore[misc]
    def is_exclusive(self) -> bool:
        return bool(self._actions_group.isExclusive())

    @is_exclusive.setter
    def is_exclusive(self, is_exclusive: bool) -> None:
        self._actions_group.setExclusive(is_exclusive)

    @classmethod
    def from_icheckable_toolbar(
        cls, module_name: str, name: str, itoolbar: ICheckableToolBar
    ) -> "CheckableSalomeToolBar":
        """Create a CheckableSalomeToolBar instance from an ICheckableToolBar."""
        itoolbar_type = type(itoolbar)
        cls_name = itoolbar_type.__name__
        if cls_name.startswith("I") and cls_name[1].isupper():
            cls_name = itoolbar_type.__name__[1:]
        toolbar_type: Type[CheckableSalomeToolBar] = make_dataclass(
            cls_name, (), bases=(CheckableSalomeToolBar, itoolbar_type), eq=False
        )
        return toolbar_type(module_name, name)
