from __future__ import annotations

import signal
import sys
from typing import TYPE_CHECKING, TypeVar

from qtpy.QtWidgets import QApplication

from composeui.core.application import Application, ModelApplication
from composeui.core.view import RendererType

if TYPE_CHECKING:
    from collections.abc import Generator

    from composeui.core.model import Model
    from composeui.core.view import MainView


MainViewT = TypeVar("MainViewT", bound="MainView")
ModelT = TypeVar("ModelT", bound="Model")


class QtApplication(Application[MainViewT]):
    def run(self) -> Generator[None]:
        app = QApplication(sys.argv)
        self.render(RendererType.QT)
        signal.signal(signal.SIGINT, signal.SIG_DFL)  # kill the program when Ctr+c
        sys.exit(app.exec())


class QtModelApplication(ModelApplication[MainViewT, ModelT]):
    def run(self) -> Generator[None]:
        app = QApplication(sys.argv)
        self.render(RendererType.QT)
        signal.signal(signal.SIGINT, signal.SIG_DFL)  # kill the program when Ctr+c
        sys.exit(app.exec())
