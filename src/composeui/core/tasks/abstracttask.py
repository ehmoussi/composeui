r"""Abstract task to run in another thread."""

import logging
import traceback
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional


class TaskStatus(Enum):
    NOT_STARTED = 0
    RUNNING = 1
    SUCCESS = 3
    FAILED = 4
    CANCELED = 5
    WARNING = 6


class AbstractTask(ABC):
    r"""Definition of a task to run in another thread."""

    def __init__(self, capture_exceptions_as_errors: bool = False) -> None:
        self._status: TaskStatus = TaskStatus.NOT_STARTED
        self.error_message: str = ""
        self.warning_message: str = ""
        self._capture_exceptions_as_errors: bool = capture_exceptions_as_errors
        self._logger: logging.Logger = logging.getLogger(__name__)
        self._is_debug: bool = False
        self.is_canceled: bool = False

    @property
    def status(self) -> TaskStatus:
        return self._status

    @property
    def is_finished(self) -> bool:
        r"""Check if the task is finished from running."""
        return self._status in (
            TaskStatus.SUCCESS,
            TaskStatus.FAILED,
            TaskStatus.CANCELED,
            TaskStatus.WARNING,
        )

    @property
    def is_debug(self) -> bool:
        return self._is_debug

    @is_debug.setter
    def is_debug(self, is_debug: bool) -> None:
        self._is_debug = is_debug
        self._logger.setLevel(logging.DEBUG)

    def clear_status(self) -> None:
        r"""Clear the status of the task."""
        self._status = TaskStatus.NOT_STARTED

    def set_logger(self, logger: logging.Logger) -> None:
        self._logger = logger

    def run(self) -> bool:
        r"""Run the task, print errors and update the status."""
        if self._logger is None:
            raise ValueError("The run method can't be used without a logger for the task.")
        elif self.is_canceled:
            self._status = TaskStatus.CANCELED
            return False
        else:
            self.error_message = ""
            self.warning_message = ""
            self._status = TaskStatus.RUNNING
            try:
                is_success = self._run()
            except Exception as e:
                if self._capture_exceptions_as_errors:
                    self.error_message = str(e)
                    if self.is_debug:
                        self.error_message += "\n" + traceback.format_exc()
                elif self.is_debug:
                    self._logger.exception("")
                else:
                    self._logger.error(e)  # noqa: TRY400
                self._status = TaskStatus.FAILED
                is_success = False
            else:
                if self.error_message != "":
                    self._status = TaskStatus.FAILED
                elif self.warning_message != "":
                    self._status = TaskStatus.WARNING
                else:
                    self._status = TaskStatus.SUCCESS
                if is_success is None:
                    is_success = True
            return is_success

    @abstractmethod
    def _run(self) -> Optional[bool]:
        r"""Run the task."""
        ...
