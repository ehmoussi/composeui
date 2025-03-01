"""Model using Mashumaro store."""

from composeui.commontypes import AnyMashumaroDataClass
from composeui.model.basemodel import BaseModel
from composeui.store.mashumarostore import MashumaroStore

from typing import Generic


class MashumaroModel(BaseModel, Generic[AnyMashumaroDataClass]):
    def __init__(
        self, app_name: str, version: str, root: AnyMashumaroDataClass, is_debug: bool = False
    ) -> None:
        self._data = MashumaroStore(root)
        super().__init__(app_name, version, self._data, is_debug=is_debug)

    @property
    def root(self) -> AnyMashumaroDataClass:
        return self._data.root
