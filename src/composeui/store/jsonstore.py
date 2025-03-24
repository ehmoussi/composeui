"""Data managing state using mashumaro."""

from composeui.history.abstracthistory import AbstractHistory
from composeui.history.jsonhistory import JsonHistory
from composeui.store.abstractstore import AbstractStore

from abc import abstractmethod
from pathlib import Path
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


class JsonStore(AbstractStore, Generic[T]):
    def __init__(self, root: T) -> None:
        self.root = root
        self._is_debug = False
        self._history = JsonHistory(self)

    def get_extension(self) -> str:
        return ".json"

    def get_history(self) -> Optional[AbstractHistory]:
        return self._history

    def set_debug_mode(self, is_debug: bool) -> None:
        self._is_debug = is_debug

    @abstractmethod
    def clear_study(self) -> None:
        """Clear all the data."""
        self._history.clear_history()

    def new_study(self) -> None:
        """Create a new study."""
        self.clear_study()

    def save_study(self, filepath: Path) -> None:
        """Save the current study into a json file."""
        with open(filepath, "w") as f:
            f.write(self.to_json())

    def open_study(self, filepath: Path) -> None:
        """Save the current study into a json file."""
        with open(filepath) as f:
            self.root = self.from_json(f.read())

    @abstractmethod
    def from_json(self, json_data: str) -> T: ...

    @abstractmethod
    def to_json(self) -> str: ...
