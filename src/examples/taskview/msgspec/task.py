from composeui import form
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.core.tasks.tasks import Tasks
from composeui.core.views.progressview import ProgressView
from composeui.core.views.view import View
from composeui.form.abstractformitems import AbstractFormItems
from composeui.form.formview import GroupBoxFormView, LabelSpinBoxView

import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

if TYPE_CHECKING:
    from examples.taskview.msgspec.app import ExampleMainView, Model


@dataclass(eq=False)
class TaskConfigForm(GroupBoxFormView["TaskConfigItems"]):
    min_duration: LabelSpinBoxView["TaskConfigItems"] = field(
        init=False, repr=False, default_factory=LabelSpinBoxView["TaskConfigItems"]
    )
    max_duration: LabelSpinBoxView["TaskConfigItems"] = field(
        init=False, repr=False, default_factory=LabelSpinBoxView["TaskConfigItems"]
    )
    percentage_failure: LabelSpinBoxView["TaskConfigItems"] = field(
        init=False, repr=False, default_factory=LabelSpinBoxView["TaskConfigItems"]
    )


@dataclass(eq=False)
class TaskView(View):
    status_tasks: List[str] = field(init=False, default_factory=list)

    config: TaskConfigForm = field(init=False, repr=False, default_factory=TaskConfigForm)
    progress: ProgressView["Task"] = field(
        init=False, repr=False, default_factory=ProgressView["Task"]
    )


class Task(AbstractTask):
    def __init__(self, id_task: int, model: "Model") -> None:
        super().__init__(capture_exceptions_as_errors=True)
        self.id_task = id_task
        self._model = model

    def _run(self) -> Optional[bool]:
        t = random.random() * self._model.root.max_duration + self._model.root.min_duration
        self._logger.info(
            "Hey, I'm running Task %s! What the heck %.1f s?",
            self.id_task,
            t,
        )
        time.sleep(t)
        # 20 % chance that the task fail
        if random.random() <= (self._model.root.percentage_failure / 100):
            msg = f"Random Error: Task {self.id_task} failed"
            self._logger.error("Oh Oh ... Task %s are you fine ?", self.id_task)
            # The exception is captured and the message is stored to
            # be displayed gracefully to the user
            raise ValueError(msg)
        return True


class TaskConfigItems(AbstractFormItems["Model", "TaskConfigForm"]):
    def __init__(self, model: "Model", view: "TaskConfigForm") -> None:
        super().__init__(model, view)
        self._labels = {
            "min_duration": "Minimum Duration (s)",
            "max_duration": "Maximum Duration (s)",
            "percentage_failure": "Percentage of Failure (%)",
        }

    def get_label(self, field: str, parent_fields: Tuple[str, ...] = ()) -> str:
        return self._labels[field]

    def get_value(self, field: str, parent_fields: Tuple[str, ...] = ()) -> Any:
        if field == "min_duration":
            return self._model.root.min_duration
        elif field == "max_duration":
            return self._model.root.max_duration
        elif field == "percentage_failure":
            return self._model.root.percentage_failure
        return super().get_value(field, parent_fields)

    def set_value(self, field: str, value: Any, parent_fields: Tuple[str, ...] = ()) -> bool:
        int_value = self.to_int_value(value)
        if int_value is not None:
            if field == "min_duration":
                self._model.root.min_duration = int_value
            elif field == "max_duration":
                self._model.root.max_duration = int_value
            elif field == "percentage_failure":
                self._model.root.percentage_failure = int_value
            return True
        return super().set_value(field, value, parent_fields)


def update_task_status(*, view: ProgressView["Task"], parent_view: "TaskView") -> None:
    # If the tasks is not defined the app will crash
    if view.tasks is None:
        raise ValueError("The tasks are not defined.")
    # Use the lock to avoid two tasks accessing the attribute status_tasks
    # at the same time
    with view.tasks.lock:
        parent_view.status_tasks = [
            view.tasks[i].status.name.replace("_", " ").capitalize()
            for i in range(len(view.tasks))
        ]


def initialize_task(view: TaskView, main_view: "ExampleMainView", model: "Model") -> None:
    view.config.title = "Configuration"
    form.initialize_form_view_items(view.config, TaskConfigItems(model, view.config))
    view.status_tasks = [""] * 25
    view.progress.tasks = Tasks(
        tuple([Task(j, model) for j in range(len(view.status_tasks))]),
        is_sequential=False,
        print_to_std=True,
        name="Task",
        log_filepath=Path("taskview.msgspec_example.log"),
    )


def connect_task(view: TaskView) -> None:
    view.progress.progress += [update_task_status]
    view.progress.finished += [update_task_status]
    view.progress.canceled += [update_task_status]
