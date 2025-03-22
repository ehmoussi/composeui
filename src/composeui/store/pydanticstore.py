from composeui.commontypes import AnyPydanticBaseModel
from composeui.store.abstractstore import AbstractStore

from pathlib import Path
from typing import Generic


class PydanticStore(AbstractStore, Generic[AnyPydanticBaseModel]):
    def __init__(self, root: AnyPydanticBaseModel) -> None:
        # - The root is a pydantic BaseModel that contains all the data in the study
        # only the root is used to store the data in the study.
        # - The root need to have default values otherwise this class need to be override
        # to manage the clear of the data
        # - Creating another BaseModel outside of root will be not used for saving the data
        # the implementation of the saving and opening and clearing of the data is let
        # to be implemented in the child classes if really needed
        self.root = root
        self._is_debug = False

    def get_extension(self) -> str:
        return ".json"

    def set_debug_mode(self, is_debug: bool) -> None:
        self._is_debug = is_debug

    def clear_study(self) -> None:
        try:
            self.root = self.root.model_construct()
        except AttributeError:  # old version
            self.root = self.root.construct()

    def new_study(self) -> None:
        self.clear_study()

    def save_study(self, filepath: Path) -> None:
        """Save the current study into a json file."""
        with open(filepath, "w") as f:
            try:
                f.write(self.root.model_dump_json())
            except AttributeError:  # old version
                f.write(self.root.json())

    def open_study(self, filepath: Path) -> None:
        """Save the current study into a json file."""
        with open(filepath) as f:
            try:
                self.root = self.root.model_validate_json(f.read())
            except AttributeError:  # old version
                self.root = self.root.parse_raw(f.read())

    def undo(self) -> None:
        """Undo the last modification on the store."""

    def redo(self) -> None:
        """Redo the last undo modification on the store."""

    def activate_history(self) -> None:
        """Activate the history."""

    def deactivate_history(self) -> None:
        """Deactivate the history."""
