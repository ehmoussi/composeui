from abc import ABC, abstractmethod
from pathlib import Path


class AbstractStore(ABC):

    @abstractmethod
    def get_extension(self) -> str:
        """Get the extension of the store.

        For example, for sqlite: '.sqlite'
        """

    @abstractmethod
    def set_debug_mode(self, is_debug: bool) -> None:
        """Set the status of the debug mode."""

    @abstractmethod
    def clear_study(self) -> None:
        """Clear all the data."""

    @abstractmethod
    def new_study(self) -> None:
        """Create a new study."""

    @abstractmethod
    def save_study(self, filepath: Path) -> None:
        """Save the current study using the specific format into the tar file."""

    @abstractmethod
    def open_study(self, filepath: Path) -> None:
        """Open the current study from the tar file using the specific format.

        Return the list of relative path to the files specific to the format.
        The path need to be relative to the tar container.
        """

    @abstractmethod
    def undo(self) -> None:
        """Undo the last modification on the store."""

    @abstractmethod
    def redo(self) -> None:
        """Redo the last undo modification on the store."""

    @abstractmethod
    def activate_history(self) -> None:
        """Activate the history."""

    @abstractmethod
    def deactivate_history(self) -> None:
        """Deactivate the history."""


class DataReadError(Exception):
    def __init__(self, filepath: Path) -> None:
        msg = (
            f"Invalid or corrupted file '{filepath}' encountered. "
            "Please ensure the file is in the expected format."
        )
        super().__init__(msg)
