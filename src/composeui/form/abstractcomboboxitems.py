from composeui.model.basemodel import BaseModel

from abc import ABC, abstractmethod
from typing import Any, Tuple


class AbstractComboboxItems(ABC):
    # TODO: replace with a Generic
    def __init__(self, model: BaseModel) -> None:
        self._model: BaseModel = model

    @abstractmethod
    def row_count(self) -> int:
        r"""Get the number of rows from the model."""

    @abstractmethod
    def data(self, row: int, column: int) -> Any:
        r"""Get the data for the given row and column."""

    def values(self) -> Tuple[str, ...]:
        """Get all the values."""
        return tuple(str(self.data(i, 0)) for i in range(self.row_count()))
