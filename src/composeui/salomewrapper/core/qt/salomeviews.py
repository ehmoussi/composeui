"""Base views of Salome"""

from composeui.core.qt.view import View
from composeui.salomewrapper.core.isalomeviews import ISalomeViews
from composeui.salomewrapper.core.qt.occview import OCCView

from dataclasses import InitVar, dataclass, field


@dataclass(eq=False)
class SalomeViews(View, ISalomeViews):

    main_id: InitVar[int]
    occ_view: OCCView = field(init=False)

    def __post_init__(self, main_id: int) -> None:
        super().__post_init__()
        self.view = None
        self.occ_view = OCCView(self.module_name, view_type="OCCViewer", main_id=main_id)
