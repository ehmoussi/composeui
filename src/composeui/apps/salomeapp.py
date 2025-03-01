r"""
SalomeApp need to be used in an environment created using salome

For windows:
...\SALOME-9.9.0\W64\Python\python3.exe ...\SALOME-9.9.0\salome shell -- python -m venv .venvsalome

"""  # noqa: E501

from composeui.apps.baseapp import BaseApp
from composeui.apps.salomemoduleapp import SalomeModuleApp

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from typing import Any, List


class SalomeApp(BaseApp):
    def __init__(
        self, modules: List[SalomeModuleApp[Any, Any]], is_testing: bool = False
    ) -> None:
        # initialize the variable before to use the "is_testing" property
        self._modules: List[SalomeModuleApp[Any, Any]] = modules
        super().__init__(is_testing)
        self._is_testing = is_testing
        self.salome_dir_path = Path(sys.base_prefix, "..", "..").resolve()
        self.is_study_closed = False
        # TODO: manage the opening of a study
        # self._parser.add_argument(
        #     "-f", metavar="FILE", help="Open the app with the FILE study", type=Path
        # )
        self._parser.add_argument(
            "--generate-module",
            help="Generate a salome module for the app.",
            action="store_true",
        )
        self._parser.add_argument(
            "--log-signals", help="Log all the emitted signals.", action="store_true"
        )

    @property
    def modules(self) -> List[SalomeModuleApp[Any, Any]]:
        return self._modules

    @property
    def is_testing(self) -> bool:
        return self._is_testing

    @is_testing.setter
    def is_testing(self, is_testing: bool) -> None:
        self._is_testing = is_testing
        for module in self._modules:
            module.is_testing = is_testing

    def run(self) -> None:
        super().run()
        salome_main_module = self._get_salome_main_module()
        context = salome_main_module.main([])
        for module in self._modules:
            module.run_module(salome_main_module, context, self._args)
        if self._args is None or not self._args.generate_module:
            if not self.is_testing:
                _, _, status = context.runSalome([])
                sys.exit(status)
            else:
                for module in self._modules:
                    module.initialize_module()
                    module.activate_module()

    def _get_salome_main_module(self) -> Any:
        """Import the salome file that is used to run Salome and return the imported module.

        The salome file is modified to remove the running of salome in the main function to
        return instead the salome context.
        The salome context can be used to add a new module before launching Salome.
        """
        salome_filepath = Path(self.salome_dir_path, "salome")
        if not salome_filepath.exists():
            msg = f"Can't find the file: '{salome_filepath}'"
            raise ValueError(msg)
        source_file_loader = ModifiedSourceLoader("salome_main", str(salome_filepath))
        spec = importlib.util.spec_from_loader("salome_main", source_file_loader)
        if spec is None or spec.loader is None:
            msg = f"Failed to read the file: '{salome_filepath}'"
            raise ValueError(msg)
        salome_main_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(salome_main_module)
        return salome_main_module


class ModifiedSourceLoader(importlib.machinery.SourceFileLoader):
    def get_data(self, path: str) -> bytes:
        # Read the original file content
        content = ""
        with open(path, encoding="latin1") as f:
            for line in f:
                if "context.runSalome" not in line:
                    content += line
                else:
                    content += "    return context\n"
        return content.encode("latin1")
