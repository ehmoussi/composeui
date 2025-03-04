from composeui import form
from composeui.core import tools
from composeui.core.views.view import GroupView, View
from composeui.form.abstractformitems import AbstractFormItems
from composeui.form.formview import (
    GroupBoxApplyFormView,
    LabelComboBoxView,
    LabelDoubleLineEditView,
    LabelRadioButtonGroupView,
    NoLabelSelectFileView,
)
from composeui.mainview.views.mainview import MainView
from composeui.vtk import vtkutils
from composeui.vtk.vtkview import VTKPickType, VTKView

import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

if typing.TYPE_CHECKING:
    from examples.vtkview.app import Model


class VTKConfigFormItems(AbstractFormItems["Model", "VTKConfigView"]):
    def is_visible(self, field: str, parent_fields: Tuple[str, ...] = ()) -> bool:
        if field == "edge_width":
            return self._view.edge.field_view.current_index == 0
        elif field == "warp_scale":
            return self._view.warp.field_view.current_index == 0
        return super().is_visible(field, parent_fields)

    def get_error_messages(self, field: str, parent_fields: Tuple[str, ...] = ()) -> List[str]:
        if self._view.file.field_view.text == "":
            if field == "file":
                return ["Select a file to display in the view"]
        elif (
            field == "scalar_field" and self._view.scalar_field.field_view.current_index == -1
        ):
            if len(self._model.root.vtk_fields) == 0:
                return ["Click Apply to populate the available fields"]
            else:
                return ["Select a field to display in the view"]
        return super().get_error_messages(field, parent_fields)

    def get_value(self, field: str, parent_fields: Tuple[str, ...] = ()) -> Any:
        if field == "file":
            return self._model.root.vtk_filepath
        elif field == "scalar_field":
            return self._model.root.current_vtk_field
        elif field == "edge":
            return self._model.root.is_edge_visible
        elif field == "edge_width":
            return self._model.root.edge_width
        elif field == "warp":
            return self._model.root.is_warp_active
        elif field == "warp_scale":
            return self._model.root.warp_scale_factor
        elif field == "pick_type":
            return self._model.root.pick_type.value
        return super().get_value(field, parent_fields)

    def set_value(self, field: str, value: Any, parent_fields: Tuple[str, ...] = ()) -> bool:
        if field == "file":
            self._model.root.vtk_filepath = str(value)
            return True
        elif field == "scalar_field":
            self._model.root.current_vtk_field = str(value)
            return True
        elif field == "edge":
            self._model.root.is_edge_visible = bool(value)
            return True
        elif field == "warp":
            self._model.root.is_warp_active = bool(value)
            return True
        elif field in ("edge_width", "warp_scale"):
            float_value = self.to_float_value(value)
            if float_value is not None:
                if field == "edge_width":
                    self._model.root.edge_width = float_value
                elif field == "warp_scale":
                    self._model.root.warp_scale_factor = float_value
                return True
            else:
                return False
        elif field == "pick_type":
            int_value = self.to_int_value(value)
            if int_value is not None:
                self._model.root.pick_type = VTKPickType(int_value)
                return True
            return False
        return super().set_value(field, value, parent_fields)

    def acceptable_values(
        self, field: str, parent_fields: Tuple[str, ...] = ()
    ) -> Optional[Sequence[Any]]:
        if field == "scalar_field":
            return self._model.root.vtk_fields
        elif field in ("edge", "warp"):
            return [True, False]
        elif field == "pick_type":
            return list(VTKPickType)
        return super().acceptable_values(field, parent_fields)

    def acceptable_displayed_values(
        self, field: str, parent_fields: Tuple[str, ...] = ()
    ) -> Optional[Sequence[str]]:
        if field in ("edge", "warp"):
            return ["Yes", "No"]
        elif field == "pick_type":
            return list(map(str, VTKPickType))
        return super().acceptable_displayed_values(field, parent_fields)


@dataclass(eq=False)
class VTKInfosView(GroupView):
    text: str = field(init=False, default="")


@dataclass(eq=False)
class VTKConfigView(GroupBoxApplyFormView[VTKConfigFormItems]):
    file: NoLabelSelectFileView[VTKConfigFormItems] = field(
        init=False, repr=False, default_factory=NoLabelSelectFileView
    )
    scalar_field: LabelComboBoxView[VTKConfigFormItems] = field(
        init=False, repr=False, default_factory=LabelComboBoxView
    )
    edge: LabelRadioButtonGroupView[VTKConfigFormItems] = field(
        init=False, repr=False, default_factory=LabelRadioButtonGroupView
    )
    edge_width: LabelDoubleLineEditView[VTKConfigFormItems] = field(
        init=False, repr=False, default_factory=LabelDoubleLineEditView
    )
    warp: LabelComboBoxView[VTKConfigFormItems] = field(
        init=False, repr=False, default_factory=LabelComboBoxView
    )
    warp_scale: LabelDoubleLineEditView[VTKConfigFormItems] = field(
        init=False, repr=False, default_factory=LabelDoubleLineEditView
    )
    pick_type: LabelRadioButtonGroupView[VTKConfigFormItems] = field(
        init=False, repr=False, default_factory=LabelRadioButtonGroupView
    )


