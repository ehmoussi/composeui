from composeui.core.views.iactionview import ActionView
from composeui.items.tree.itreeview import TreeGroupView
from composeui.mainview.views.imaintoolbar import MainToolBar
from composeui.mainview.views.imainview import MainView
from composeui.mainview.views.itoolbar import CheckableToolBar
from examples.treeview.lines import LinesItems

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
    lines_view: TreeGroupView[LinesItems] = field(
        init=False, default_factory=TreeGroupView[LinesItems]
    )


def initialize_navigation(view: NavigationToolBar, main_view: "ExampleMainView") -> None:
    view.lines.is_checked = True
    view.lines.text = "Lines"
    view.lines.visible_views = [main_view.lines_view]
