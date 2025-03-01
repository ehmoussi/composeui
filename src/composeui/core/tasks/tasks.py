r"""Tasks to run in multiple threads or synchronously in one thread."""

from composeui.core.tasks.abstracttask import AbstractTask, TaskStatus

import logging
import threading
from itertools import islice
from pathlib import Path
from typing import Optional, Sequence, TypeVar, Union, overload

# from typing_extensions import TypeVarTuple, Unpack


T_co = TypeVar("T_co", bound=AbstractTask, covariant=True)
# TODO: Use TypeVarTuple to type each task explicitly when it is no more
# experimental and bound is available
# Ts = TypeVarTuple("Ts")


class Tasks(Sequence[T_co]):
    r"""Tuple of tasks."""

    def __init__(
        self,
        tasks: Sequence[T_co],
        is_sequential: bool = False,
        print_to_std: bool = False,
        name: str = "",
        log_filepath: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self._tasks = tasks
        self.lock = threading.Lock()
        self._is_sequential: bool = is_sequential or len(tasks) == 1
        self._log_filepath: Optional[Path] = log_filepath
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.INFO)
        if print_to_std:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(stream_handler)
        self._file_handler: Optional[logging.FileHandler] = None
        for task in tasks:
            task.set_logger(self._logger)

    @property
    def is_sequential(self) -> bool:
        r"""Check if the tasks must be run in sequential."""
        return self._is_sequential

    @property
    def log_filepath(self) -> Optional[Path]:
        return self._log_filepath

    @log_filepath.setter
    def log_filepath(self, filepath: Path) -> None:
        self._log_filepath = filepath

    @property
    def is_running(self) -> bool:
        r"""Check if at least one task is running."""
        return any(task.status == TaskStatus.RUNNING for task in self._tasks)

    @property
    def status(self) -> TaskStatus:
        r"""Get the status of all the tasks."""
        _status = TaskStatus.SUCCESS
        for task in self._tasks:
            if task.status == TaskStatus.FAILED:
                _status = TaskStatus.FAILED
                break
            if task.status == TaskStatus.WARNING:
                _status = TaskStatus.WARNING
                # can't break because a task may have failed
        return _status

    def count_finished(self) -> int:
        r"""Count the number of tasks finished."""
        return sum(task.is_finished for task in self._tasks)

    def run(self) -> bool:
        is_success = False
        for task in self._tasks:
            is_success = task.run()
            if not is_success:
                break
        return is_success

    def run_async(self) -> bool:
        r"""Run asynchronously the tasks."""
        raise NotImplementedError

    def cancel(self) -> None:
        for task in self._tasks:
            if task.status == TaskStatus.NOT_STARTED:
                task.is_canceled = True

    def clear(self) -> None:
        r"""Clear the log and the status."""
        self.clear_log()
        self.clear_status()

    def clear_status(self) -> None:
        r"""Clear the status of all the tasks."""
        for task in self._tasks:
            task.clear_status()

    def read_log(self, max_lines: int = -1) -> str:
        r"""Read the content of the log."""
        if self._log_filepath is not None and self._log_filepath.exists():
            with open(self._log_filepath) as f:
                if max_lines == -1:
                    return f.read()
                else:
                    lines_log = list(islice(f, 0, max_lines))
                    if len(lines_log) == max_lines:
                        lines_log.append("\n\n")
                        lines_log.append(
                            "The log can't be displayed completely. "
                            f"See **{self._log_filepath.name}** for more details."
                        )
                    return "".join(lines_log)
        return ""

    def clear_log(self) -> None:
        r"""Clear the log."""
        if self._log_filepath is not None:
            self.close_log()
            if self._log_filepath.exists():
                self._log_filepath.unlink()
            self._file_handler = logging.FileHandler(self._log_filepath, mode="a")
            self._logger.addHandler(self._file_handler)

    def close_log(self) -> None:
        r"""Close the log file."""
        if self._file_handler is not None:
            self._file_handler.close()
            self._logger.removeHandler(self._file_handler)
            self._file_handler = None

    def join_error_messages(self) -> str:
        r"""Join all the error messages of the tasks."""
        return self._join_messages(
            tuple(
                task.error_message
                for task in self._tasks
                if task.status == TaskStatus.FAILED and task.error_message != ""
            )
        )

    def join_warning_messages(self) -> str:
        r"""Join all the warning messages of the tasks."""
        return self._join_messages(
            tuple(task.warning_message for task in self._tasks if task.warning_message != "")
        )

    @staticmethod
    def _join_messages(messages: Sequence[str]) -> str:
        r"""Join the given messages."""
        if len(messages) == 0:
            return ""
        elif len(messages) == 1:
            return messages[0]
        else:
            return "\n".join(f"- {message}" for message in messages)

    @overload
    def __getitem__(self, index: int) -> T_co: ...
    @overload
    def __getitem__(self, index: slice) -> Sequence[T_co]: ...

    def __getitem__(self, index: Union[int, slice]) -> Union[T_co, Sequence[T_co]]:
        return self._tasks[index]

    def __len__(self) -> int:
        return len(self._tasks)