@dataclass(eq=False)
class VTKExampleView(View):
    configuration: VTKConfigView = field(init=False, repr=False, default_factory=VTKConfigView)
    vtk_view: VTKView = field(init=False, repr=False, default_factory=VTKView)
    informations: VTKInfosView = field(init=False, repr=False, default_factory=VTKInfosView)


@dataclass(eq=False)
class ExampleMainView(MainView):
    vtk_example: VTKExampleView = field(init=False, repr=False, default_factory=VTKExampleView)


def read_file(*, view: VTKConfigView, main_view: ExampleMainView, model: "Model") -> None:
    filepath = Path(view.file.field_view.text)
    vtk_ugrid = vtkutils.read_file(filepath, main_view=main_view)
    if vtk_ugrid is not None:
        data = vtk_ugrid.GetPointData()
        array_names = [str(data.GetArrayName(i)) for i in range(data.GetNumberOfArrays())]
        model.root.vtk_fields = array_names
        if model.root.current_vtk_field != "" and model.root.current_vtk_field in array_names:
            main_view.vtk_example.vtk_view.vtk_scalar_name = model.root.current_vtk_field
            main_view.vtk_example.vtk_view.vtk_ugrid = vtk_ugrid
            main_view.vtk_example.vtk_view.is_edge_visible = model.root.is_edge_visible
            main_view.vtk_example.vtk_view.edge_width = model.root.edge_width
            main_view.vtk_example.vtk_view.is_warp_active = model.root.is_warp_active
            main_view.vtk_example.vtk_view.warp_scale_factor = model.root.warp_scale_factor
            main_view.vtk_example.vtk_view.pick_type = model.root.pick_type
            main_view.vtk_example.vtk_view.render()
        tools.update_view_with_dependencies(view.scalar_field)


def display_informations(*, view: VTKView, parent_view: VTKExampleView) -> None:
    """Display the cell informations of the last cell/point picked."""
    text = ""
    if view.last_picked_cell_id >= 0:
        parent_view.informations.title = f"Cell Id: {view.last_picked_cell_id}"
        cell_type = vtkutils.get_cell_type(view.last_picked_cell_id, view=view)
        text += f"Cell Type: {cell_type.name}\n\n"
        for point_id, value in vtkutils.get_cell_field_value(
            view.last_picked_cell_id, view=view
        ).items():
            text += f"{point_id}: {_display_vector(value)}\n\n"
        parent_view.informations.is_visible = True
    elif view.last_picked_point_id >= 0:
        parent_view.informations.title = f"Point Id: {view.last_picked_point_id}"
        text += (
            f"{view.last_picked_point_id}: "
            + _display_vector(
                vtkutils.get_point_field_value(view.last_picked_point_id, view=view)
            )
            + "\n\n"
        )
        parent_view.informations.is_visible = True
    else:
        parent_view.informations.is_visible = False
    parent_view.informations.text = text


def initialize_vtk_example(view: VTKExampleView, model: "Model") -> None:
    """Initialize the vtk view."""
    # configuration
    form.initialize_form_view_items(
        view.configuration, VTKConfigFormItems(model, view.configuration)
    )
    view.configuration.title = "Configuration"
    view.configuration.file.field_view.extensions = "*.vtu;*.vtk"
    view.configuration.edge.field_view.dependencies.append(view.configuration.edge_width)
    view.configuration.edge_width.is_visible = False
    view.configuration.edge_width.field_view.minimum = 0.0
    view.configuration.warp.field_view.dependencies.append(view.configuration.warp_scale)
    view.configuration.warp_scale.is_visible = False
    view.configuration.warp_scale.minimum = 0.0
    # vtk infos
    view.informations.is_visible = False
    view.informations.is_enabled = False


def connect_vtk_example(view: VTKExampleView) -> None:
    view.configuration.apply_clicked += [read_file]
    view.vtk_view.cell_picked += [display_informations]
    view.vtk_view.point_picked += [display_informations]


def _display_vector(vector: List[float]) -> str:
    """Fancy display of a vector."""
    return "[" + ", ".join(f"{comp:0.3f}" for comp in vector) + "]"
