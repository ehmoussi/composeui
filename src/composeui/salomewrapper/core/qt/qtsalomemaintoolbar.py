from composeui.core.qt.qtview import QtView
from composeui.mainview.views.itoolbar import CheckableToolBar, ToolBar
from composeui.salomewrapper.mainview.qt.qtsalometoolbar import (
    CheckableSalomeToolBar,
    QtSalomeToolBar,
)

from qtpy.QtWidgets import QMainWindow

from dataclasses import dataclass, fields


@dataclass(eq=False)
class QtSalomeMainToolBar(QtView):

    module_name: str
    main_view: QMainWindow

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = None
        self.add_toolbars()

    def add_toolbars(self) -> None:
        for toolbar_field in fields(self):
            itoolbar = getattr(self, toolbar_field.name)
            # ICheckableToolBar must be first because it is also an IToolBar.
            if isinstance(itoolbar, CheckableToolBar):
                checkable_toolbar = CheckableSalomeToolBar.from_icheckable_toolbar(
                    self.module_name, toolbar_field.name, itoolbar
                )
                setattr(self, toolbar_field.name, checkable_toolbar)
                # self.main_view.addToolBar(checkable_toolbar.view)
                # self.main_view.addToolBarBreak()
            elif isinstance(itoolbar, ToolBar):
                toolbar = QtSalomeToolBar.from_itoolbar(
                    self.module_name, toolbar_field.name, itoolbar
                )
                setattr(self, toolbar_field.name, toolbar)
                # self.main_view.addToolBar(toolbar.view)
                # self.main_view.addToolBarBreak()
