from composeui.core.views.iactionview import IActionView
from composeui.items.linkedtable.ilinkedtableview import ILinkedTableView
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar
from examples.linkedtableview.sqlite.lines import LinesItems, PointsItems

from dataclasses import dataclass, field


@dataclass(eq=False)
class INavigationToolBar(ICheckableToolBar):
    lines: IActionView = field(init=False, default_factory=IActionView)


@dataclass(eq=False)
class IExampleMainToolBar(IMainToolBar):
    navigation: INavigationToolBar = field(init=False, default_factory=INavigationToolBar)


@dataclass(eq=False)
class IExampleMainView(IMainView):
    toolbar: IExampleMainToolBar = field(init=False, default_factory=IExampleMainToolBar)
    lines: ILinkedTableView[LinesItems, PointsItems] = field(
        init=False, default_factory=ILinkedTableView[LinesItems, PointsItems]
    )
    extension_study = ".example"


def initialize_navigation(view: INavigationToolBar, main_view: "IExampleMainView") -> None:
    view.lines.is_checked = True
    view.lines.text = "Lines"
    view.lines.visible_views = [main_view.lines]
