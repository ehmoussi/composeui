from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class AbstractHistory(ABC):

    def get_capacity(self) -> int:
        """Get the maxumum number of actions of undo/redo to store."""
        return 3  # 100

    def open_history(self, filepath: Optional[Path]) -> None:
        return None

    def save_history(self, filepath: Path) -> None:
        return None

    def get_extension(self) -> Optional[str]:
        return None

    @abstractmethod
    def undo(self) -> None:
        """Undo the last modification on the store."""

    @abstractmethod
    def redo(self) -> None:
        """Redo the last undo modification on the store."""

    @abstractmethod
    def start_recording(self) -> None:
        """Start recording the history."""

    @abstractmethod
    def stop_recording(self) -> None:
        """Stop recording the history."""
