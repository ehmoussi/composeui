r"""
SalomeApp need to be used in an environment created using salome

- For windows:
SALOME-9.9.0\W64\Python\python3.exe SALOME-9.9.0\salome shell -- python -m venv .venvsalome

- For linux:
export LD_LIBRARY_PATH=/opt/salome/SALOME-9.9.0/BINARIES-CO7/Python/lib:$LD_LIBRARY_PATH
SALOME-9.9.0/BINARIES-CO7/Python/bin/python3 SALOME-9.9.0/salome shell -- python -m venv .venvsalome
"""  # noqa: E501

from composeui.apps.eventdrivenappmixin import EventDrivenAppMixin
from composeui.commontypes import AnyModel
from composeui.core import tools
from composeui.core.basesignal import SIGNAL_LOGGER
from composeui.mainview import toolbar
from composeui.salomewrapper.mainview.isalomemainview import ISalomeMainView
from composeui.store.salomehdfstore import SalomeHDFStore

import argparse
import inspect
import logging
import os
import platform
import shutil
import sys
from abc import abstractmethod
from pathlib import Path
from types import ModuleType
from typing import Any, Optional, TypeVar

V = TypeVar("V", bound=ISalomeMainView)


class SalomeModuleApp(EventDrivenAppMixin[V, AnyModel]):
    def __init__(self) -> None:
        super().__init__()
        self.is_testing = False
        self.app_module: Optional[ModuleType] = None
        try:
            self.app_module = sys.modules[self.__class__.__module__]
        except KeyError:
            child_file = None
        else:
            child_file = self.app_module.__file__
        if child_file is None:
            raise ValueError("Can't find the path to the current App")
        self.module_path = Path(
            Path(child_file).parent, "salome_module", self.get_module_name().upper()
        )
        self.is_study_closed = False

    def __init_subclass__(cls) -> None:
        """Force not having arguments in the __init__ method for the inherited class."""
        super().__init_subclass__()
        if cls.__base__ is not None:
            subclass_init = cls.__init__
            subclass_signature = inspect.signature(subclass_init)
            if len(subclass_signature.parameters) > 1:
                other_args = tuple(subclass_signature.parameters.keys())[1:]  # ignore self
                msg = (
                    f"The Salome module app `{cls.__name__}` have arguments `{other_args}` "
                    "in the `__init__` method which is forbidden. "
                    "Override the method `initialize_module` instead."
                )
                raise TypeError(msg)

    @abstractmethod
    def get_module_name(self) -> str: ...

    @abstractmethod
    def _create_model(self) -> None: ...

    @abstractmethod
    def _create_main_view(self) -> None: ...

    @property
    def model(self) -> AnyModel:
        assert (
            self._model is not None
        ), "The method '_create_model' failed to initialize the '_model' attribute"
        return self._model

    @property
    def main_view(self) -> V:
        assert (
            self._main_view is not None
        ), "The method '_create_main_view' failed to initialize the '_main_view' attribute"
        return self._main_view

    def initialize_module(self) -> None:
        self._create_model()
        self._create_main_view()
        if os.environ.get(self._get_log_signals_variable_name(), None) is not None:
            SIGNAL_LOGGER.setLevel(logging.DEBUG)
        self.initialize()
        self.connect()

    def activate_module(self) -> bool:
        if self._main_view is not None:
            if self.is_study_closed:
                self._main_view.create_central_views()
                self.disconnect()
                self.initialize()
                self.connect()
                self.is_study_closed = False
            tools.update_all_views(self._main_view)
            self._main_view.is_visible = True
            toolbar.display(view=self._main_view.toolbar.navigation, main_view=self._main_view)
            return True
        return False

    def deactivate_module(self) -> None:
        if self._main_view is not None:
            self._main_view.is_visible = False

    def close_study(self) -> None:
        assert self._model is not None
        # Use the new only if the close of the study is not an event triggered by the opening
        # of a salome study, to avoid to loose the opened study
        if all(
            not store.is_opening_study
            for store in self._model.stores
            if isinstance(store, SalomeHDFStore)
        ):
            self._model.new()
        else:
            for store in self._model.stores:
                if isinstance(store, SalomeHDFStore):
                    store.is_opening_study = False
        self.is_study_closed = True

    def run_module(
        self, salome_main_module: Any, context: Any, args: Optional[argparse.Namespace]
    ) -> None:
        if args is not None and args.debug and self._model is not None:
            self._model.is_debug = True
        # if --generate-module is in the arguments then the run only generate the files of the
        # module
        if args is not None and args.generate_module:
            if self.module_path.exists():
                response = (
                    input(
                        f"Overwrite the existing '{self.get_module_name()}' module (yes/[no]):"
                    )
                    .strip()
                    .lower()
                )
                if response != "yes":
                    return
            self._create_module()
        # If the module files are missing then raise an exception to ask the user to generate
        # the files using --generate-module argument
        elif not self.module_path.exists():
            msg = (
                f"Can't find {self.get_module_name()} module associated with the app. "
                "Create one using the '--generate-module' argument"
            )
            raise ValueError(msg)
        # otherwise add the module info to the current salome context so the module is
        # available when salome is open
        else:
            self._add_module_to_context(salome_main_module, context, args)

    def _add_module_to_context(
        self, salome_main_module: Any, context: Any, args: Optional[argparse.Namespace]
    ) -> None:
        """Add the module to the salome context."""
        module_name_upper = self.get_module_name().upper()
        module_name_lower = self.get_module_name().lower()
        module_root_dir = f"{module_name_upper}_ROOT_DIR"
        if args is not None and args.log_signals:
            context.setVariable(self._get_log_signals_variable_name(), "1", overwrite=True)
        context.setVariable(module_root_dir, str(self.module_path), overwrite=True)
        context.addToPath(str(Path(self.module_path, "bin", "salome")))
        context.addToPythonPath(str(Path(self.module_path, "bin", "salome")))
        if platform.system() == "Windows":
            context.addToPythonPath(str(Path(sys.prefix, "Lib", "site-packages")))
            context.setVariable(
                "PYTHONBIN", str(Path(sys.prefix, "Scripts", "python.exe")), overwrite=True
            )
            context.addToPath(str(Path(sys.prefix, "Scripts")))
        else:
            python_version = ".".join(map(str, sys.version_info[:2]))
            context.addToPythonPath(
                str(Path(sys.prefix, "lib", f"python{python_version}", "site-packages"))
            )
            context.setVariable(
                "PYTHONBIN", str(Path(sys.prefix, "bin", "python")), overwrite=True
            )
            context.addToPath(str(Path(sys.prefix, "bin")))
            # correct missing python lib in ld_library_path in 9.9.0
            context.addToLdLibraryPath(r"${PYTHON_ROOT_DIR}/lib")
        if hasattr(salome_main_module, "appendPath"):
            salome_main_module.appendPath("SALOME_MODULES", module_name_upper, separator=",")
            salome_main_module.appendPath(
                "SalomeAppConfig",
                str(Path(self.module_path, "share", "salome", "resources", module_name_lower)),
                separator=";",
            )
        else:
            context.appendVariable("SALOME_MODULES", module_name_upper, separator=",")
            context.appendVariable(
                "SalomeAppConfig",
                str(Path(self.module_path, "share", "salome", "resources", module_name_lower)),
                separator=";",
            )

    def _create_module(self) -> None:
        assert self.app_module is not None
        self._create_model()
        assert (
            self._model is not None
        ), "Failed to fill the '_model' attribute in the 'create_model' method"
        if self.module_path.exists():
            shutil.rmtree(self.module_path)
        module_python_path = Path(
            self.module_path, "bin", "salome", f"{self.get_module_name().upper()}GUI.py"
        )
        module_python_path.parent.mkdir(parents=True, exist_ok=True)
        module = self.__class__.__module__
        class_name = self.__class__.__name__
        self._write_module_gui_file(
            module_python_path, Path(sys.prefix, "Lib", "site-packages"), module, class_name
        )
        module_name_lower = self.get_module_name().lower()
        resources_path = Path(
            self.module_path, "share", "salome", "resources", module_name_lower
        )
        resources_path.mkdir(parents=True, exist_ok=True)
        self._write_salome_app_xml(
            Path(resources_path, "SalomeApp.xml"), self.get_module_name(), self._model.version
        )
        self._write_salome_app_xml(
            Path(resources_path, "SalomeAppSL.xml"),
            self.get_module_name(),
            self._model.version,
        )
        logging.basicConfig(level=logging.INFO)
        logging.info("Generate the module '%s' successfully.", self.get_module_name())

    def _get_log_signals_variable_name(self) -> str:
        """Get the name of the environement variable used for the log signals argument."""
        return f"{self.get_module_name().upper()}_LOG_SIGNALS"

    @staticmethod
    def _write_salome_app_xml(filepath: Path, module_name: str, version: str) -> None:
        module_name_upper = module_name.upper()
        with open(filepath, "w") as f:
            f.write(
                f"""<document>
    <section name="{module_name_upper}">
        <!-- Major module parameters -->
        <parameter name="name" value="{module_name}" />
        <parameter name="icon" value="{module_name_upper}.png" />
        <parameter name="library" value="SalomePyQtGUI" />
        <parameter name="version" value="{version}" />
    </section>
    <section name="resources">
        <!-- Module resources -->
        <parameter name="{module_name_upper}" value="%{module_name_upper}_ROOT_DIR%/share/salome/resources/cosmos" />
    </section>
</document>
"""  # noqa: E501
            )

    @staticmethod
    def _write_module_gui_file(
        filepath: Path, venv_path: Path, app_module: str, app_class_name: str
    ) -> None:
        with open(filepath, "w") as f:
            f.write(
                f"""import site

site.addsitedir(r"{venv_path}")

import composeui.core.icons.icons  # noqa: F401
from {app_module} import {app_class_name}

import logging
from typing import Optional

APP: Optional[{app_class_name}] = None


def initialize() -> None:
    global APP  # noqa: PLW0603
    APP = {app_class_name}()
    APP.initialize_module()


def activate() -> bool:
    if APP is not None:
        return APP.activate_module()
    else:
        logging.getLogger("salome").error(
            "Can't activate the the module because it has not been initialized"
        )
        return False


def deactivate() -> None:
    if APP is not None:
        APP.deactivate_module()
    else:
        logging.getLogger("salome").error(
            "Can't deactivate the module because it has not been initialized"
        )


def closeStudy() -> None:  # noqa: N802
    if APP is not None:
        APP.close_study()
    else:
        logging.getLogger("salome").error(
            "Can't close the study because the module has not been initialized"
        )
"""
            )
