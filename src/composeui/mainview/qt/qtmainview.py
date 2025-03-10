r"""Main view."""

from composeui.core.qt.qtfileview import QtFileView
from composeui.core.qt.qtview import QtView
from composeui.mainview.qt.qtmessageview import QtMessageView
from composeui.mainview.qt.qtprogresspopupview import QtProgressPopupView
from composeui.mainview.qt.widgets.mainwindow import MainWindow
from composeui.mainview.views.mainview import MainView
from composeui.network.qt.qtnetworkview import QtNetworkView

from qtpy import API
from qtpy.QtCore import QLocale
from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget

import signal
import sys
from dataclasses import InitVar, dataclass, field

if API == "pyside6":
    import composeui.core.icons.icons_pyside6
else:
    import composeui.core.icons.icons  # noqa: F401


# No check because the menu, toolbar and extension study are not implemented
# because it should be implemented in the inherited class
@dataclass(eq=False)
class QtMainView(QtView, MainView):
    r"""View of the main view."""

    view: MainWindow = field(init=False, repr=False)
    with_app: InitVar[bool] = True

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__()
        if with_app:
            # Define the qapplication
            self.qt_app = QApplication(sys.argv)
            # Set the locale to force "." as the unique decimal separator
            QLocale.setDefault(QLocale.c())
            if API == "pyside6":
                try:
                    from PySide6 import QtAsyncio
                except (ImportError, ModuleNotFoundError):
                    pass
                else:
                    self.qt_asyncio = QtAsyncio
        # Create the main window
        self.view = MainWindow()
        self.view.setMinimumSize(720, 480)
        # When interrupt quit
        signal.signal(signal.SIGINT, lambda *_: self.view.close())
        # central view
        self.central_view = QWidget()
        self.central_layout = QVBoxLayout()
        self.central_view.setLayout(self.central_layout)
        self.view.setCentralWidget(self.central_view)
        # message view
        self.message_view = QtMessageView(self.view)
        # file view
        self.file_view = QtFileView(self.view)
        # progress view
        self.progress_popup_view = QtProgressPopupView(self.view)
        # network view
        self.network_view = QtNetworkView()
        # assign signals
        self.save_before_exit.add_qt_signals((self.view, self.view.save_before_exit))
        # update_all signal is not a qt signal

    @property  # type: ignore[misc]
    def title(self) -> str:
        return str(self.view.windowTitle())

    @title.setter
    def title(self, title: str) -> None:
        self.view.setWindowTitle(title)

    @property  # type: ignore[misc]
    def closed(self) -> bool:
        return False

    @closed.setter
    def closed(self, closed: bool) -> None:
        if closed:
            self.view.close()

    @property  # type: ignore[misc]
    def force_close(self) -> bool:
        return bool(self.view.force_close)

    @force_close.setter
    def force_close(self, force_close: bool) -> None:
        self.view.force_close = force_close

    @property  # type: ignore[misc]
    def message_before_closing(self) -> str:
        return str(self.view.message_before_closing)

    @message_before_closing.setter
    def message_before_closing(self, message: str) -> None:
        self.view.message_before_closing = message
