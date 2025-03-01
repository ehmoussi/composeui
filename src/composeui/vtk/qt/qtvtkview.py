from composeui.core.qt.qtview import QtView
from composeui.vtk.ivtkview import VTKPickType, VTKView

from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonCore import vtkCommand, vtkLookupTable, vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCell, vtkDataSet, vtkUnstructuredGrid
from vtkmodules.vtkFiltersGeneral import vtkWarpVector
from vtkmodules.vtkFiltersSources import vtkSphereSource
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkInteractionWidgets import (
    vtkCameraOrientationRepresentation,
    vtkCameraOrientationWidget,
    vtkScalarBarWidget,
)
from vtkmodules.vtkRenderingAnnotation import vtkScalarBarActor
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkCellPicker,
    vtkDataSetMapper,
    vtkPointPicker,
    vtkPolyDataMapper,
    vtkRenderWindow,
    vtkRenderWindowInteractor,
)
from vtkmodules.vtkRenderingOpenGL2 import vtkOpenGLRenderer

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

colors = vtkNamedColors()


@dataclass
class CameraConfiguration:
    position: Tuple[float, float, float] = field(default_factory=lambda: (0.0, 0.0, 0.0))
    focal_point: Tuple[float, float, float] = field(default_factory=lambda: (0.0, 0.0, 0.0))
    view_up: Tuple[float, float, float] = field(default_factory=lambda: (0.0, 0.0, 0.0))
    distance: float = 0
    clippling_range: Tuple[float, float] = field(default_factory=lambda: (0.0, 0.0))


