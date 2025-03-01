from composeui.core.basesignal import BaseSignal
from composeui.core.views.iactionview import IActionView
from composeui.core.views.iview import IView

from dataclasses import dataclass, field

# from typing import Mapping


@dataclass(eq=False)
class IToolBar(IView):
    is_always_visible: bool = field(init=False, default=False)
    title: str = field(init=False, default="")
    is_movable: bool = field(init=False, default=False)


@dataclass(eq=False)
class ICheckableToolBar(IToolBar):
    is_exclusive: bool = field(init=False, default=False)
    toggled: BaseSignal = field(init=False, default=BaseSignal())


@dataclass(eq=False)
class IFileToolBar(IToolBar):
    new: IActionView = field(init=False, default_factory=IActionView)
    open_file: IActionView = field(init=False, default_factory=IActionView)
    save: IActionView = field(init=False, default_factory=IActionView)
    save_as: IActionView = field(init=False, default_factory=IActionView)
