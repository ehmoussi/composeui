from composeui import get_version
from composeui.model.djangoormmodel import DjangoORMModel
from examples.probamodelapp.variables.variablesquery import VariablesQuery
from pathlib import Path


class Model(DjangoORMModel):
    def __init__(self, is_debug: bool = False) -> None:
        base_dir = Path(__file__).resolve().parent
        super().__init__(
            "ProbaModel",
            get_version("composeui"),
            filepath=base_dir / "db.sqlite3",
            is_debug=is_debug,
        )
        self.variables_query = VariablesQuery(self._django_store)
