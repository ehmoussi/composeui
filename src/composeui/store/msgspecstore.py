from composeui.commontypes import AnyMsgspecStruct
from composeui.store.abstractstore import AbstractStore

import msgspec

from pathlib import Path
from typing import Generic


class MsgspecStore(AbstractStore, Generic[AnyMsgspecStruct]):
    def __init__(self, root: AnyMsgspecStruct) -> None:
        # - The root is a msgspec struct that contains all the data in the study
        # only the root is used to store the data in the study.
        # - The root need to have default values otherwise this class need to be override
        # to manage the clear of the data
        # - Creating another struct outside of root will be not used for saving the data
        # the implementation of the saving and opening and clearing of the data is let
        # to be implemented in the child classes if really needed
        self.root = root
        self._is_debug = False

    def get_extension(self) -> str:
        return ".json"

    def set_debug_mode(self, is_debug: bool) -> None:
        self._is_debug = is_debug

    def clear_study(self) -> None:
        self.root = type(self.root)()

    def new_study(self) -> None:
        self.clear_study()

    def save_study(self, filepath: Path) -> None:
        """Save the current study into a msgpack file."""
        with open(filepath, "wb") as f:
            encoder = msgspec.msgpack.Encoder()
            f.write(encoder.encode(self.root))

    def open_study(self, filepath: Path) -> None:
        """Save the current study into a msgpack file."""
        with open(filepath, "rb") as f:
            decoder = msgspec.msgpack.Decoder(type(self.root))
            self.root = decoder.decode(f.read())

    def undo(self) -> None:
        """Undo the last modification on the store."""

    def redo(self) -> None:
        """Redo the last undo modification on the store."""

    def activate_history(self) -> None:
        """Activate the history."""

    def deactivate_history(self) -> None:
        """Deactivate the history."""
