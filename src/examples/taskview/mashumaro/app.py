from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.mainview.views.mainview import MainView
from composeui.model.mashumaromodel import MashumaroModel
from examples.taskview.mashumaro.task import TaskView, connect_task, initialize_task

from mashumaro.mixins.json import DataClassJSONMixin
from typing_extensions import TypeAlias

from dataclasses import dataclass, field


@dataclass
class TaskConfig(DataClassJSONMixin):
    min_duration: int = 3
    max_duration: int = 10
    percentage_failure: int = 20


@dataclass(eq=False)
class ExampleMainView(MainView):
    task: TaskView = field(init=False, repr=False, default_factory=TaskView)


Model: TypeAlias = MashumaroModel[TaskConfig]


class MashumaroTaskViewApp(QtBaseApp[ExampleMainView, Model]):
    def __init__(self, main_view: ExampleMainView) -> None:
        super().__init__(
            MashumaroModel("example", get_version("composeui"), TaskConfig(), is_debug=True),
            main_view,
        )

    def initialize_app(self) -> None:
        initialize_task(self.main_view.task, self.main_view, self.model)

    def connect_app(self) -> None:
        connect_task(self.main_view.task)
