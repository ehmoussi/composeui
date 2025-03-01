r"""Main view."""

from composeui.mainview.views.mainview import MainView
from composeui.salomewrapper.core.views.salometree import SalomeTree
from composeui.salomewrapper.core.views.salomeview import SalomeView
from composeui.salomewrapper.core.views.salomeviews import SalomeViews

from dataclasses import dataclass, field


@dataclass(eq=False)
class SalomeMainView(MainView):
    module_name: str
    salome_tree: SalomeTree = field(init=False, default_factory=SalomeTree)
    salome_views: SalomeViews = field(init=False)
    central_view: SalomeView = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.create_central_views()

    def create_central_views(self) -> None:
        self.central_view = SalomeView(self.module_name, f"central_view_{self.module_name}")
        self.salome_views = SalomeViews(self.module_name)
