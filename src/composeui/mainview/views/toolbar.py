from composeui.core.basesignal import BaseSignal
from composeui.core.views.actionview import ActionView
from composeui.core.views.view import View

from dataclasses import dataclass, field

# from typing import Mapping


@dataclass(eq=False)
class ToolBar(View):
    is_always_visible: bool = field(init=False, default=False)
    title: str = field(init=False, default="")
    is_movable: bool = field(init=False, default=False)


@dataclass(eq=False)
class CheckableToolBar(ToolBar):
    is_exclusive: bool = field(init=False, default=False)
    toggled: BaseSignal = field(init=False, repr=False, default=BaseSignal())


@dataclass(eq=False)
class FileToolBar(ToolBar):
    new: ActionView = field(init=False, repr=False, default_factory=ActionView)
    open_file: ActionView = field(init=False, repr=False, default_factory=ActionView)
    save: ActionView = field(init=False, repr=False, default_factory=ActionView)
    save_as: ActionView = field(init=False, repr=False, default_factory=ActionView)
    undo: ActionView = field(init=False, repr=False, default_factory=ActionView)
    redo: ActionView = field(init=False, repr=False, default_factory=ActionView)
