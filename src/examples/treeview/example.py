from composeui.core.interfaces.iactionview import IActionView
from composeui.items.tree.itreeview import ITreeGroupView
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar
from examples.treeview.lines import LinesItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class INavigationToolBar(ICheckableToolBar):
    lines: IActionView = field(init=False, default_factory=IActionView)


@dataclass(eq=False)
class IExampleToolBar(IMainToolBar):
    navigation: INavigationToolBar = field(init=False, default_factory=INavigationToolBar)


@dataclass(eq=False)
class IExampleMainView(IMainView):
    toolbar: IExampleToolBar = field(init=False, default_factory=IExampleToolBar)
    lines_view: ITreeGroupView[LinesItems] = field(
        init=False, default_factory=ITreeGroupView[LinesItems]
    )


def initialize_navigation(view: INavigationToolBar, main_view: "IExampleMainView") -> None:
    view.lines.is_checked = True
    view.lines.text = "Lines"
    view.lines.visible_views = [main_view.lines_view]
