r"""View for a worker."""

from composeui.core.interfaces.iworkerview import IWorkerView
from composeui.core.qt.qtview import QtView
from composeui.core.qt.widgets.worker import Worker
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.core.tasks.tasks import Tasks

from dataclasses import dataclass, field
from typing import Optional, TypeVar, cast

T = TypeVar("T", bound=AbstractTask)


@dataclass(eq=False)
class QtWorkerView(QtView, IWorkerView[T]):
    r"""View for the worker."""

    worker: Worker = field(init=False, repr=False, default_factory=Worker)

    def __post_init__(self) -> None:
        super().__post_init__()
        # assign signals
        self.progress.add_qt_signals((self.worker, self.worker.progress))
        self.finished.add_qt_signals((self.worker, self.worker.finished))
        self.canceled.add_qt_signals((self.worker, self.worker.canceled))

    @property  # type: ignore[misc]
    def tasks(self) -> Optional[Tasks[T]]:
        return cast(Optional[Tasks[T]], self.worker.tasks)

    @tasks.setter
    def tasks(self, tasks: Optional[Tasks[T]]) -> None:
        self.worker.tasks = tasks

    def run(self) -> None:
        r"""Run the tasks."""
        self.worker.run()

    def cancel(self) -> None:
        r"""Cancel the tasks."""
        self.worker.cancel()
