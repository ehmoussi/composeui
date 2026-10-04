from __future__ import annotations

import enum

from attrs import Factory

from composeui.core.view import (
    FormView,
    GroupFormView,
    LabelRowComboboxView,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelRowRadioGroupView,
    MainView,
    define_view,
)
from composeui.qtcore.qtapplication import QtApplication
from composeui.textualcore.textualapplication import TextualApplication
from composeui.webcore.webapplication import WebApplication


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
        self.values = {
            EdgeType.Normal.value: EdgeType.Normal,
            EdgeType.Chamfer.value: EdgeType.Chamfer,
            EdgeType.Fillet.value: EdgeType.Fillet,
        }
        self.value = EdgeType.Normal


class Material(enum.Enum):
    Steel = "Steel"
    Copper = "Copper"
    Aluminum = "Aluminum"
    Pvc = "PVC"


@define_view
class MaterialView(LabelRowComboboxView[Material]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Material"
        self.values = {
            Material.Steel.value: Material.Steel,
            Material.Copper.value: Material.Copper,
            Material.Aluminum.value: Material.Aluminum,
            Material.Pvc.value: Material.Pvc,
        }
        self.value = Material.Steel


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
        self.set_validator(self._check_name, self.text_edited)
        self.run_validator()

    def _check_name(self) -> str | None:
        return "A name is mandatory" if self.text == "" else None


@define_view
class PipeFormView(FormView):
    name: PipeNameRowView = Factory(PipeNameRowView)
    material: MaterialView = Factory(MaterialView)

    main_pipe: PipeDimensionView = Factory(PipeDimensionView)
    incident_pipe: PipeDimensionView = Factory(PipeDimensionView)

    edge_type: EdgeTypeView = Factory(EdgeTypeView)

    chamfer: ChamferDimensionView = Factory(ChamferDimensionView)
    fillet: FilletDimensionView = Factory(FilletDimensionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # Main Pipe
        self.main_pipe.title = "Main Pipe"
        self.main_pipe.radius.value = 50.0
        # Incident Pipe
        self.incident_pipe.title = "Incident Pipe"
        # two independent cross-field checks, combined into one shared `log_view`
        self.add_validator(
            self._check_main_pipe_fits_incident,
            self.main_pipe.radius.editing_finished,
            self.main_pipe.width.editing_finished,
            self.incident_pipe.half_length.editing_finished,
        )
        self.add_validator(
            self._check_incident_radius_not_greater_than_main,
            self.incident_pipe.radius.editing_finished,
            self.main_pipe.radius.editing_finished,
        )
        # Edge Type
        self.edge_type.value_changed.connect(self._display_edge_options)
        self._display_edge_options(self.edge_type.value)
        # Fillet
        self.fillet.radius.value = 20.0

    def _check_main_pipe_fits_incident(self) -> str | None:
        main_radius = self.main_pipe.radius.value
        main_width = self.main_pipe.width.value
        incident_half_length = self.incident_pipe.half_length.value
        if (
            main_radius is None
            or main_width is None
            or incident_half_length is None
            or (main_radius + main_width) > incident_half_length
        ):
            return (
                "The sum of the radius and width of the main pipe "
                "can't be greater than the half length of the incident pipe: "
                f"({main_radius} + {main_width} > "
                f"{incident_half_length})"
            )
        return None

    def _check_incident_radius_not_greater_than_main(self) -> str | None:
        incident_radius = self.incident_pipe.radius.value
        main_radius = self.main_pipe.radius.value
        if incident_radius is None or main_radius is None or incident_radius > main_radius:
            return (
                "The incident radius can't be greater than the main radius: "
                f"({incident_radius} > {main_radius})"
            )
        return None

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
        super().__attrs_post_init__()
        self._init_app_info(title="Pipe Form", extension=".pipe")
        self.pipe_form.edge_type.value_changed.connect(self._display_message_status_bar)

    def _display_message_status_bar(self, value: EdgeType | None) -> None:
        if value is not None:
            self.status_bar.show_message(f"Edge type changed: {value.value}")


class QtPipeApp(QtApplication[PipeMainView]):
    def __init__(self) -> None:
        main_view = PipeMainView()
        super().__init__(main_view=main_view)


class TextualPipeApp(TextualApplication[PipeMainView]):
    def __init__(self) -> None:
        main_view = PipeMainView()
        super().__init__(main_view=main_view)


class WebPipeApp(WebApplication[PipeMainView]):
    def __init__(self) -> None:
        super().__init__(build_main_view=PipeMainView)


def main() -> None:
    # app = QtPipeApp()
    # app = TextualPipeApp()
    app = WebPipeApp()
    app.run()


if __name__ == "__main__":
    main()
