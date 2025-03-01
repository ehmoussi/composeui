from composeui.core.qt.progressview import ProgressView
from composeui.core.qt.view import View
from composeui.form.formview import GroupBoxFormView
from examples.taskview.msgspec.task import ITaskConfigForm, ITaskView, Task, TaskConfigItems

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QGridLayout, QLabel, QWidget

from dataclasses import dataclass, field
from typing import List


@dataclass(eq=False)
class TaskConfigForm(GroupBoxFormView[TaskConfigItems], ITaskConfigForm): ...


@dataclass(eq=False)
class TaskView(View, ITaskView):

    view: QWidget = field(init=False, default_factory=QWidget)
    config: TaskConfigForm = field(init=False, default_factory=TaskConfigForm)
    progress: ProgressView[Task] = field(init=False, default_factory=ProgressView[Task])

    labels: List[QLabel] = field(init=False, default_factory=list)
    _status_tasks: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view.setMinimumHeight(600)
        layout = QGridLayout()
        self.view.setLayout(layout)
        # Task config
        layout.addWidget(self.config.view, 0, 0, 1, 5)
        # Tasks labels
        for i in range(5):
            for j in range(5):
                label = QLabel(f"Task {5*i + j + 1}")
                label.setAlignment(Qt.AlignCenter)
                layout.addWidget(label, i + 1, j)
                self.labels.append(label)
                self._status_tasks.append("")
        # Run
        layout.addWidget(self.progress.view, 7, 0, 1, 5)

    @property  # type: ignore[misc]
    def status_tasks(self) -> List[str]:
        return self._status_tasks

    @status_tasks.setter
    def status_tasks(self, status: List[str]) -> None:
        if hasattr(self, "_status_tasks"):
            for i in range(len(self._status_tasks)):
                self.labels[i].setText(f"Task {i}\n{status[i]}\n")
                self._status_tasks[i] = status[i]
