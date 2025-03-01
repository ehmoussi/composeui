from composeui.core.views.iactionview import IActionView
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar
from examples.asyncview.filereader import IFileReaderView

from dataclasses import dataclass, field


@dataclass(eq=False)
class INavigationToolBar(ICheckableToolBar):
    file_reader: IActionView = field(init=False, default_factory=IActionView)


@dataclass(eq=False)
class IExampleMainToolBar(IMainToolBar):
    navigation: INavigationToolBar = field(init=False, default_factory=INavigationToolBar)


@dataclass(eq=False)
class IExampleMainView(IMainView):
    toolbar: IExampleMainToolBar = field(init=False, default_factory=IExampleMainToolBar)
    file_reader: IFileReaderView = field(init=False, default_factory=IFileReaderView)


def initialize_navigation(*, view: INavigationToolBar) -> None:
    view.file_reader.text = "File Reader"
