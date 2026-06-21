import signal
import sys
from collections.abc import Generator

from qtpy.QtWidgets import QApplication

from composeui.view import MainView, RendererType


class QtApplication:
    def __init__(self, main_view: MainView) -> None:
        self._main_view = main_view

    def render(self) -> None:
        self._main_view.is_visible = True
        self._main_view.render(RendererType.QT)

    def run(self) -> Generator[None]:
        app = QApplication(sys.argv)
        self.render()

        signal.signal(signal.SIGINT, signal.SIG_DFL)  # kill the program when Ctr+c
        sys.exit(app.exec())
