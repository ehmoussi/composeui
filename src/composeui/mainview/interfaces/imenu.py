from composeui.core.interfaces.iactionview import IActionView
from composeui.core.interfaces.iview import IView

from dataclasses import dataclass, field


@dataclass(eq=False)
class IMenu(IView):
    title: str = field(init=False, default="")


@dataclass(eq=False)
class IFileMenu(IMenu):
    new: IActionView = field(init=False, default_factory=IActionView)
    open_file: IActionView = field(init=False, default_factory=IActionView)
    save: IActionView = field(init=False, default_factory=IActionView)
    save_as: IActionView = field(init=False, default_factory=IActionView)
    separator_exit: IActionView = field(init=False, default_factory=IActionView)
    exit_app: IActionView = field(init=False, default_factory=IActionView)
