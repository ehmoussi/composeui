from composeui.core.basesignal import BaseSignal
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.core.views.workerview import WorkerView

from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T", bound=AbstractTask)


@dataclass(eq=False)
class Progress(WorkerView[T]):
    is_percentage_visible: bool = field(init=False, default=False)
    minimum: int = field(init=False, default=0)
    maximum: int = field(init=False, default=100)
    value: int = field(init=False, default=0)


@dataclass(eq=False)
class ProgressView(Progress[T]):
    run_text: str = field(init=False, default="Run")
    cancel_text: str = field(init=False, default="Cancel")
    button_text: str = field(init=False, default="")
    button_enabled: bool = field(init=False, default=False)
    button_clicked: BaseSignal = field(init=False, repr=False, default=BaseSignal())
