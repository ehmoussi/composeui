from composeui.core.views.actionview import ActionView
from composeui.items.tree.treeview import TreeGroupView
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.toolbar import CheckableToolBar
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
