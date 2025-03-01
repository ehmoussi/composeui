from composeui.commontypes import AnyPydanticBaseModel
from composeui.model.basemodel import BaseModel
from composeui.store.pydanticstore import PydanticStore

from typing import Generic


class PydanticModel(BaseModel, Generic[AnyPydanticBaseModel]):
    def __init__(
        self, app_name: str, version: str, root: AnyPydanticBaseModel, is_debug: bool = False
    ) -> None:
        self._data = PydanticStore(root)
        super().__init__(app_name, version, self._data, is_debug=is_debug)

    @property
    def root(self) -> AnyPydanticBaseModel:
        return self._data.root
