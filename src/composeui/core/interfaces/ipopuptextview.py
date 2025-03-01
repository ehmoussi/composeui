from composeui.core.interfaces.iview import IView

import enum
from dataclasses import dataclass, field


@enum.unique
class DialogChoices(enum.Enum):
    rejected = 0
    accepted = 1


@dataclass(eq=False)
class IPopupTextView(IView):
    title: str = field(init=False, default="")
    text: str = field(init=False, default="")
    confirm_button_text: str = field(init=False, default="")
    choice: DialogChoices = field(init=False, default=DialogChoices.rejected)

    def run(self) -> None: ...
