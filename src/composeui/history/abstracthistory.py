from abc import ABC, abstractmethod


class AbstractHistory(ABC):

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
