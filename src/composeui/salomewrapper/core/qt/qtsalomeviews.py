"""Base views of Salome"""

from composeui.core.qt.qtview import QtView
from composeui.salomewrapper.core.qt.qtoccview import QtOCCView
from composeui.salomewrapper.core.views.salomeviews import SalomeViews

from dataclasses import InitVar, dataclass, field


@dataclass(eq=False)
class QtSalomeViews(QtView, SalomeViews):

    main_id: InitVar[int]
    occ_view: QtOCCView = field(init=False, repr=False)

    def __post_init__(self, main_id: int) -> None:
        super().__post_init__()
        self.view = None
        self.occ_view = QtOCCView(self.module_name, view_type="OCCViewer", main_id=main_id)
