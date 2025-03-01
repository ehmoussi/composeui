from composeui.core.interfaces.iview import IView
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar, IFileToolBar

from dataclasses import dataclass, field


@dataclass(eq=False)
class IMainToolBar(IView):
    file: IFileToolBar = field(init=False, default_factory=IFileToolBar)
    navigation: ICheckableToolBar = field(init=False, default_factory=ICheckableToolBar)
