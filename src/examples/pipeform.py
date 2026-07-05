from __future__ import annotations

import enum

from attrs import Factory

from composeui.core.view import (
    FormView,
    GroupFormView,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelRowRadioGroupView,
    LogType,
    MainView,
    define_view,
)
from composeui.qtcore.qtapplication import QtApplication


@define_view
class DimensionInputView(LabelRowFloatInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.value = 20.0
        self.minimum = 0
        self.decimals = 3


@define_view
class PipeDimensionView(GroupFormView):
    radius: DimensionInputView = Factory(DimensionInputView)
    width: DimensionInputView = Factory(DimensionInputView)
    half_length: DimensionInputView = Factory(DimensionInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.radius.label = "Radius"
        self.width.label = "Width"
        self.half_length.label = "Half Length"
        self.half_length.value = 200.0


class EdgeType(enum.Enum):
    Normal = "Normal"
    Chamfer = "Chamfer"
    Fillet = "Fillet"


@define_view
class EdgeTypeView(LabelRowRadioGroupView[EdgeType]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Edge Type"
        self.value = EdgeType.Normal
        # Use object.__setattr__ to bypass the frozen attribute restriction.
        object.__setattr__(
            self,
            "values",
            {
                EdgeType.Normal.value: EdgeType.Normal,
                EdgeType.Chamfer.value: EdgeType.Chamfer,
                EdgeType.Fillet.value: EdgeType.Fillet,
            },
        )


@define_view
class ChamferDimensionView(GroupFormView):
    height: DimensionInputView = Factory(DimensionInputView)
    width: DimensionInputView = Factory(DimensionInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Chamfer"
        self.height.label = "Height"
        self.width.label = "Width"


@define_view
class FilletDimensionView(GroupFormView):
    radius: DimensionInputView = Factory(DimensionInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Fillet"
        self.radius.label = "Radius"


@define_view
class PipeNameRowView(LabelRowInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Name"
        self.text_edited.connect(self._check_name)
        self._check_name(self.text)

    def _check_name(self, text: str) -> None:
        if text == "":
            self.log_message = "A name is mandatory"
            self.log_type = LogType.ERROR
        else:
            self.log_message = ""
            self.log_type = LogType.INFO


@define_view
class PipeFormView(FormView):
    name: PipeNameRowView = Factory(PipeNameRowView)
    main_pipe: PipeDimensionView = Factory(PipeDimensionView)
    incident_pipe: PipeDimensionView = Factory(PipeDimensionView)

    edge_type: EdgeTypeView = Factory(EdgeTypeView)

    chamfer: ChamferDimensionView = Factory(ChamferDimensionView)
    fillet: FilletDimensionView = Factory(FilletDimensionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # Main Pipe
        self.main_pipe.title = "Main Pipe"
        # Incident Pipe
        self.incident_pipe.title = "Incident Pipe"
        self.incident_pipe.radius.value = 50.0
        # Edge Type
        self.edge_type.value_changed.connect(self._display_edge_options)
        self._display_edge_options(self.edge_type.value)
        # Fillet
        self.fillet.radius.value = 20.0

    def _display_edge_options(self, edge_type: EdgeType | None) -> None:
        if edge_type == EdgeType.Chamfer:
            self.chamfer.is_visible = True
            self.fillet.is_visible = False
        elif edge_type == EdgeType.Fillet:
            self.chamfer.is_visible = False
            self.fillet.is_visible = True
        else:
            self.chamfer.is_visible = False
            self.fillet.is_visible = False


@define_view
class PipeMainView(MainView):
    pipe_form: PipeFormView = Factory(PipeFormView)

    def __attrs_post_init__(self) -> None:
        object.__setattr__(self, "title", "Pipe Form")
        object.__setattr__(self, "extension", ".pipe")
        super().__attrs_post_init__()
        # Use object.__setattr__ to bypass the frozen attribute restriction.
        self.pipe_form.edge_type.value_changed.connect(self._display_message_status_bar)

    def _display_message_status_bar(self, value: EdgeType | None) -> None:
        if value is not None:
            self.status_bar.show_message(f"Edge type changed: {value.value}", timeout=3)


_MAIN_VIEW = PipeMainView()
APP = QtApplication(main_view=_MAIN_VIEW)


@APP.connect(
    view=APP.main_view.pipe_form,
    signals=[
        APP.main_view.pipe_form.main_pipe.radius.editing_finished,
        APP.main_view.pipe_form.main_pipe.width.editing_finished,
        APP.main_view.pipe_form.incident_pipe.radius.editing_finished,
        APP.main_view.pipe_form.incident_pipe.half_length.editing_finished,
    ],
)
def display_error_message(*, view: PipeFormView) -> None:
    log_messages: list[str] = []
    main_radius = view.main_pipe.radius.value
    main_width = view.main_pipe.width.value
    incident_half_length = view.incident_pipe.half_length.value
    incident_radius = view.incident_pipe.radius.value
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
    if incident_radius is None or main_radius is None or incident_radius > main_radius:
        log_messages.append(
            "The incident radius cant'be greater than the main radius: "
            f"({incident_radius} > {main_radius})"
        )
    if len(log_messages) > 0:
        view.log_view.log_message = "- " + "\n- ".join(log_messages)
        view.log_view.log_type = LogType.ERROR
        view.log_view.is_visible = True
    else:
        view.log_view.is_visible = False
        view.log_view.log_message = ""
        view.log_view.log_type = LogType.INFO


def main() -> None:
    APP.run()


if __name__ == "__main__":
    main()
