from composeui.apps.djangoapp import DjangoApp
from examples.probamodelapp.model import Model
import dotenv

import os
from pathlib import Path


dotenv.load_dotenv()


class ProbaModelApp(DjangoApp):

    def __init__(self, is_debug: bool = True) -> None:
        base_dir = Path(__file__).parent.resolve()
        print(base_dir / "templates")
        super().__init__(
            Model(is_debug=is_debug),
            base_dir=base_dir,
            root_urlconf="examples.probamodelapp.urls",
            secret_key=os.environ.get("SECRET_KEY", ""),
            is_debug=is_debug,
            allowed_hosts=["*"],
            template_dirs=[Path(base_dir, "templates")],
            installed_apps=[
                "examples.probamodelapp.variables",
            ],
        )


app = ProbaModelApp(is_debug=True)
