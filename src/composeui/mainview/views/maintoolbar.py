from composeui.core.views.view import View
from composeui.mainview.views.toolbar import CheckableToolBar, EditToolBar, FileToolBar

from dataclasses import dataclass, field


@dataclass(eq=False)
class MainToolBar(View):
    file: FileToolBar = field(init=False, repr=False, default_factory=FileToolBar)
    edit: EditToolBar = field(init=False, repr=False, default_factory=EditToolBar)
    navigation: CheckableToolBar = field(
        init=False, repr=False, default_factory=CheckableToolBar
    )
