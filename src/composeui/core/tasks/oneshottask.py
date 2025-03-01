r"""Task."""

from composeui.core.tasks.abstracttask import AbstractTask

from typing import Callable, Optional


class OneShotTask(AbstractTask):
    r"""Task running the function given in argument."""

    def __init__(self, task_function: Callable[..., Optional[bool]]) -> None:
        super().__init__(capture_exceptions_as_errors=True)
        self._task_function = task_function

    def _run(self) -> Optional[bool]:
        return self._task_function()
