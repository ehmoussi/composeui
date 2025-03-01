"""App for the example VTKView."""

from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.mashumaromodel import MashumaroModel
from composeui.vtk.ivtkview import VTKPickType
from examples.vtkview.example import (  # initialize_vtk_view,
    ExampleMainView,
    connect_vtk_example,
    initialize_vtk_example,
)

from mashumaro.mixins.json import DataClassJSONMixin
from typing_extensions import TypeAlias

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class VTKConfig(DataClassJSONMixin):
    vtk_filepath: str = ""
    vtk_fields: List[str] = field(default_factory=list)
    current_vtk_field: Optional[str] = None
    is_edge_visible: bool = False
    edge_width: float = 1.0
    is_warp_active: bool = False
    warp_scale_factor: float = 1.0
    pick_type: VTKPickType = VTKPickType.CELL


Model: TypeAlias = MashumaroModel[VTKConfig]


class VTKViewApp(QtBaseApp[ExampleMainView, Model]):
    def __init__(self, main_view: ExampleMainView) -> None:
        super().__init__(
            MashumaroModel("example", get_version("composeui"), VTKConfig()),
            main_view,
        )

    def initialize_app(self) -> None:
        initialize_vtk_example(self.main_view.vtk_example, self.model)

    def connect_app(self) -> None:
        connect_vtk_example(self.main_view.vtk_example)
