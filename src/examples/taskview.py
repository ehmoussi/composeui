"""Tasks run side by side in threads: `python -m examples.taskview --backend qt`.

Each task is a job (`MainView.jobs`): a function run in a thread, which never touches a
view. It returns the task's status, which its job emits on the main thread, where the
views show it. On the web, the page follows them through the progress bar, which fetches
itself while not full.
"""

import enum
import functools
import random
from collections import Counter
from pathlib import Path
from typing import Optional

import attrs
from attrs import Factory

from composeui.core import application
from composeui.core.jobs import Job
from composeui.core.registry import RendererType
from composeui.core.view import (
    OMIT,
    Align,
    ButtonVariant,
    ButtonView,
    GroupFormView,
    HorizontalView,
    LabelRowFloatInputView,
    LabelView,
    LanguageMenu,
    MainView,
    ProgressBarView,
    T,
    TableView,
    child,
    define_view,
)

#: the tasks a run starts, all at once
TASK_COUNT = 25


class TaskStatus(enum.Enum):
    RUNNING = T("Running")
    SUCCEEDED = T("Succeeded")
    FAILED = T("Failed")
    CANCELED = T("Canceled")


@attrs.define
class Task:
    number: int
    #: how long it works, in seconds
    duration: float
    status: TaskStatus = TaskStatus.RUNNING


def run_task(job: Job[TaskStatus], duration: float, failure_rate: float) -> TaskStatus:
    """Work for `duration` seconds, in the job's thread; then fail at `failure_rate`."""
    if not job.sleep(duration):
        return TaskStatus.CANCELED
    # not cryptography: a failure only needs to happen at random
    failed = random.random() < failure_rate  # noqa: S311
    return TaskStatus.FAILED if failed else TaskStatus.SUCCEEDED


@define_view
class ConfigInputView(LabelRowFloatInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.minimum = 0
        self.decimals = 0


@define_view
class TaskConfigForm(GroupFormView):
    min_duration: ConfigInputView = child(ConfigInputView, label=T("Minimum Duration (s)"), value=3)
    max_duration: ConfigInputView = child(
        ConfigInputView, label=T("Maximum Duration (s)"), value=10
    )
    failure_percentage: ConfigInputView = child(
        ConfigInputView, label=T("Percentage of Failure (%)"), value=20, maximum=100
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Configuration")
        self.add_validator(
            self._check_filled,
            *(row.editing_finished for row in self.rows),
            rows=self.rows,
        )
        self.add_validator(
            self._check_durations_ordered,
            self.min_duration.editing_finished,
            self.max_duration.editing_finished,
            rows=(self.min_duration, self.max_duration),
        )

    @property
    def rows(self) -> tuple[ConfigInputView, ...]:
        return (self.min_duration, self.max_duration, self.failure_percentage)

    def _check_filled(self) -> Optional[str]:
        if any(row.value is None for row in self.rows):
            return self.tr("Every value is needed")
        return None

    def _check_durations_ordered(self) -> Optional[str]:
        minimum, maximum = self.min_duration.value, self.max_duration.value
        if minimum is not None and maximum is not None and minimum > maximum:
            return self.tr("The minimum duration can't be greater than the maximum duration")
        return None


@define_view
class RunButtons(HorizontalView):
    align = Align.END
    run: ButtonView = child(ButtonView, text=T("Run"))
    cancel: ButtonView = child(
        ButtonView, text=T("Cancel"), variant=ButtonVariant.DANGER, is_enabled=False
    )


@define_view
class TaskMainView(MainView):
    app_title = T("Task View")
    extension = ".tasks"
    translations_dir = Path(__file__).parent / "locales" / "taskview"

    language_menu: LanguageMenu = Factory(LanguageMenu)

    config: TaskConfigForm = Factory(TaskConfigForm)
    buttons: RunButtons = Factory(RunButtons)
    # hidden until the first run: on the web, a bar not full polls the server
    progress: ProgressBarView = child(ProgressBarView, maximum=TASK_COUNT, is_visible=False)
    summary: LabelView = Factory(LabelView)
    tasks: TableView = child(
        TableView, headers=[T("Task"), T("Duration (s)"), T("Status"), T("Error")]
    )
    #: the tasks of the last run
    _tasks: list[Task] = attrs.field(factory=list, init=False, metadata={OMIT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.buttons.run.clicked.connect(self.start)
        self.buttons.cancel.clicked.connect(self.jobs.cancel)
        self.jobs.running_changed.connect(self._show_running)

    def start(self) -> None:
        """Start a run of `TASK_COUNT` tasks, each a job of its own."""
        if self.jobs.is_running:
            return
        self.config.validate()
        if self.config.log_view.log_message != "":
            self.status_bar.show_message(self.tr("Fix the configuration first"))
            return
        minimum = self.config.min_duration.value or 0.0
        maximum = self.config.max_duration.value or 0.0
        failure_rate = (self.config.failure_percentage.value or 0.0) / 100
        self._tasks = [
            # not cryptography: a task's duration only needs to vary
            Task(number, round(random.uniform(minimum, maximum), 1))  # noqa: S311
            for number in range(1, TASK_COUNT + 1)
        ]
        for task in self._tasks:
            job = self.jobs.start(run_task, task.duration, failure_rate)
            job.finished.connect(functools.partial(self._report, task))
        self.progress.is_visible = True
        self._show()

    def _report(self, task: Task, status: TaskStatus) -> None:
        """Show a task's outcome, on the main thread."""
        task.status = status
        self._show()

    def _show(self) -> None:
        error = self.tr("Random error: task {number} failed")
        self.tasks.rows = [
            [
                str(task.number),
                f"{task.duration:.1f}",
                self.tr(task.status.value),
                error.format(number=task.number) if task.status is TaskStatus.FAILED else "",
            ]
            for task in self._tasks
        ]
        counts = Counter(task.status for task in self._tasks)
        done = counts[TaskStatus.SUCCEEDED] + counts[TaskStatus.FAILED]
        self.progress.value = done + counts[TaskStatus.CANCELED]
        summary = self.tr(
            "{done} of {total} tasks done: {succeeded} succeeded, {failed} failed,"
            " {canceled} canceled"
        )
        self.summary.text = summary.format(
            done=done,
            total=len(self._tasks),
            succeeded=counts[TaskStatus.SUCCEEDED],
            failed=counts[TaskStatus.FAILED],
            canceled=counts[TaskStatus.CANCELED],
        )

    def _show_running(self, is_running: bool) -> None:
        self.config.is_enabled = not is_running
        self.buttons.run.is_enabled = not is_running
        self.buttons.cancel.is_enabled = is_running


def main() -> None:
    application.run(TaskMainView, default_backend=RendererType.WEB)


if __name__ == "__main__":
    main()
