"""Tasks run side by side in worker threads: `python -m examples.taskview --backend qt`.

The workers never touch a view: each hands its task's outcome to the main thread with
`call_on_main_thread`, which updates the views. On the web, the page follows them through
the progress bar, which fetches itself while not full.
"""

import enum
import functools
import random
import threading
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import attrs
from attrs import Factory

from composeui.core import application
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

if TYPE_CHECKING:
    from collections.abc import Callable

#: the tasks a run starts, all at once
TASK_COUNT = 25


class TaskStatus(enum.Enum):
    PENDING = T("Pending")
    RUNNING = T("Running")
    SUCCEEDED = T("Succeeded")
    FAILED = T("Failed")
    CANCELED = T("Canceled")


@attrs.define
class Task:
    number: int
    #: how long it works, in seconds
    duration: float
    status: TaskStatus = TaskStatus.PENDING

    @property
    def is_done(self) -> bool:
        return self.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELED)


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


@attrs.define
class _Run:
    """The tasks of one run, and the event telling its workers to stop."""

    tasks: list[Task]
    canceled: threading.Event = Factory(threading.Event)


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
    #: the run going on, None between runs; only ever read and changed on the main thread
    _run: Optional[_Run] = attrs.field(default=None, init=False, metadata={OMIT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.buttons.run.clicked.connect(self.start)
        self.buttons.cancel.clicked.connect(self.cancel)

    def start(self) -> None:
        """Start a run of `TASK_COUNT` tasks, each in a worker thread of its own."""
        if self._run is not None:
            return
        self.config.validate()
        if self.config.log_view.log_message != "":
            self.status_bar.show_message(self.tr("Fix the configuration first"))
            return
        minimum = self.config.min_duration.value or 0.0
        maximum = self.config.max_duration.value or 0.0
        failure_rate = (self.config.failure_percentage.value or 0.0) / 100
        tasks = [
            # not cryptography: a task's duration only needs to vary
            Task(number, round(random.uniform(minimum, maximum), 1))  # noqa: S311
            for number in range(1, TASK_COUNT + 1)
        ]
        self._run = run = _Run(tasks)
        self._show_running(is_running=True)
        self.progress.is_visible = True
        self._show(run)
        for index in range(len(tasks)):
            # daemons: closing the app doesn't wait for the tasks
            worker = threading.Thread(
                target=self._work, args=(run, index, failure_rate), daemon=True
            )
            worker.start()

    def cancel(self) -> None:
        """Stop the run's tasks still working; each reports itself canceled."""
        if self._run is not None:
            self._run.canceled.set()

    def _work(self, run: _Run, index: int, failure_rate: float) -> None:
        """Run a task on its worker thread: it waits its duration, then may fail."""
        self._on_main_thread(functools.partial(self._report, run, index, TaskStatus.RUNNING))
        if run.canceled.wait(run.tasks[index].duration):
            status = TaskStatus.CANCELED
        elif random.random() < failure_rate:  # noqa: S311
            status = TaskStatus.FAILED
        else:
            status = TaskStatus.SUCCEEDED
        self._on_main_thread(functools.partial(self._report, run, index, status))

    def _on_main_thread(self, callback: "Callable[[], None]") -> None:
        # a worker never sets a view: a toolkit's widgets belong to the main thread
        if self.renderer is None:
            callback()
        else:
            self.renderer.call_on_main_thread(callback)

    def _report(self, run: _Run, index: int, status: TaskStatus) -> None:
        """Show a task's new status, on the main thread; the run ends with its last task."""
        run.tasks[index] = attrs.evolve(run.tasks[index], status=status)
        self._show(run)
        if all(task.is_done for task in run.tasks):
            self._run = None
            self._show_running(is_running=False)

    def _show(self, run: _Run) -> None:
        error = self.tr("Random error: task {number} failed")
        self.tasks.rows = [
            [
                str(task.number),
                f"{task.duration:.1f}",
                self.tr(task.status.value),
                error.format(number=task.number) if task.status is TaskStatus.FAILED else "",
            ]
            for task in run.tasks
        ]
        counts = Counter(task.status for task in run.tasks)
        done = counts[TaskStatus.SUCCEEDED] + counts[TaskStatus.FAILED]
        self.progress.value = done + counts[TaskStatus.CANCELED]
        summary = self.tr(
            "{done} of {total} tasks done: {succeeded} succeeded, {failed} failed,"
            " {canceled} canceled"
        )
        self.summary.text = summary.format(
            done=done,
            total=len(run.tasks),
            succeeded=counts[TaskStatus.SUCCEEDED],
            failed=counts[TaskStatus.FAILED],
            canceled=counts[TaskStatus.CANCELED],
        )

    def _show_running(self, *, is_running: bool) -> None:
        self.config.is_enabled = not is_running
        self.buttons.run.is_enabled = not is_running
        self.buttons.cancel.is_enabled = is_running


def main() -> None:
    application.run(TaskMainView, default_backend=RendererType.WEB)


if __name__ == "__main__":
    main()
