from composeui.core.views.iview import IView
from composeui.salomewrapper.core.views.ioccview import IOCCView

from dataclasses import dataclass, field


@dataclass(eq=False)
class ISalomeViews(IView):
    module_name: str
    occ_view: IOCCView = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.occ_view = IOCCView(self.module_name, "OCCViewer")
