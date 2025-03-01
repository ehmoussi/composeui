"""Model using SqlAlchemyData."""

from composeui.model.basemodel import BaseModel
from composeui.store.sqlalchemystore import SqlAlchemyStore

from sqlalchemy.orm import Session

import typing

if typing.TYPE_CHECKING:
    from sqlalchemy import Engine


class SqlAlchemyModel(BaseModel):
    def __init__(self, app_name: str, version: str, is_debug: bool = False) -> None:
        self._data = SqlAlchemyStore()
        super().__init__(app_name, version, self._data, is_debug=is_debug)

    def get_session(self) -> Session:
        return self._data.get_session()

    def get_engine(self) -> "Engine":
        return self._data.get_engine()
