from composeui.core.interfaces.iview import IView

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MessageViewType(Enum):
    question = 0
    warning = 1
    critical = 2


@dataclass(eq=False)
class IMessageView(IView):
    title: str = field(init=False, default="")
    message: str = field(init=False, default="")
    message_type: Optional[MessageViewType] = field(init=False, default=None)

    def run(self) -> Optional[bool]: ...
