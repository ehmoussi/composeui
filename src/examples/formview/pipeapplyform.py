from composeui import form
from composeui.form.formview import (
    GroupBoxApplyFormView,
    LabelComboBoxView,
    LabelLineEditView,
    LabelSelectFileView,
)
from examples.formview import pipeform
from examples.formview.pipeform import (
    AbstractPipeFormItems,
    ChamferDimensionView,
    EdgeType,
    FilletDimensionView,
    PipeDimensionView,
    PipeQuery,
)

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    from examples.formview.app import Model
    from examples.formview.example import ExampleMainView


@dataclass(eq=False)
class PipeApplyFormView(GroupBoxApplyFormView["PipeApplyFormItems"]):
    name: LabelLineEditView["PipeApplyFormItems"] = field(
        init=False, default_factory=LabelLineEditView["PipeApplyFormItems"]
    )
    p_id: LabelLineEditView["PipeApplyFormItems"] = field(
        init=False, default_factory=LabelLineEditView["PipeApplyFormItems"]
    )
    export: LabelSelectFileView["PipeApplyFormItems"] = field(
        init=False, default_factory=LabelSelectFileView["PipeApplyFormItems"]
    )
    main: PipeDimensionView["PipeApplyFormItems"] = field(
        init=False, default_factory=PipeDimensionView["PipeApplyFormItems"]
    )
    incident: PipeDimensionView["PipeApplyFormItems"] = field(
        init=False, default_factory=PipeDimensionView["PipeApplyFormItems"]
    )
    edge_type: LabelComboBoxView["PipeApplyFormItems"] = field(
        init=False, default_factory=LabelComboBoxView["PipeApplyFormItems"]
    )
    chamfer: ChamferDimensionView["PipeApplyFormItems"] = field(
        init=False, default_factory=ChamferDimensionView["PipeApplyFormItems"]
    )
    fillet: FilletDimensionView["PipeApplyFormItems"] = field(
        init=False, default_factory=FilletDimensionView["PipeApplyFormItems"]
    )


def initialize_apply_pipe(
    view: PipeApplyFormView,
    main_view: "ExampleMainView",
    model: "Model",
    is_visible: bool = False,
) -> None:
    form.initialize_form_view(view, PipeApplyFormItems(model, view))
    view.is_visible = is_visible
    view.title = "Pipe"
    view.export.field_view.mode = "save_file"
    pipeform.initialize_main_pipe(view.main)
    pipeform.initialize_incident_pipe(view.incident)
    pipeform.initialize_chamfer(view.chamfer)
    pipeform.initialize_fillet(view.fillet)
    # the edge type selection modify the visibility of the chamfer and fillet forms
    view.edge_type.field_view.dependencies.extend([view.chamfer, view.fillet])


class PipeApplyFormItems(AbstractPipeFormItems[PipeApplyFormView]):
    def __init__(self, model: "Model", view: PipeApplyFormView) -> None:
        super().__init__(model, view)

    @property
    def query(self) -> PipeQuery:
        return self._model.apply_pipe_query

    def is_visible(self, field: str, parent_fields: Tuple[str, ...] = ()) -> bool:
        """Check if the field is visible.

        The visibility must be dependent of the current values of the view.
        With the ApplyFormView the values are updated after clicking on apply.
        So it's the values of the view that should be used.
        """
        if field in ("chamfer", "fillet") and self._view is not None:
            current_index = self._view.edge_type.field_view.current_index
            return str(EdgeType(current_index)) == field
        return super().is_visible(field, parent_fields)

    def get_error_messages(self, field: str, parent_fields: Tuple[str, ...] = ()) -> List[str]:
        """Get the error messages to display if the data are incorrect.

        If the validation need to be done before putting the values to the model.
        Then the checks need to be done using the view because the model has the old values.
        """
        infos = []
        if self._view is not None:
            if (
                len(parent_fields) == 0
                and field == "name"
                and self._view.name.field_view.text == ""
            ):
                infos.append("A name is mandatory")
            elif len(parent_fields) == 1:
                main_radius = self._view.main.radius.field_view.value
                if main_radius is not None:
                    if (parent_fields[0] == "main" and field in ("radius", "width")) or (
                        parent_fields[0] == "incident" and field == "half_length"
                    ):
                        main_width = self._view.main.width.field_view.value
                        incident_half_length = self._view.incident.half_length.field_view.value
                        if (
                            main_width is not None
                            and incident_half_length is not None
                            and main_radius + main_width > incident_half_length
                        ):
                            infos.append(
                                "The sum of the radius and width of the main pipe "
                                "can't be greater than the half length of the incident pipe "
                                f"({main_radius} + {main_width} > {incident_half_length})"
                            )
                    if field == "radius":
                        incident_radius = self._view.incident.radius.field_view.value
                        if incident_radius is not None and incident_radius > main_radius:
                            infos.append(
                                "The incident radius cant'be greater than the main radius "
                                f"({incident_radius} > {main_radius})"
                            )
        return infos
