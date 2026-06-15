from __future__ import annotations

import enum

from attrs import Factory, field

from composeui.qtapplication import QtApplication
from composeui.view import (
    FormView,
    GroupFormView,
    LabelFloatInputRowView,
    LabelInputRowView,
    LabelRadioGroupRowView,
    LogType,
    MainView,
    define_view,
)


@define_view
class RadiusInputView(LabelFloatInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Radius"
        self.field_view.value = 20.0
        self.field_view.minimum = 0
        self.field_view.decimals = 3


@define_view
class WidthInputView(LabelFloatInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Width"
        self.field_view.value = 20.0
        self.field_view.minimum = 0
        self.field_view.decimals = 3


@define_view
class HeightInputView(LabelFloatInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Height"
        self.field_view.value = 20.0
        self.field_view.minimum = 0.0
        self.field_view.decimals = 3


@define_view
class HalfLengthInputView(LabelFloatInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Half Length"
        self.field_view.value = 200.0
        self.field_view.minimum = 0
        self.field_view.decimals = 3


@define_view
class PipeDimensionView(GroupFormView):
    radius: RadiusInputView = Factory(RadiusInputView)
    width: WidthInputView = Factory(WidthInputView)
    half_length: HalfLengthInputView = Factory(HalfLengthInputView)


class EdgeType(enum.Enum):
    Normal = "Normal"
    Chamfer = "Chamfer"
    Fillet = "Fillet"


@define_view
class EdgeTypeView(LabelRadioGroupRowView[EdgeType]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Edge Type"
        self.field_view.value = EdgeType.Normal
        object.__setattr__(
            self.field_view,
            "values",
            {
                EdgeType.Normal.value: EdgeType.Normal,
                EdgeType.Chamfer.value: EdgeType.Chamfer,
                EdgeType.Fillet.value: EdgeType.Fillet,
            },
        )


@define_view
class ChamferDimensionView(GroupFormView):
    height: HeightInputView = Factory(HeightInputView)
    width: WidthInputView = Factory(WidthInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Chamfer"


@define_view
class FilletDimensionView(GroupFormView):
    radius: RadiusInputView = Factory(RadiusInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Fillet"


@define_view
class PipeNameRowView(LabelInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Name"
        self.field_view.text_edited.connect(self._check_name)
        self._check_name(self.field_view.text)

    def _check_name(self, text: str) -> None:
        if text == "":
            self.log_view.log_message = "A name is mandatory"
            self.log_view.log_type = LogType.ERROR
            self.log_view.is_visible = True
        else:
            self.log_view.is_visible = False
            self.log_view.log_message = ""
            self.log_view.log_type = LogType.INFO


@define_view
class PipeFormView(FormView):
    name: PipeNameRowView = field(factory=PipeNameRowView)
    main_pipe: PipeDimensionView = Factory(PipeDimensionView)
    incident_pipe: PipeDimensionView = Factory(PipeDimensionView)

    edge_type: EdgeTypeView = Factory(EdgeTypeView)

    chamfer: ChamferDimensionView = Factory(ChamferDimensionView)
    fillet: FilletDimensionView = Factory(FilletDimensionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # Main Pipe
        self.main_pipe.title = "Main Pipe"
        self.main_pipe.radius.field_view.editing_finished.connect(
            self._display_error_message
        )
        self.main_pipe.width.field_view.editing_finished.connect(
            self._display_error_message
        )
        # Incident Pipe
        self.incident_pipe.title = "Incident Pipe"
        self.incident_pipe.radius.field_view.value = 50.0
        self.incident_pipe.radius.field_view.editing_finished.connect(
            self._display_error_message
        )
        self.incident_pipe.half_length.field_view.editing_finished.connect(
            self._display_error_message
        )
        # Edge Type
        self.edge_type.field_view.value_changed.connect(self._display_edge_options)
        self._display_edge_options()
        # Fillet
        self.fillet.radius.field_view.value = 20.0

    def _display_edge_options(self) -> None:
        edge_type = self.edge_type.field_view.value
        if edge_type == EdgeType.Chamfer:
            self.chamfer.is_visible = True
            self.fillet.is_visible = False
        elif edge_type == EdgeType.Fillet:
            self.chamfer.is_visible = False
            self.fillet.is_visible = True
        else:
            self.chamfer.is_visible = False
            self.fillet.is_visible = False

    def _display_error_message(self) -> None:
        log_messages: list[str] = []
        main_radius = self.main_pipe.radius.field_view.value
        main_width = self.main_pipe.width.field_view.value
        incident_half_length = self.incident_pipe.half_length.field_view.value
        incident_radius = self.incident_pipe.radius.field_view.value
        if (
            main_radius is None
            or main_width is None
            or incident_half_length is None
            or (main_radius + main_width) > incident_half_length
        ):
            log_messages.append(
                "The sum of the radius and width of the main pipe "
                "can't be greater than the half length of the incident pipe: "
                f"({main_radius} + {main_width} > "
                f"{incident_half_length})"
            )
        if (
            incident_radius is None
            or main_radius is None
            or incident_radius > main_radius
        ):
            log_messages.append(
                "The incident radius cant'be greater than the main radius: "
                f"({incident_radius} > {main_radius})"
            )
        if len(log_messages) > 0:
            self.log_view.log_message = "- " + "\n- ".join(log_messages)
            self.log_view.log_type = LogType.ERROR
            self.log_view.is_visible = True
        else:
            self.log_view.is_visible = False
            self.log_view.log_message = ""
            self.log_view.log_type = LogType.INFO


@define_view
class PipeMainView(MainView):
    pipe_form: PipeFormView = field(factory=PipeFormView)

    def __attrs_post_init__(self) -> None:
        # Use object.__setattr__ to bypass the frozen attribute restriction.
        object.__setattr__(self, "title", "Pipe Form")
        object.__setattr__(self, "extension", ".pipe")


def main() -> None:
    main_view = PipeMainView()
    # print(attrs.asdict(main_view, filter=attrs.filters.exclude("renderer", Signal)))
    app = QtApplication(main_view)
    app.run()


if __name__ == "__main__":
    main()
