from composeui.core.basesignal import BaseSignal
from composeui.core.views.view import View

from dataclasses import dataclass, field
from typing import List


@dataclass(eq=False)
class ActionView(View):
    data: str = field(init=False, default="")
    text: str = field(init=False, default="")
    icon: str = field(init=False, default="")
    is_separator: bool = field(init=False, default=False)
    is_checkable: bool = field(init=False, default=False)
    is_checked: bool = field(init=False, default=False)
    shortcut: str = field(init=False, default="")
    visible_views: List["View"] = field(init=False, repr=False, default_factory=list)
    triggered: BaseSignal = field(init=False, repr=False, default=BaseSignal())
    toggled: BaseSignal = field(init=False, repr=False, default=BaseSignal())
    changed: BaseSignal = field(init=False, repr=False, default=BaseSignal())
