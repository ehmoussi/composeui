r"""Toolbar View."""

from composeui.core.qt.qtactionview import QtActionView
from composeui.core.qt.qtview import QtView
from composeui.core.views.iactionview import ActionView
from composeui.mainview.views.itoolbar import CheckableToolBar, ToolBar

from qtpy.QtWidgets import QActionGroup, QToolBar

from dataclasses import dataclass, field, fields, make_dataclass
from typing import List, Type


@dataclass(eq=False)
class QtToolBar(QtView, ToolBar):
    r"""Toolbar."""

    view: QToolBar = field(init=False)
    _actions: List[QtActionView] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = QToolBar()
        self.view.toggleViewAction().setVisible(False)
        self.view.setFloatable(False)
        self._add_actions()

    def _add_actions(self) -> None:
        r"""Add actions to toolbar."""
        for action_field in fields(self):
            if action_field.type is ActionView:
                self.add_action(action_field.name)

    def add_action(self, name: str) -> None:
        action = QtActionView()
        setattr(self, name, action)
        self._actions.append(action)
        self.view.addAction(action.view)
        action.view.setData(name)

    # @property
    # def actions(self) -> OrderedDict[str, ActionView]:
    #     return self._actions

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
    def from_itoolbar(cls, itoolbar: ToolBar) -> "QtToolBar":
        """Create a ToolBar instance from an IToolBar."""
        itoolbar_type = type(itoolbar)
        cls_name = itoolbar_type.__name__
        if cls_name.startswith("I") and cls_name[1].isupper():
            cls_name = itoolbar_type.__name__[1:]
        toolbar_type: Type[QtToolBar] = make_dataclass(
            cls_name, (), bases=(QtToolBar, itoolbar_type), eq=False
        )
        return toolbar_type()


@dataclass(eq=False)
class QtCheckableToolBar(QtToolBar, CheckableToolBar):
    r"""Checkable Toolbar."""

    _actions_group: QActionGroup = field(init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self._actions_group = QActionGroup(self.view)
        self.add_actions_to_group()
        # assign signals
        self.toggled.add_qt_signals(
            *[(action, action.toggled) for action in self.view.actions()]
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
    def from_icheckable_toolbar(cls, itoolbar: CheckableToolBar) -> "QtCheckableToolBar":
        """Create a CheckableToolBar instance from an ICheckableToolBar."""
        itoolbar_type = type(itoolbar)
        cls_name = itoolbar_type.__name__
        if cls_name.startswith("I") and cls_name[1].isupper():
            cls_name = itoolbar_type.__name__[1:]
        toolbar_type: Type[QtCheckableToolBar] = make_dataclass(
            cls_name, (), bases=(QtCheckableToolBar, itoolbar_type), eq=False
        )
        return toolbar_type()
