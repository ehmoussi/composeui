from composeui.core.tasks.abstracttask import AbstractTask
from composeui.core.views.iprogressview import IProgress

from dataclasses import dataclass, field


@dataclass(eq=False)
class IProgressPopupView(IProgress[AbstractTask]):
    title: str = field(init=False, default="Work in progress ...")
    label_text: str = field(init=False, default="Wait ...")
    # TODO: remove if really useless
    # finished: BaseSignal = field(init=False, default=BaseSignal())
