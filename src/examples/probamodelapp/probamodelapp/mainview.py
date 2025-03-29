from dataclasses import dataclass, field
from composeui.core.views.actionview import ActionView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.toolbar import CheckableToolBar


@dataclass(eq=False)
class ProbaModelNavigation(CheckableToolBar):
    definition: ActionView = field(init=False, default_factory=ActionView)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.definition.text = "Definition"


@dataclass(eq=False)
class ProbaModelMainToolBar(MainToolBar):
    navigation: ProbaModelNavigation = field(init=False, default_factory=ProbaModelNavigation)


@dataclass(eq=False)
class ProbaModelMainView(MainView):
    title = "ProbaModelApp"
    toolbar: ProbaModelMainToolBar = field(init=False, default_factory=ProbaModelMainToolBar)
