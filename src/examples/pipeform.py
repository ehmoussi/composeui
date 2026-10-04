"""A pipe form, runnable on every backend: `python -m examples.pipeform --backend qt`."""

from __future__ import annotations

import argparse
import enum
import sys

from attrs import Factory

from composeui.core.view import (
    ActionView,
    DialogKind,
    DialogView,
    FormView,
    GroupFormView,
    LabelRowCheckBoxView,
    LabelRowComboboxView,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelRowRadioGroupView,
    MainView,
    Menu,
    PageView,
    Router,
    TableView,
    define_view,
)


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

    @property
    def dimensions(self) -> tuple[DimensionInputView, ...]:
        return (self.radius, self.width, self.half_length)


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
class InsulatedView(LabelRowCheckBoxView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Insulation"
        self.text = "Insulated pipe"


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
    insulated: InsulatedView = Factory(InsulatedView)
    insulation_thickness: DimensionInputView = Factory(DimensionInputView)

    main_pipe: PipeDimensionView = Factory(PipeDimensionView)
    incident_pipe: PipeDimensionView = Factory(PipeDimensionView)

    edge_type: EdgeTypeView = Factory(EdgeTypeView)

    chamfer: ChamferDimensionView = Factory(ChamferDimensionView)
    fillet: FilletDimensionView = Factory(FilletDimensionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # Insulation: its thickness only matters for an insulated pipe
        self.insulation_thickness.label = "Insulation Thickness"
        self.insulation_thickness.value = 10.0
        self.insulated.toggled.connect(self._enable_insulation_thickness)
        self._enable_insulation_thickness(self.insulated.is_checked)
        # Main Pipe
        self.main_pipe.title = "Main Pipe"
        self.main_pipe.radius.value = 50.0
        # Incident Pipe
        self.incident_pipe.title = "Incident Pipe"
        # two independent cross-field checks, combined into one shared `log_view`
        # each names the rows it is about: their fields show as invalid while it fails
        self.add_validator(
            self._check_main_pipe_fits_incident,
            self.main_pipe.radius.editing_finished,
            self.main_pipe.width.editing_finished,
            self.incident_pipe.half_length.editing_finished,
            rows=(self.main_pipe.radius, self.main_pipe.width, self.incident_pipe.half_length),
        )
        self.add_validator(
            self._check_incident_radius_not_greater_than_main,
            self.incident_pipe.radius.editing_finished,
            self.main_pipe.radius.editing_finished,
            rows=(self.incident_pipe.radius, self.main_pipe.radius),
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

    def _enable_insulation_thickness(self, is_insulated: bool) -> None:
        self.insulation_thickness.is_enabled = is_insulated

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
class InputsPageView(PageView):
    pipe_form: PipeFormView = Factory(PipeFormView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_route("inputs")
        self.title = "Inputs"


@define_view
class ResultsPageView(PageView):
    #: both pipes' dimensions side by side, read-only
    summary: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_route("results")
        self.title = "Results"
        self.summary.headers = ["Pipe", "Radius", "Width", "Half Length"]


@define_view
class PipePagesView(Router):
    inputs: InputsPageView = Factory(InputsPageView)
    results: ResultsPageView = Factory(ResultsPageView)


@define_view
class PipeMenu(Menu):
    reset_dimensions: ActionView = Factory(ActionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Pipe"
        self.reset_dimensions.text = "Reset Dimensions"
        self.reset_dimensions.shortcut = "Ctrl+r"


@define_view
class ResetDimensionsDialog(DialogView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.kind = DialogKind.CONFIRM
        self.title = "Reset the dimensions"
        self.text = "Both pipes go back to their starting dimensions."
        self.accept_text = "Reset"


@define_view
class PipeMainView(MainView):
    pipe_menu: PipeMenu = Factory(PipeMenu)
    pages: PipePagesView = Factory(PipePagesView)
    confirm_reset: ResetDimensionsDialog = Factory(ResetDimensionsDialog)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Pipe Form", extension=".pipe")
        pipe_form = self.pages.inputs.pipe_form
        pipe_form.edge_type.value_changed.connect(self._display_message_status_bar)
        for pipe in (pipe_form.main_pipe, pipe_form.incident_pipe):
            for dimension in pipe.dimensions:
                dimension.editing_finished.connect(self._update_summary)
        # the dimensions are only reset once the user confirms
        self.pipe_menu.reset_dimensions.triggered.connect(self.confirm_reset.open)
        self.confirm_reset.accepted.connect(self._reset_dimensions)
        self._update_summary()

    def _reset_dimensions(self) -> None:
        pipe_form = self.pages.inputs.pipe_form
        initial = PipeFormView()
        for pipe, initial_pipe in (
            (pipe_form.main_pipe, initial.main_pipe),
            (pipe_form.incident_pipe, initial.incident_pipe),
        ):
            for dimension, initial_dimension in zip(pipe.dimensions, initial_pipe.dimensions):
                dimension.value = initial_dimension.value
        # set in code, the values finish no editing: check and summarize them here
        pipe_form.validate()
        self._update_summary()
        self.status_bar.show_message("Dimensions reset")

    def _update_summary(self) -> None:
        def text(value: float | None) -> str:
            return "" if value is None else f"{value:g}"

        pipe_form = self.pages.inputs.pipe_form
        self.pages.results.summary.rows = [
            [
                pipe.title,
                text(pipe.radius.value),
                text(pipe.width.value),
                text(pipe.half_length.value),
            ]
            for pipe in (pipe_form.main_pipe, pipe_form.incident_pipe)
        ]

    def _display_message_status_bar(self, value: EdgeType | None) -> None:
        if value is not None:
            self.status_bar.show_message(f"Edge type changed: {value.value}")


def main() -> None:
    # every app parses `sys.argv` itself when it runs (`-f`, `--debug`, `--port`, ...), so
    # take `--backend` out and leave the rest, `--help` included, to the chosen app
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--backend", choices=["qt", "textual", "web"], default="web")
    args, rest = parser.parse_known_args()
    sys.argv = [sys.argv[0], *rest]
    # imported only once chosen, so importing the views (as the tests do) or running one
    # backend doesn't need the other backends' extras
    if args.backend == "qt":
        from composeui.qtcore.qtapplication import QtApplication  # noqa: PLC0415

        QtApplication(main_view=PipeMainView()).run()
    elif args.backend == "textual":
        from composeui.textualcore.textualapplication import TextualApplication  # noqa: PLC0415

        TextualApplication(main_view=PipeMainView()).run()
    else:
        from composeui.webcore.webapplication import WebApplication  # noqa: PLC0415

        WebApplication(build_main_view=PipeMainView).run()


if __name__ == "__main__":
    main()
