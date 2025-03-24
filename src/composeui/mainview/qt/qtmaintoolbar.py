r"""View of the toolbar."""

from composeui.core.qt.qtview import QtView
from composeui.mainview.qt.qttoolbar import QtCheckableToolBar, QtToolBar
from composeui.mainview.views.toolbar import CheckableToolBar, ToolBar

from qtpy.QtWidgets import QMainWindow

from dataclasses import dataclass, fields


# Don't inherit from IMainToolBar because it contains only toolbars
# and it messes with the 2nd level of inheritance when trying to create toolbars.
@dataclass(eq=False)
class QtMainToolBar(QtView):
    r"""View of the main toolbar."""

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
                checkable_toolbar = QtCheckableToolBar.from_icheckable_toolbar(itoolbar)
                setattr(self, toolbar_field.name, checkable_toolbar)
                self.main_view.addToolBar(checkable_toolbar.view)
                self.main_view.addToolBarBreak()
            elif isinstance(itoolbar, ToolBar):
                toolbar = QtToolBar.from_itoolbar(itoolbar)
                setattr(self, toolbar_field.name, toolbar)
                self.main_view.addToolBar(toolbar.view)
                if toolbar_field.name != "file":
                    self.main_view.addToolBarBreak()