@dataclass(eq=False)
class QtVTKView(QtView, VTKView):
    view: QWidget = field(init=False)

    _toolbar: QWidget = field(init=False)
    _reset_camera_button: QPushButton = field(init=False)
    _render_view: QVTKRenderWindowInteractor = field(init=False)
    _renderer: vtkOpenGLRenderer = field(init=False)
    _interactor: vtkRenderWindowInteractor = field(init=False)
    _camera_orientation_manipulator: vtkCameraOrientationWidget = field(init=False)
    _scalar_bar_lut: vtkLookupTable = field(init=False)
    _scalar_bar: vtkScalarBarActor = field(init=False)
    _scalar_bar_widget: vtkScalarBarWidget = field(init=False)
    _vtk_warp_vector: Optional[vtkWarpVector] = field(init=False, default=None)
    _actor: Optional[vtkActor] = field(init=False, default=None)
    _is_edge_visible: bool = field(init=False, default=False)
    _edge_width: float = field(init=False, default=1.0)
    _warp_scale_factor: float = field(init=False, default=1.0)
    _initial_camera_orientation: CameraConfiguration = field(
        init=False, default_factory=CameraConfiguration
    )

    def __post_init__(self) -> None:
        self.view = QWidget()
        layout = QVBoxLayout()
        self.view.setLayout(layout)
        # toolbar
        self._toolbar = QWidget()
        toolbar_layout = QHBoxLayout()
        toolbar_layout.addStretch()
        self._toolbar.setLayout(toolbar_layout)
        layout.addWidget(self._toolbar)
        # - Reset Camera button
        self._reset_camera_button = QPushButton()
        self._reset_camera_button.setToolTip("Reset Camera")
        self._reset_camera_button.setIcon(QIcon(":/icons/reset_focus.png"))
        self.reset_camera_clicked.add_qt_signals(
            (self._reset_camera_button, self._reset_camera_button.clicked)
        )
        toolbar_layout.insertWidget(0, self._reset_camera_button)
        # - Text to indicate how to pick a cell/point
        information_label = QLabel(self.toolbar_information_text)
        information_label.setStyleSheet("QLabel { font-size: 11px; font: italic; }")
        toolbar_layout.insertWidget(1, information_label)
        # vtk view
        self._render_view = QVTKRenderWindowInteractor()  # type: ignore[no-untyped-call]
        # PyQt5 and PySide6 disagree here os we ignore the type
        layout.addWidget(self._render_view)  # type: ignore[arg-type, unused-ignore]
        # create an interactor
        self._interactor = self.render_window.GetInteractor()
        style = MouseInteractorStyle(self)
        self._interactor.SetInteractorStyle(style)
        # add a camera manipulator
        self._create_camera_manipulator()
        # add a scalar bar
        self._create_scalar_bar()
        # create the renderer
        self._create_renderer()

    @property  # type: ignore[misc]
    def is_edge_visible(self) -> bool:
        return self._is_edge_visible

    @is_edge_visible.setter
    def is_edge_visible(self, is_edge_visible: bool) -> None:
        self._is_edge_visible = is_edge_visible
        if self._actor is not None:
            if self._is_edge_visible:
                self._actor.GetProperty().EdgeVisibilityOn()
            else:
                self._actor.GetProperty().EdgeVisibilityOff()

    @property  # type: ignore[misc]
    def edge_width(self) -> float:
        return self._edge_width

    @edge_width.setter
    def edge_width(self, edge_width: float) -> None:
        self._edge_width = edge_width
        if self._actor is not None:
            self._actor.GetProperty().SetLineWidth(edge_width)

    @property  # type: ignore[misc]
    def warp_scale_factor(self) -> float:
        return self._warp_scale_factor

    @warp_scale_factor.setter
    def warp_scale_factor(self, warp_scale_factor: float) -> None:
        self._warp_scale_factor = warp_scale_factor
        if self._vtk_warp_vector is not None:
            self._vtk_warp_vector.SetScaleFactor(warp_scale_factor)
            self._vtk_warp_vector.Update()

    @property
    def actor(self) -> Optional[vtkActor]:
        return self._actor

    @property
    def render_window(self) -> vtkRenderWindow:
        render_window = self._render_view.GetRenderWindow()  # type: ignore[no-untyped-call]
        assert isinstance(render_window, vtkRenderWindow)
        return render_window

    def reset_camera(self) -> None:
        self._set_orientation(self._initial_camera_orientation)

    def render(self) -> None:
        # create new renderer
        self._create_renderer()
        # create the new actor
        self._create_actor()
        super().render()
        if self.view.isVisible():
            self.render_window.Render()

    def _set_orientation(self, camera_configuration: CameraConfiguration) -> None:
        camera = self._renderer.GetActiveCamera()
        camera.SetPosition(tuple(camera_configuration.position))
        camera.SetFocalPoint(tuple(camera_configuration.focal_point))
        camera.SetViewUp(tuple(camera_configuration.view_up))
        camera.SetDistance(camera_configuration.distance)
        camera.SetClippingRange(tuple(camera_configuration.clippling_range))

    def _get_orientation(self) -> CameraConfiguration:
        camera = self._renderer.GetActiveCamera()
        position = camera.GetPosition()
        focal_point = camera.GetFocalPoint()
        view_up = camera.GetViewUp()
        clipping_range = camera.GetClippingRange()
        return CameraConfiguration(
            position=(position[0], position[1], position[2]),
            focal_point=(focal_point[0], focal_point[1], focal_point[2]),
            view_up=(view_up[0], view_up[1], view_up[2]),
            distance=camera.GetDistance(),
            clippling_range=(clipping_range[0], clipping_range[1]),
        )

    def _create_renderer(self) -> None:
        """Create the renderer of the vtk view."""
        self._camera_orientation_manipulator.Off()
        self._scalar_bar_widget.Off()
        # delete old renderer
        if hasattr(self, "_renderer"):  # in post_init attribute _renderer doesn't exist yet
            self.render_window.RemoveRenderer(self._renderer)
        # create a renderer
        self._renderer = vtkOpenGLRenderer()
        self._renderer.SetBackground(colors.GetColor3d("White"))
        self.render_window.AddRenderer(self._renderer)
        # set the renderer to the style of the interactor
        self._interactor.GetInteractorStyle().SetDefaultRenderer(self._renderer)
        # set camera manipulator parent
        self._camera_orientation_manipulator.SetParentRenderer(self._renderer)
        self._camera_orientation_manipulator.On()
        # set scalar bar interactor
        self._scalar_bar_widget.SetInteractor(self._interactor)
        self._scalar_bar_widget.On()
        # initialize
        self._interactor.Initialize()

    def _create_actor(self) -> None:
        if self.vtk_scalar_name is not None and self.vtk_ugrid is not None:
            # Check if scalar name exists and is active
            vector_array = self.vtk_ugrid.GetPointData().GetArray(self.vtk_scalar_name)
            if vector_array is None:
                msg = f"Field '{self.vtk_scalar_name}' not found in the dataset."
                raise ValueError(msg)
            if vector_array.GetNumberOfComponents() > 1:
                self.vtk_ugrid.GetPointData().SetActiveVectors(self.vtk_scalar_name)
                self.vtk_ugrid.GetPointData().SetActiveScalars(self.vtk_scalar_name)
                scalar_range = self.vtk_ugrid.GetPointData().GetVectors().GetRange()
            else:
                self.vtk_ugrid.GetPointData().SetActiveScalars(self.vtk_scalar_name)
                scalar_range = self.vtk_ugrid.GetPointData().GetScalars().GetRange()
            # warp
            if self.is_warp_active:
                self._vtk_warp_vector = vtkWarpVector()
                self._vtk_warp_vector.SetInputData(self.vtk_ugrid)
                self._vtk_warp_vector.SetScaleFactor(self.warp_scale_factor)
                self._vtk_warp_vector.Update()
            else:
                self._vtk_warp_vector = None
            if self._vtk_warp_vector is not None:
                output = self._vtk_warp_vector.GetOutput()
            else:
                output = self.vtk_ugrid
            # mapper
            mapper = vtkDataSetMapper()
            mapper.SetInputData(output)
            mapper.SetScalarRange(scalar_range)
            mapper.SetLookupTable(self._scalar_bar_lut)
            # actor
            self._actor = vtkActor()
            self._actor.SetMapper(mapper)
            if self._is_edge_visible:
                self._actor.GetProperty().EdgeVisibilityOn()
            if self._edge_width is not None:
                self._actor.GetProperty().SetLineWidth(self._edge_width)
            # add actor to the renderer
            self._renderer.AddActor(self._actor)
            self._renderer.ResetCamera()
            self._initial_camera_orientation = self._get_orientation()

    def _create_camera_manipulator(self) -> None:
        """Create a camera manipulator."""
        self._camera_orientation_manipulator = vtkCameraOrientationWidget()
        camera_manipulator_repr = self._camera_orientation_manipulator.GetRepresentation()
        assert isinstance(camera_manipulator_repr, vtkCameraOrientationRepresentation)
        camera_manipulator_repr.AnchorToLowerLeft()

    def _create_scalar_bar(self) -> None:
        """Create a scalar bar."""
        self._scalar_bar_lut = vtkLookupTable()
        self._scalar_bar_lut.Build()
        self._scalar_bar = vtkScalarBarActor()
        self._scalar_bar.SetOrientationToHorizontal()
        self._scalar_bar.SetLookupTable(self._scalar_bar_lut)
        self._scalar_bar.SetUnconstrainedFontSize(True)
        self._scalar_bar.SetMaximumWidthInPixels(100)
        self._scalar_bar_widget = vtkScalarBarWidget()
        self._scalar_bar.GetLabelTextProperty().SetColor(0, 0, 0)
        self._scalar_bar.GetLabelTextProperty().SetFontSize(12)
        self._scalar_bar_widget.SetScalarBarActor(self._scalar_bar)


