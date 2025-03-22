"""Data managing state using mashumaro."""

from composeui.commontypes import AnyMashumaroDataClass
from composeui.store.abstractstore import AbstractStore

from pathlib import Path
from typing import Generic


class MashumaroStore(AbstractStore, Generic[AnyMashumaroDataClass]):
    def __init__(self, root: AnyMashumaroDataClass) -> None:
        self.root = root
        self._is_debug = False

    def get_extension(self) -> str:
        return ".json"

    def set_debug_mode(self, is_debug: bool) -> None:
        self._is_debug = is_debug

    def clear_study(self) -> None:
        """Clear all the data."""
        self.root = self.root.from_dict({})

    def new_study(self) -> None:
        """Create a new study."""
        self.clear_study()

    def save_study(self, filepath: Path) -> None:
        """Save the current study into a json file."""
        with open(filepath, "w") as f:
            f.write(str(self.root.to_json()))

    def open_study(self, filepath: Path) -> None:
        """Save the current study into a json file."""
        with open(filepath) as f:
            self.root = self.root.from_json(f.read())

    def undo(self) -> None:
        """Undo the last modification on the store."""

    def redo(self) -> None:
        """Redo the last undo modification on the store."""

    def activate_history(self) -> None:
        """Activate the history."""

    def deactivate_history(self) -> None:
        """Deactivate the history."""
