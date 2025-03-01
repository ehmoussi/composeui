from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.mainview.views.mainview import MainView
from composeui.model.msgspecmodel import MsgspecModel
from examples.taskview.msgspec.task import TaskView, connect_task, initialize_task

import msgspec
from typing_extensions import TypeAlias

from dataclasses import dataclass, field


class TaskConfig(msgspec.Struct):
    min_duration: int = 3
    max_duration: int = 10
    percentage_failure: int = 20


@dataclass(eq=False)
class ExampleMainView(MainView):
    task: TaskView = field(init=False, default_factory=TaskView)


Model: TypeAlias = MsgspecModel[TaskConfig]


class MsgspecTaskViewApp(QtBaseApp[ExampleMainView, Model]):
    def __init__(self, main_view: ExampleMainView) -> None:
        super().__init__(
            MsgspecModel("example", get_version("composeui"), TaskConfig(), is_debug=True),
            main_view,
        )

    def initialize_app(self) -> None:
        initialize_task(self.main_view.task, self.main_view, self.model)

    def connect_app(self) -> None:
        connect_task(self.main_view.task)
