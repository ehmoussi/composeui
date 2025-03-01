r"""Tasks to open/save a file."""

from composeui.commontypes import AnyModel
from composeui.core.tasks.abstracttask import AbstractTask

from pathlib import Path
from typing import Generic, Optional


class _FileTask(AbstractTask, Generic[AnyModel]):
    r"""Task to open/save a file."""

    def __init__(self, model: AnyModel, filepath: Path) -> None:
        super().__init__(capture_exceptions_as_errors=True)
        self._model: AnyModel = model
        self._filepath: Path = filepath


class SaveTask(_FileTask[AnyModel]):
    r"""Task for saving the current datas into a file."""

    def _run(self) -> Optional[bool]:
        self._model.save(self._filepath)
        return None


class OpenTask(_FileTask[AnyModel]):
    r"""Task for opening the current datas into a file."""

    def _run(self) -> Optional[bool]:
        self._model.open_file(self._filepath)
        return None
