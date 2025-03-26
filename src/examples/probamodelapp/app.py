from composeui import get_version
from composeui.apps.djangoapp import DjangoApp
from composeui.model.djangoormmodel import DjangoORMModel


import dotenv

import os
from pathlib import Path

dotenv.load_dotenv()


class ProbaModelApp(DjangoApp):

    def __init__(self, is_debug: bool = True) -> None:
        base_dir = Path(__file__).resolve().parent
        super().__init__(
            DjangoORMModel(
                "ProbaModel", get_version("composeui"), filepath=base_dir / "db.sqlite3"
            ),
            base_dir=base_dir,
            root_urlconf="examples.probamodelapp.urls",
            secret_key=os.environ.get("SECRET_KEY", ""),
            is_debug=is_debug,
            allowed_hosts=["*"],
            installed_apps=[
                "examples.probamodelapp.variables.apps.VariablesConfig",
            ],
        )
