from composeui.core.views.view import View
from composeui.salomewrapper.core.views.occview import OCCView

from dataclasses import dataclass, field


@dataclass(eq=False)
class SalomeViews(View):
    module_name: str
    occ_view: OCCView = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.occ_view = OCCView(self.module_name, "OCCViewer")
