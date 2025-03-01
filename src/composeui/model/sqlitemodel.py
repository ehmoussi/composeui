"""Model using Sqlite store."""

from composeui.model.basemodel import BaseModel
from composeui.store.sqlitestore import SqliteStore

from pathlib import Path
from typing import Optional


class SqliteModel(BaseModel):
    def __init__(
        self,
        app_name: str,
        version: str,
        is_debug: bool = False,
        filepath: Optional[Path] = None,
        capacity: int = 20,
    ) -> None:
        self._data = SqliteStore(filepath, capacity)
        super().__init__(app_name, version, self._data, is_debug=is_debug)

    @property
    def sqlite_store(self) -> SqliteStore:
        return self._data
