from composeui.core.qt.qtprogressview import QtProgressView
from composeui.core.qt.qtview import QtView
from composeui.form.qtformview import QtGroupBoxFormView
from examples.taskview.msgspec.task import Task, TaskConfigForm, TaskConfigItems, TaskView

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QGridLayout, QLabel, QWidget

from dataclasses import dataclass, field
from typing import List


@dataclass(eq=False)
class QtTaskConfigForm(QtGroupBoxFormView[TaskConfigItems], TaskConfigForm): ...


@dataclass(eq=False)
class QtTaskView(QtView, TaskView):

    view: QWidget = field(init=False, repr=False, default_factory=QWidget)
    config: QtTaskConfigForm = field(init=False, repr=False, default_factory=QtTaskConfigForm)
    progress: QtProgressView[Task] = field(
        init=False, repr=False, default_factory=QtProgressView[Task]
    )

    labels: List[QLabel] = field(init=False, repr=False, default_factory=list)
    _status_tasks: List[str] = field(repr=False, default_factory=list)

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
