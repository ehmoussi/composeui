"""A pipe form, runnable on every backend: `python -m examples.pipeform --backend qt`."""

from __future__ import annotations

import argparse
import enum
import functools
import sys
from pathlib import Path

import attrs
from attrs import Factory

from composeui.core.view import (
    OMIT,
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
        self.radius.label = self.tr("Radius")
        self.width.label = self.tr("Width")
        self.half_length.label = self.tr("Half Length")
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
        self.label = self.tr("Edge Type")
        self.values = {self.tr(edge_type.value): edge_type for edge_type in EdgeType}
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
        self.label = self.tr("Material")
        self.values = {self.tr(material.value): material for material in Material}
        self.value = Material.Steel


@define_view
class InsulatedView(LabelRowCheckBoxView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = self.tr("Insulation")
        self.text = self.tr("Insulated pipe")


@define_view
class ChamferDimensionView(GroupFormView):
    height: DimensionInputView = Factory(DimensionInputView)
    width: DimensionInputView = Factory(DimensionInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Chamfer")
        self.height.label = self.tr("Height")
        self.width.label = self.tr("Width")


@define_view
class FilletDimensionView(GroupFormView):
    radius: DimensionInputView = Factory(DimensionInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Fillet")
        self.radius.label = self.tr("Radius")


@define_view
class PipeNameRowView(LabelRowInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = self.tr("Name")
        self.set_validator(self._check_name, self.text_edited)
        self.run_validator()

    def _check_name(self) -> str | None:
        return self.tr("A name is mandatory") if self.text == "" else None


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
        self.insulation_thickness.label = self.tr("Insulation Thickness")
        self.main_pipe.title = self.tr("Main Pipe")
        self.incident_pipe.title = self.tr("Incident Pipe")
        # Insulation: its thickness only matters for an insulated pipe
        self.insulation_thickness.value = 10.0
        self.insulated.toggled.connect(self._enable_insulation_thickness)
        self._enable_insulation_thickness(self.insulated.is_checked)
        # Main Pipe
        self.main_pipe.radius.value = 50.0
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
            message = self.tr(
                "The sum of the radius and width of the main pipe can't be greater than "
                "the half length of the incident pipe: ({radius} + {width} > {half_length})"
            )
            return message.format(
                radius=main_radius, width=main_width, half_length=incident_half_length
            )
        return None

    def _check_incident_radius_not_greater_than_main(self) -> str | None:
        incident_radius = self.incident_pipe.radius.value
        main_radius = self.main_pipe.radius.value
        if incident_radius is None or main_radius is None or incident_radius > main_radius:
            message = self.tr(
                "The incident radius can't be greater than the main radius: "
                "({incident_radius} > {main_radius})"
            )
            return message.format(incident_radius=incident_radius, main_radius=main_radius)
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
        self.title = self.tr("Inputs")


@define_view
class ResultsPageView(PageView):
    #: both pipes' dimensions side by side, read-only
    summary: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_route("results")
        self.title = self.tr("Results")
        self.summary.headers = [
            self.tr(header) for header in ("Pipe", "Radius", "Width", "Half Length")
        ]


@define_view
class PipePagesView(Router):
    inputs: InputsPageView = Factory(InputsPageView)
    results: ResultsPageView = Factory(ResultsPageView)


@define_view
class PipeMenu(Menu):
    reset_dimensions: ActionView = Factory(ActionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Pipe")
        self.reset_dimensions.text = self.tr("Reset Dimensions")
        self.reset_dimensions.shortcut = "Ctrl+r"


@define_view
class LanguageMenu(Menu):
    english: ActionView = Factory(ActionView)
    french: ActionView = Factory(ActionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Language")
        # each language named in itself, whatever the app's: never translated
        for action, language, name, shortcut in (
            (self.english, "en", "English", "Ctrl+Shift+e"),
            (self.french, "fr", "Français", "Ctrl+Shift+f"),
        ):
            action.data = language
            action.text = name
            action.shortcut = shortcut
            action.is_checkable = True

    @property
    def actions(self) -> tuple[ActionView, ...]:
        return (self.english, self.french)

    def check(self, language: str) -> None:
        """Check the action of `language`: "fr-CA" checks French."""
        base = language.replace("_", "-").split("-")[0]
        for action in self.actions:
            action.is_checked = action.data == base


@define_view
class ResetDimensionsDialog(DialogView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.kind = DialogKind.CONFIRM
        self.title = self.tr("Reset the dimensions")
        self.text = self.tr("Both pipes go back to their starting dimensions.")
        self.accept_text = self.tr("Reset")


@define_view
class PipeMainView(MainView):
    translations_dir = Path(__file__).parent / "locales" / "pipeform"

    pipe_menu: PipeMenu = Factory(PipeMenu)
    # the app's language, not study data: never saved, loaded or reset
    language_menu: LanguageMenu = attrs.field(factory=LanguageMenu, metadata={OMIT: True})
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
        for action in self.language_menu.actions:
            action.triggered.connect(functools.partial(self.set_language, action.data))
        self.language_menu.check(self.language)
        self._update_summary()

    def set_language(self, language: str) -> None:
        super().set_language(language)
        self.language_menu.check(self.language)

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
        self.status_bar.show_message(self.tr("Dimensions reset"))

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
            message = self.tr("Edge type changed: {edge_type}")
            self.status_bar.show_message(message.format(edge_type=self.tr(value.value)))


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
