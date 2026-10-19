"""Tasks run side by side in threads: `python -m examples.taskview --backend qt`.

Each task is a job (`MainView.jobs`): a function run in a thread, which never touches a
view. It returns the task's status, which its job emits on the main thread, where the
views show it: in the table, and counted by metrics, which once a run is over show how
each count changed since the last run; a step chart shows the tasks running over the
run's time, each count held until a task ends. The table is a section that collapses,
leaving only the metrics and the chart.
"""

from __future__ import annotations

import enum
import functools
import random
import time
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
    ChartView,
    ExpanderView,
    GroupFormView,
    HorizontalView,
    LabelRowIntInputView,
    LabelRowSliderView,
    LanguageMenu,
    MainView,
    MetricView,
    ProgressBarView,
    Series,
    T,
    TableView,
    child,
    define_view,
)

if TYPE_CHECKING:
    from composeui.core.jobs import Job

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
class ConfigInputView(LabelRowIntInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.minimum = 0


@define_view
class TaskConfigForm(GroupFormView):
    min_duration: ConfigInputView = child(ConfigInputView, label=T("Minimum Duration (s)"), value=3)
    max_duration: ConfigInputView = child(
        ConfigInputView, label=T("Maximum Duration (s)"), value=10
    )
    #: a slider: always a percentage, never empty
    failure_percentage: LabelRowSliderView = child(
        LabelRowSliderView, label=T("Percentage of Failure (%)"), value=20, maximum=100
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Configuration")
        self.add_validator(
            self._check_filled,
            *(row.editing_finished for row in self.durations),
            rows=self.durations,
        )
        self.add_validator(
            self._check_durations_ordered,
            self.min_duration.editing_finished,
            self.max_duration.editing_finished,
            rows=(self.min_duration, self.max_duration),
        )

    @property
    def durations(self) -> tuple[ConfigInputView, ...]:
        return (self.min_duration, self.max_duration)

    def _check_filled(self) -> Optional[str]:
        if any(row.value is None for row in self.durations):
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
class TaskMetrics(HorizontalView):
    """How many tasks of the run have each status."""

    running: MetricView = child(MetricView, label=T("Tasks running"), value="0")
    succeeded: MetricView = child(
        MetricView, label=T("Tasks succeeded"), value="0", delta_text=T("since the last run")
    )
    failed: MetricView = child(
        MetricView, label=T("Tasks failed"), value="0", delta_text=T("since the last run")
    )
    canceled: MetricView = child(
        MetricView, label=T("Tasks canceled"), value="0", delta_text=T("since the last run")
    )

    def metric(self, status: TaskStatus) -> MetricView:
        return {
            TaskStatus.RUNNING: self.running,
            TaskStatus.SUCCEEDED: self.succeeded,
            TaskStatus.FAILED: self.failed,
            TaskStatus.CANCELED: self.canceled,
        }[status]


@define_view
class TaskDetails(ExpanderView):
    """Each task of the run, behind the metrics: collapsed, only they show."""

    tasks: TableView = child(
        TableView, headers=[T("Task"), T("Duration (s)"), T("Status"), T("Error")]
    )


@define_view
class TaskMainView(MainView):
    app_title = T("Task View")
    extension = ".tasks"
    translations_dir = Path(__file__).parent / "locales" / "taskview"

    language_menu: LanguageMenu = Factory(LanguageMenu)

    config: TaskConfigForm = Factory(TaskConfigForm)
    buttons: RunButtons = Factory(RunButtons)
    progress: ProgressBarView = child(ProgressBarView, maximum=TASK_COUNT)
    metrics: TaskMetrics = Factory(TaskMetrics)
    running: ChartView = child(
        ChartView, title=T("Tasks running"), x_title=T("Time"), x_unit="s", height=240
    )
    details: TaskDetails = child(TaskDetails, title=T("Tasks"), is_expanded=True)
    #: the tasks of the last run
    _tasks: list[Task] = attrs.field(factory=list, init=False, metadata={OMIT: True})
    #: when the run started, by `time.monotonic`
    _started: float = attrs.field(default=0.0, init=False, metadata={OMIT: True})
    #: the run's tasks running, as (seconds since it started, count) at each change
    _running_counts: list[tuple[float, int]] = attrs.field(
        factory=list, init=False, metadata={OMIT: True}
    )
    #: how many tasks of the run before had each status, once it was over
    _last_counts: Optional[Counter[TaskStatus]] = attrs.field(
        default=None, init=False, metadata={OMIT: True}
    )

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
        minimum = self.config.min_duration.value or 0
        maximum = self.config.max_duration.value or 0
        failure_rate = self.config.failure_percentage.value / 100
        self._tasks = [
            # not cryptography: a task's duration only needs to vary
            Task(number, round(random.uniform(minimum, maximum), 1))  # noqa: S311
            for number in range(1, TASK_COUNT + 1)
        ]
        self._started = time.monotonic()
        self._running_counts = []
        for task in self._tasks:
            job = self.jobs.start(run_task, task.duration, failure_rate)
            job.finished.connect(functools.partial(self._report, task))
        self._show()

    def _report(self, task: Task, status: TaskStatus) -> None:
        """Show a task's outcome, on the main thread."""
        task.status = status
        self._show()

    def _show(self) -> None:
        error = self.tr("Random error: task {number} failed")
        self.details.tasks.rows = [
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
        for status in TaskStatus:
            self.metrics.metric(status).value = str(counts[status])
        self._show_running_counts(counts[TaskStatus.RUNNING])

    def _show_running_counts(self, running: int) -> None:
        """Add the count of tasks running now to the chart, held until it changes."""
        self._running_counts.append((time.monotonic() - self._started, running))
        self.running.series = [
            Series(
                name=self.tr(TaskStatus.RUNNING.value),
                x=[seconds for seconds, _ in self._running_counts],
                y=[count for _, count in self._running_counts],
                step=True,
                fill=True,
            )
        ]

    def _show_running(self, is_running: bool) -> None:
        self.config.is_enabled = not is_running
        self.buttons.run.is_enabled = not is_running
        self.buttons.cancel.is_enabled = is_running
        # compared once a run is over: a count is only final then
        counts = Counter(task.status for task in self._tasks)
        last = None if is_running else self._last_counts
        for status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELED):
            delta = None if last is None else counts[status] - last[status]
            self.metrics.metric(status).delta = delta
        if not is_running:
            self._last_counts = counts


def main() -> None:
    application.run(TaskMainView, default_backend=RendererType.WEB)


if __name__ == "__main__":
    main()
