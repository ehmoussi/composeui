from composeui.core.views.iactionview import ActionView
from composeui.items.linkedtable.ilinkedtableview import LinkedTableView
from composeui.mainview.views.imaintoolbar import MainToolBar
from composeui.mainview.views.imainview import MainView
from composeui.mainview.views.itoolbar import CheckableToolBar
from examples.linkedtableview.sqlite.lines import LinesItems, PointsItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class NavigationToolBar(CheckableToolBar):
    lines: ActionView = field(init=False, default_factory=ActionView)


@dataclass(eq=False)
class ExampleMainToolBar(MainToolBar):
    navigation: NavigationToolBar = field(init=False, default_factory=NavigationToolBar)


@dataclass(eq=False)
class ExampleMainView(MainView):
    toolbar: ExampleMainToolBar = field(init=False, default_factory=ExampleMainToolBar)
    lines: LinkedTableView[LinesItems, PointsItems] = field(
        init=False, default_factory=LinkedTableView[LinesItems, PointsItems]
    )
    extension_study = ".example"


def initialize_navigation(view: NavigationToolBar, main_view: "ExampleMainView") -> None:
    view.lines.is_checked = True
    view.lines.text = "Lines"
    view.lines.visible_views = [main_view.lines]
