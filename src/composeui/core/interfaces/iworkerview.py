from composeui.core.basesignal import BaseSignal
from composeui.core.interfaces.iview import IView
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.core.tasks.tasks import Tasks

import concurrent.futures
from dataclasses import dataclass, field
from typing import Generic, Optional, TypeVar

T = TypeVar("T", bound=AbstractTask)


@dataclass(eq=False)
class IWorkerView(IView, Generic[T]):
    tasks: Optional[Tasks[T]] = field(init=False, default=None)
    progress: BaseSignal = field(init=False, default=BaseSignal())
    finished: BaseSignal = field(init=False, default=BaseSignal())
    canceled: BaseSignal = field(init=False, default=BaseSignal())

    def run(self) -> None:
        """Run the tasks using python threads."""
        if self.tasks is not None:
            if self.tasks.is_sequential:
                self.tasks.run()
                self.tasks._logger.debug(  # noqa: SLF001
                    "Don't forget to call 'finished' from '%s' to emulate the whole process",
                    type(self).__name__,
                )
                # self.finished()
            else:
                pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
                for task in self.tasks:
                    pool.submit(task.run)
                    # future = pool.submit(task.run)
                    # future.add_done_callback(self._finished)
                # pool.shutdown()
                self.tasks._logger.debug(  # noqa: SLF001
                    "Don't forget to call 'finished' from '%s' to emulate the whole process",
                    type(self).__name__,
                )
                return None
        else:
            return None

    # def _finished(self, _: concurrent.futures.Future[bool]) -> None:
    #     if self.tasks is not None:
    #         with self.tasks.lock:
    #             if not self.tasks.is_running:
    #                 self.finished()

    def cancel(self) -> None:
        """Cancel the tasks."""
        if self.tasks is not None:
            return self.tasks.cancel()
        else:
            return None
