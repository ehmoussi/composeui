from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.mainview.interfaces.imainview import IMainView
from composeui.model.pydanticmodel import PydanticModel
from examples.taskview.pydantic.task import ITaskView, connect_task, initialize_task

import pydantic
from typing_extensions import TypeAlias

from dataclasses import dataclass, field


class TaskConfig(pydantic.BaseModel):
    min_duration: int = 3
    max_duration: int = 10
    percentage_failure: int = 20


@dataclass(eq=False)
class IExampleMainView(IMainView):
    task: ITaskView = field(init=False, default_factory=ITaskView)


Model: TypeAlias = PydanticModel[TaskConfig]


class PydanticTaskViewApp(QtBaseApp[IExampleMainView, Model]):
    def __init__(self, main_view: IExampleMainView) -> None:
        super().__init__(
            PydanticModel("example", get_version("composeui"), TaskConfig(), is_debug=True),
            main_view,
        )

    def initialize_app(self) -> None:
        initialize_task(self.main_view.task, self.main_view, self.model)

    def connect_app(self) -> None:
        connect_task(self.main_view.task)
