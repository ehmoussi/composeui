r"""Worker for long running task."""

from composeui.core.tasks.abstracttask import AbstractTask
from composeui.core.tasks.tasks import Tasks

from qtpy.QtCore import Signal  # type: ignore[attr-defined]
from qtpy.QtCore import Slot  # type: ignore[attr-defined]
from qtpy.QtCore import QObject, QRunnable, QThreadPool

import contextlib
from typing import Optional


class _RunnableEmmiter(QObject):
    r"""Object with a finished signal for a runnable."""

    finished = Signal()


class _TaskRunnable(QRunnable):
    def __init__(self, task: AbstractTask) -> None:
        self.emitter = _RunnableEmmiter()
        super().__init__()
        self._task = task
        self.setAutoDelete(True)

    def run(self) -> None:
        self._task.run()
        with contextlib.suppress(RuntimeError):
            self.emitter.finished.emit()


class Worker(QObject):
    r"""Run the tasks."""

    progress = Signal(int)
    finished = Signal()
    canceled = Signal()

    def __init__(self, tasks: Optional[Tasks[AbstractTask]] = None) -> None:
        super().__init__()
        self.tasks: Optional[Tasks[AbstractTask]] = tasks
        self._nb_runnables: int = 0

    @Slot()
    def _task_finished(self) -> None:
        r"""Check if all the tasks are finished therefore emit the finished signal."""
        if self.tasks is not None:
            nb_finished = self.tasks.count_finished()
            if self._nb_runnables > 1:
                self.progress.emit(nb_finished)
            if self.tasks.is_sequential and nb_finished < self._nb_runnables:
                thread_pool = QThreadPool.globalInstance()
                runnable = _TaskRunnable(self.tasks[nb_finished])
                runnable.emitter.finished.connect(self._task_finished)
                thread_pool.start(runnable)
            elif nb_finished == self._nb_runnables:
                self.tasks.close_log()
                self.finished.emit()

    def run(self) -> None:
        r"""Run all the tasks in multiple threads or in one if the tasks are sequential."""
        self._clear()
        if self.tasks is not None:
            thread_pool = QThreadPool.globalInstance()
            self._nb_runnables = len(self.tasks)
            if self.tasks.is_sequential:
                runnable = _TaskRunnable(self.tasks[0])
                runnable.emitter.finished.connect(self._task_finished)
                thread_pool.start(runnable)
            else:
                for task in self.tasks:
                    runnable = _TaskRunnable(task)
                    runnable.emitter.finished.connect(self._task_finished)
                    thread_pool.start(runnable)

    @Slot()
    def cancel(self, wait_done: bool = False) -> None:
        r"""Cancel the tasks which are not launched and wait or not for the others."""
        if self.tasks is not None:
            self.tasks.cancel()
            self.canceled.emit()
            if wait_done:
                thread_pool = QThreadPool.globalInstance()
                thread_pool.waitForDone()

    def deleteLater(self) -> None:  # noqa: N802
        self.cancel(wait_done=True)
        super().deleteLater()

    def _clear(self) -> None:
        r"""Clear the current runnables and finished indices."""
        self._nb_runnables = 0
