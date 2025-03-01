"""Model using Msgspec store."""

from composeui.commontypes import AnyMsgspecStruct
from composeui.model.basemodel import BaseModel
from composeui.store.msgspecstore import MsgspecStore

from typing import Generic


class MsgspecModel(BaseModel, Generic[AnyMsgspecStruct]):
    """Model using the MsgspecStore using a Struct from Msgspec library to store data."""

    def __init__(
        self,
        app_name: str,
        version: str,
        root: AnyMsgspecStruct,
        is_debug: bool = False,
    ) -> None:
        self._data = MsgspecStore(root)
        super().__init__(app_name, version, self._data, is_debug=is_debug)

    @property
    def root(self) -> AnyMsgspecStruct:
        return self._data.root
