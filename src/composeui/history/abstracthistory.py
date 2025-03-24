from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class AbstractHistory(ABC):

    def get_capacity(self) -> int:
        """Get the maxumum number of actions of undo/redo to store."""
        return 100

    def open_history(self, filepath: Optional[Path]) -> None:
        """Open the history file if it exists and/or do the post process actions.

        Useful to create the sqlite tables or triggers for example.
        """
        return None

    def save_history(self, filepath: Path) -> None:
        """Save the history if the history is saved in an another file than the store."""
        return None

    def get_extension(self) -> Optional[str]:
        """Get the extension of the file where the history is saved.

        Return None if the history is not saved in another file.
        """
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
