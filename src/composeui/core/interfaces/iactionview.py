from composeui.core.basesignal import BaseSignal
from composeui.core.interfaces.iview import IView

from dataclasses import dataclass, field
from typing import List


@dataclass(eq=False)
class IActionView(IView):
    data: str = field(init=False, default="")
    text: str = field(init=False, default="")
    icon: str = field(init=False, default="")
    is_separator: bool = field(init=False, default=False)
    is_checkable: bool = field(init=False, default=False)
    is_checked: bool = field(init=False, default=False)
    shortcut: str = field(init=False, default="")
    visible_views: List["IView"] = field(init=False, default_factory=list)
    triggered: BaseSignal = field(init=False, default=BaseSignal())
    toggled: BaseSignal = field(init=False, default=BaseSignal())
    changed: BaseSignal = field(init=False, default=BaseSignal())
