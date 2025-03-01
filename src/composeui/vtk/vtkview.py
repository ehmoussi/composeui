"""Interface to the VTK view."""

from composeui.core.basesignal import BaseSignal
from composeui.core.views.view import View

import enum
import typing
from dataclasses import dataclass, field
from typing import Optional, Tuple

if typing.TYPE_CHECKING:
    from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid


class VTKPickType(enum.IntEnum):
    CELL = enum.auto()
    POINT = enum.auto()

    def __str__(self) -> str:
        return self.name.capitalize()

    def __repr__(self) -> str:
        return self.name.capitalize()


@dataclass(eq=False)
class VTKView(View):
    vtk_ugrid: Optional["vtkUnstructuredGrid"] = field(init=False, default=None)
    vtk_scalar_name: Optional[str] = field(init=False, default=None)
    # edge configuration
    is_edge_visible: bool = field(init=False, default=False)
    edge_width: float = field(init=False, default=1.0)
    # warp configuration
    is_warp_active: bool = field(init=False, default=False)
    warp_scale_factor: float = field(init=False, default=1.0)
    # pick configuration
    pick_type: VTKPickType = field(init=False, default=VTKPickType.CELL)
    picker_tolerance: float = field(init=False, default=5e-3)
    # - pick cell
    last_picked_cell_id: int = field(init=False, default=-1)  # -1 means no pick
    picked_cell_color: Tuple[float, float, float] = field(
        init=False, default_factory=lambda: (0.3, 0.6, 1.0)
    )
    # - pick point
    last_picked_point_id: int = field(init=False, default=-1)  # -1 means no pick
    picked_point_color: Tuple[float, float, float] = field(
        init=False, default_factory=lambda: (1.0, 0.0, 0.0)
    )
    pick_point_sphere_scale_factor: float = field(init=False, default=0.003)
    opacity_after_picked: float = field(init=False, default=0.1)
    # others
    toolbar_information_text: str = field(
        init=False, default="Use Shift key to pick a cell/point"
    )
    # signals
    reset_camera_clicked: BaseSignal = field(init=False, default=BaseSignal())
    cell_picked: BaseSignal = field(init=False, default=BaseSignal())
    point_picked: BaseSignal = field(init=False, default=BaseSignal())

    def reset_camera(self) -> None: ...

    def render(self) -> None:
        self.last_picked_cell_id = -1
        self.last_picked_point_id = -1
