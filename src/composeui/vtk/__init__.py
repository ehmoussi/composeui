from composeui.vtk.ivtkview import VTKPickType, VTKView


def initialize_vtk_view(view: VTKView) -> bool:
    """Initialize the vtk view."""
    view.vtk_ugrid = None
    view.vtk_scalar_name = None
    view.is_edge_visible = False
    view.edge_width = 1.0
    view.is_warp_active = False
    view.warp_scale_factor = 1.0
    view.pick_type = VTKPickType.CELL
    view.picker_tolerance = 5e-3
    view.last_picked_cell_id = -1
    view.picked_cell_color = (0.3, 0.6, 1.0)
    view.last_picked_point_id = -1
    view.picked_point_color = (1.0, 0.0, 0.0)
    view.pick_point_sphere_scale_factor = 0.003
    view.opacity_after_picked = 0.1
    view.toolbar_information_text = "Use Shift key to pick a cell/point"
    return False


def connect_vtk_view(view: VTKView) -> bool:
    view.reset_camera_clicked = [view.reset_camera]
    return False
