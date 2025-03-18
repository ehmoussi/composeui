from composeui.core.views.actionview import ActionView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.toolbar import CheckableToolBar
from examples.network.llm import LLMView

from dataclasses import dataclass, field


@dataclass(eq=False)
class NavigationToolBar(CheckableToolBar):
    llm: ActionView = field(init=False, repr=False, default_factory=ActionView)


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
    llm: LLMView = field(init=False, repr=False, default_factory=LLMView)


def initialize_navigation(*, view: NavigationToolBar) -> None:
    view.llm.text = "LLM"
    view.llm.is_checked = True
