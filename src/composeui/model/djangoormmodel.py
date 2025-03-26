from composeui.model.basemodel import BaseModel
from composeui.store.djangoormstore import DjangoORMStore

from pathlib import Path
from typing import Any, Dict, Optional


class DjangoORMModel(BaseModel):
    def __init__(
        self,
        app_name: str,
        version: str,
        engine: Optional[str] = None,
        filepath: Optional[Path] = None,
        is_debug: bool = False,
    ) -> None:
        self._django_orm = DjangoORMStore(engine=engine, filepath=filepath)
        super().__init__(
            app_name,
            version,
            self._django_orm,
            is_debug=is_debug,
        )

    @property
    def databases(self) -> Dict[str, Dict[str, Any]]:
        return self._django_orm.databases