class MouseInteractorStyle(vtkInteractorStyleTrackballCamera):
    def __init__(self, view: QtVTKView) -> None:
        super().__init__()
        self.AddObserver(vtkCommand.LeftButtonPressEvent, self.left_button_press_event)
        self._highlight_actor: Optional[vtkActor] = None
        self.last_picked_cell_id = -1
        self.last_picked_point_id = -1
        self._view = view

    def left_button_press_event(self, obj: "MouseInteractorStyle", event: str) -> None:
        """Callback when the user click on the left button of the mouse."""
        # Pick only when the shift key is held down
        if self.GetInteractor().GetShiftKey():
            if self._view.pick_type == VTKPickType.CELL:
                self._picked_cell()
                self._view.last_picked_node_id = -1
            elif self._view.pick_type == VTKPickType.POINT:
                self._view.last_picked_cell_id = -1
                self._picked_point()
        # resume the left button down event
        self.OnLeftButtonDown()

    def _picked_cell(self) -> None:
        """Highlight the picked cell and store its id in the view."""
        position = self.GetInteractor().GetEventPosition()
        picker = vtkCellPicker()
        picker.SetTolerance(self._view.picker_tolerance)
        picker.Pick(position[0], position[1], 0, self.GetDefaultRenderer())
        picked_cell_id = picker.GetCellId()
        if self._highlight_actor is not None:
            self.GetDefaultRenderer().RemoveActor(self._highlight_actor)
        if picked_cell_id >= 0:
            picked_dataset: vtkDataSet = picker.GetDataSet()
            picked_cell = picked_dataset.GetCell(picked_cell_id)
            self._highlight_actor = self._create_highlight_cell_actor(picked_cell)
            self.GetDefaultRenderer().AddActor(self._highlight_actor)
            # Change the opacity of the main unstructured grid to highlight the picked cell
            if self._view.actor is not None:
                self._view.actor.GetProperty().SetOpacity(self._view.opacity_after_picked)
            self.last_picked_cell_id = picked_cell_id
        elif self._view.actor is not None:
            self._view.actor.GetProperty().SetOpacity(1.0)
        self._view.last_picked_cell_id = picked_cell_id
        self._view.cell_picked()

    def _picked_point(self) -> None:
        """Highlight the picked point and store its id in the view."""
        position = self.GetInteractor().GetEventPosition()
        picker = vtkPointPicker()
        picker.SetTolerance(self._view.picker_tolerance)
        picker.Pick(position[0], position[1], 0, self.GetDefaultRenderer())
        picked_point_id = picker.GetPointId()
        if self._highlight_actor is not None:
            self.GetDefaultRenderer().RemoveActor(self._highlight_actor)
        if picked_point_id >= 0:
            picked_dataset: vtkDataSet = picker.GetDataSet()
            diagonal_length = 0.0
            if self._view.vtk_ugrid is not None:
                (xmin, xmax, ymin, ymax, zmin, zmax) = self._view.vtk_ugrid.GetBounds()
                diagonal_length = math.sqrt(
                    (xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2
                )
            picked_point = picked_dataset.GetPoint(picked_point_id)
            self._highlight_actor = self._create_highlight_point_actor(
                picked_point,
                radius=self._view.pick_point_sphere_scale_factor * diagonal_length,
            )
            self.GetDefaultRenderer().AddActor(self._highlight_actor)
            # Change the opacity of the main unstructured grid to highlight the picked point
            if self._view.actor is not None:
                self._view.actor.GetProperty().SetOpacity(self._view.opacity_after_picked)
            self.last_picked_point_id = picked_point_id
        elif self._view.actor is not None:
            self._view.actor.GetProperty().SetOpacity(1.0)
        self._view.last_picked_point_id = picked_point_id
        self._view.point_picked()

    def _create_highlight_cell_actor(self, picked_cell: vtkCell) -> vtkActor:
        """Create an actor of the picked cell.

        An unstructured grid is created with only the picked cell
        """
        # create points
        points = vtkPoints()
        picked_points: vtkPoints = picked_cell.GetPoints()
        for i in range(picked_cell.GetNumberOfPoints()):
            points.InsertNextPoint(picked_points.GetPoint(i))
        # create grid
        highlight_grid = vtkUnstructuredGrid()
        highlight_grid.SetPoints(points)
        highlight_grid.InsertNextCell(
            picked_cell.GetCellType(),
            # point_ids,
            picked_cell.GetNumberOfPoints(),
            list(range(picked_cell.GetNumberOfPoints())),
        )
        # Create mapper
        highlight_mapper = vtkDataSetMapper()
        highlight_mapper.SetInputData(highlight_grid)
        # create actor
        highlight_actor = vtkActor()
        highlight_actor.SetMapper(highlight_mapper)
        highlight_property = highlight_actor.GetProperty()
        highlight_property.SetColor(*self._view.picked_cell_color)
        # highlight_property.SetOpacity(0.8)
        highlight_property.EdgeVisibilityOn()
        return highlight_actor

    def _create_highlight_point_actor(
        self, coordinates: Tuple[float, float, float], radius: float
    ) -> vtkActor:
        """Create a sphere at the given coordinates."""
        sphere = vtkSphereSource()
        sphere.SetCenter(*coordinates)
        sphere.SetRadius(radius)
        sphere_mapper = vtkPolyDataMapper()
        sphere_mapper.SetInputConnection(sphere.GetOutputPort())
        sphere_actor = vtkActor()
        sphere_actor.SetMapper(sphere_mapper)
        sphere_actor.GetProperty().SetColor(*self._view.picked_point_color)
        return sphere_actor
