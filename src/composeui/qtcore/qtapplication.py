"""The application classes of the Qt backend."""

from __future__ import annotations

import signal
import sys
from typing import TYPE_CHECKING, TypeVar

from qtpy.QtWidgets import QApplication

from composeui.core.application import Application, ModelApplication
from composeui.core.view import RendererType

if TYPE_CHECKING:
    from composeui.core.model import Model
    from composeui.core.view import MainView


MainViewT = TypeVar("MainViewT", bound="MainView")
ModelT = TypeVar("ModelT", bound="Model")


class QtApplication(Application[MainViewT]):
    """The Qt app: it shows the main view in a window."""

    def run(self) -> None:
        super().run()
        app = QApplication(sys.argv)
        self.render(RendererType.QT)
        signal.signal(signal.SIGINT, signal.SIG_DFL)  # kill the program when Ctr+c
        sys.exit(app.exec())


class QtModelApplication(ModelApplication[MainViewT, ModelT]):
    """The Qt app with a model, which it closes once the window is closed."""

    def run(self) -> None:
        super().run()
        app = QApplication(sys.argv)
        self.render(RendererType.QT)
        signal.signal(signal.SIGINT, signal.SIG_DFL)  # kill the program when Ctr+c
        try:
            code = app.exec()
        finally:
            self.model.close()
        sys.exit(code)


#: the backend's applications, for `composeui.core.application.run`
APPLICATION = QtApplication
MODEL_APPLICATION = QtModelApplication
