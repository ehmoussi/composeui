r"""Main view."""

from composeui.mainview.interfaces.imainview import IMainView
from composeui.salomewrapper.core.isalometree import ISalomeTree
from composeui.salomewrapper.core.isalomeview import ISalomeView
from composeui.salomewrapper.core.isalomeviews import ISalomeViews

from dataclasses import dataclass, field


@dataclass(eq=False)
class ISalomeMainView(IMainView):
    module_name: str
    salome_tree: ISalomeTree = field(init=False, default_factory=ISalomeTree)
    salome_views: ISalomeViews = field(init=False)
    central_view: ISalomeView = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.create_central_views()

    def create_central_views(self) -> None:
        self.central_view = ISalomeView(self.module_name, f"central_view_{self.module_name}")
        self.salome_views = ISalomeViews(self.module_name)
