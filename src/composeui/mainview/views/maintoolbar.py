from composeui.core.views.view import View
from composeui.mainview.views.toolbar import CheckableToolBar, FileToolBar

from dataclasses import dataclass, field


@dataclass(eq=False)
class MainToolBar(View):
    file: FileToolBar = field(init=False, default_factory=FileToolBar)
    navigation: CheckableToolBar = field(init=False, default_factory=CheckableToolBar)
