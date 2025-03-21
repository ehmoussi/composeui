from composeui.core.views.actionview import ActionView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.toolbar import CheckableToolBar
from examples.asyncview.filereader import FileReaderView

from dataclasses import dataclass, field


@dataclass(eq=False)
class NavigationToolBar(CheckableToolBar):
    file_reader: ActionView = field(init=False, repr=False, default_factory=ActionView)


@dataclass(eq=False)
class ExampleMainToolBar(MainToolBar):
    navigation: NavigationToolBar = field(
        init=False, repr=False, default_factory=NavigationToolBar
    )


@dataclass(eq=False)
class ExampleMainView(MainView):
    toolbar: ExampleMainToolBar = field(
        init=False, repr=False, default_factory=ExampleMainToolBar
    )
    file_reader: FileReaderView = field(init=False, repr=False, default_factory=FileReaderView)


def initialize_navigation(*, view: NavigationToolBar) -> None:
    view.file_reader.text = "File Reader"
