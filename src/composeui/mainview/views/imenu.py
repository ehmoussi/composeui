from composeui.core.views.iactionview import ActionView
from composeui.core.views.iview import View

from dataclasses import dataclass, field


@dataclass(eq=False)
class Menu(View):
    title: str = field(init=False, default="")


@dataclass(eq=False)
class FileMenu(Menu):
    new: ActionView = field(init=False, default_factory=ActionView)
    open_file: ActionView = field(init=False, default_factory=ActionView)
    save: ActionView = field(init=False, default_factory=ActionView)
    save_as: ActionView = field(init=False, default_factory=ActionView)
    separator_exit: ActionView = field(init=False, default_factory=ActionView)
    exit_app: ActionView = field(init=False, default_factory=ActionView)
