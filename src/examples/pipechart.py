"""A pipe's pressure drop against its flow rate: `python -m examples.pipechart --backend qt`.

Each click on Add Curve sweeps the flow rate through the pipe of the form's diameter and
plots the pressure drop it causes, one curve per diameter, each with its own flow rates.
Between laminar and turbulent flow neither law holds: the curve leaves a gap there. Add
Measurements plots, as dots over the curves, what a test rig measured on that pipe, and
lists them on the Measurements tab beside the chart's, each against the computed drop: a
drop the model can't compute in red, a deviation over 10 % marked in orange. The rows kept
make the summary below them; one without a computed drop can't be kept. The Curves tab
lists every curve: a check box shows or hides it (its header's, all of them), and a
combobox draws it as a line, in steps or as dots.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Optional

import attrs
from attrs import Factory, evolve

from composeui.core import application
from composeui.core.registry import RendererType
from composeui.core.view import (
    CHECKED_TEXTS,
    Align,
    ButtonVariant,
    ButtonView,
    CellStyle,
    CellWidget,
    ChartKind,
    ChartView,
    Column,
    GroupFormView,
    HeaderGroup,
    HorizontalView,
    LabelRowFloatInputView,
    MainView,
    NodeMark,
    RecordTableView,
    ReferenceLine,
    Series,
    TableView,
    TabPage,
    TabView,
    child,
    define_view,
    replace_cell,
)

if TYPE_CHECKING:
    from collections.abc import Callable

#: water at 20 °C
DENSITY = 998.0  # kg/m3
VISCOSITY = 1.0e-3  # Pa.s
#: a commercial steel pipe's roughness
ROUGHNESS = 0.045e-3  # m
#: the Reynolds numbers between which the flow is neither laminar nor turbulent
LAMINAR_LIMIT = 2300.0
TURBULENT_LIMIT = 4000.0
#: the flow rates a sweep computes
SWEEP_POINTS = 200
#: the test rig's measurements of a pipe, as the shares of its maximum flow rate measured
#: and the ratio of each measured drop to the one the flow's law gives; the first is in
#: transitional flow for the default pipe, where the model computes no drop
MEASUREMENTS = (
    (0.06, 1.0),
    (0.2, 1.06),
    (0.35, 0.95),
    (0.5, 1.03),
    (0.65, 0.98),
    (0.8, 1.12),
    (0.95, 0.97),
)
#: the deviation (%) from the computed drop over which a measurement is marked
DEVIATION_WARNING = 10.0
#: a cell's background: a drop the model can't compute, a deviation over the warning's
NAN_COLOR = "#dc2626"
WARNING_COLOR = "#fed7aa"
#: the pressure the pump gives (kPa): a pipe whose drop is over it can't pass that flow
PUMP_PRESSURE = 20.0
#: how a curve is drawn, by the text its "Drawn as" cell shows: its kind and whether in steps
DRAWINGS: dict[str, tuple[Optional[ChartKind], bool]] = {
    "Line": (None, False),
    "Steps": (None, True),
    "Dots": (ChartKind.SCATTER, False),
}


def friction_factor(reynolds: float, diameter: float) -> float:
    """Get Darcy's friction factor, NaN where the flow is transitional."""
    if reynolds < LAMINAR_LIMIT:
        return 64.0 / reynolds
    if reynolds < TURBULENT_LIMIT:
        return math.nan
    return turbulent_friction_factor(reynolds, diameter)


def turbulent_friction_factor(reynolds: float, diameter: float) -> float:
    """Get Darcy's friction factor in turbulent flow."""
    # Haaland's explicit approximation of Colebrook's equation
    term = (ROUGHNESS / diameter / 3.7) ** 1.11 + 6.9 / reynolds
    return float((-1.8 * math.log10(term)) ** -2)


def rig_friction_factor(reynolds: float, diameter: float) -> float:
    """Get the friction factor the rig's flow has: as turbulent, once no longer laminar."""
    if reynolds < LAMINAR_LIMIT:
        return 64.0 / reynolds
    return turbulent_friction_factor(reynolds, diameter)


def pressure_drop(
    flow: float,
    diameter_mm: float,
    length: float,
    factor: Callable[[float, float], float] = friction_factor,
) -> float:
    """Get the pressure drop (kPa) of a flow rate (L/s) through a pipe."""
    diameter = diameter_mm / 1000
    velocity = flow / 1000 / (math.pi * diameter**2 / 4)
    reynolds = DENSITY * velocity * diameter / VISCOSITY
    return factor(reynolds, diameter) * length / diameter * DENSITY * velocity**2 / 2 / 1000


def pressure_drop_curve(diameter_mm: float, length: float, max_flow: float) -> Series:
    """Sweep the flow rate (L/s) up to `max_flow` through a pipe; the drop is in kPa."""
    flows = [max_flow * index / SWEEP_POINTS for index in range(1, SWEEP_POINTS + 1)]
    drops = [pressure_drop(flow, diameter_mm, length) for flow in flows]
    return Series(name=f"D = {diameter_mm:g} mm", x=flows, y=drops)


def measurements(
    diameter_mm: float, length: float, max_flow: float
) -> list[tuple[float, float, float]]:
    """Get what the test rig measured on a pipe: each flow rate, measured and computed drop.

    The computed drop is NaN in transitional flow, where the model holds no law.
    """
    points: list[tuple[float, float, float]] = []
    for share, ratio in MEASUREMENTS:
        flow = max_flow * round(share * SWEEP_POINTS) / SWEEP_POINTS
        measured = pressure_drop(flow, diameter_mm, length, rig_friction_factor) * ratio
        points.append((flow, measured, pressure_drop(flow, diameter_mm, length)))
    return points


def measured_drops(diameter_mm: float, length: float, max_flow: float) -> Series:
    """Get what the test rig measured on a pipe: dots near its computed curve."""
    points = measurements(diameter_mm, length, max_flow)
    return Series(
        name=f"Measured, D = {diameter_mm:g} mm",
        x=[flow for flow, _, _ in points],
        y=[measured for _, measured, _ in points],
        kind=ChartKind.SCATTER,
    )


@define_view
class PositiveInputView(LabelRowFloatInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.minimum = 0


@define_view
class PipeForm(GroupFormView):
    diameter: PositiveInputView = child(PositiveInputView, label="Diameter (mm)", value=50)
    length: PositiveInputView = child(PositiveInputView, label="Length (m)", value=100)
    max_flow: PositiveInputView = child(PositiveInputView, label="Maximum Flow Rate (L/s)", value=2)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Pipe"
        rows = (self.diameter, self.length, self.max_flow)
        self.add_validator(self._check_positive, *(row.editing_finished for row in rows), rows=rows)

    def _check_positive(self) -> Optional[str]:
        values = (self.diameter.value, self.length.value, self.max_flow.value)
        if any(value is None or value <= 0 for value in values):
            return "Every value must be greater than 0"
        return None


@define_view
class CurveButtons(HorizontalView):
    align = Align.END
    add: ButtonView = child(ButtonView, text="Add Curve")
    measure: ButtonView = child(
        ButtonView, text="Add Measurements", variant=ButtonVariant.SECONDARY
    )
    clear: ButtonView = child(ButtonView, text="Clear", variant=ButtonVariant.DANGER)


@define_view
class ChartTab(TabPage):
    chart: ChartView = child(
        ChartView,
        title="Pressure Drop",
        x_title="Flow Rate",
        x_unit="L/s",
        y_title="Pressure Drop",
        y_unit="kPa",
        reference_lines=[ReferenceLine(PUMP_PRESSURE, f"Pump: {PUMP_PRESSURE:g} kPa")],
    )


@attrs.frozen
class Measurement:
    """A drop the rig measured on a pipe, against the one the model computes there.

    Its numbers are rounded as the table shows them.
    """

    pipe: str
    #: the flow rate (L/s)
    flow: float
    #: the pressure drops (kPa); the computed one is NaN where the model holds no law
    measured: float
    computed: float
    #: how far (%) the measured drop is from the computed one
    deviation: float
    #: whether the summary counts it
    kept: bool = True


MEASUREMENT_COLUMNS = [
    Column("pipe", "Pipe"),
    Column("flow", "Flow Rate (L/s)"),
    Column("measured", "Measured"),
    Column("computed", "Computed"),
    Column("deviation", "Deviation (%)"),
    Column("kept", "Kept", editable=True, widget=CellWidget.check_box(check_all=True)),
]


def column_index(field: str) -> int:
    """Get the index of the measurements' column showing `field`."""
    return next(index for index, column in enumerate(MEASUREMENT_COLUMNS) if column.field == field)


@define_view
class MeasurementsTab(TabPage):
    """The rig's measurements, a row each, against the drop the curve computes there.

    Under them, a summary of those kept, a row each: its header, then its value.
    """

    table: RecordTableView[Measurement] = child(
        RecordTableView[Measurement],
        columns=MEASUREMENT_COLUMNS,
        header_groups=[HeaderGroup("Pressure Drop (kPa)", column_index("measured"), 2)],
    )
    summary: TableView = child(
        TableView,
        headers=["Value"],
        row_headers=["Measurements Kept", "Mean Deviation (%)", "Largest Deviation (%)"],
    )


@define_view
class CurvesTab(TabPage):
    """Each curve plotted, a row each: shown or not, and how it's drawn."""

    table: TableView = child(
        TableView,
        headers=["Shown", "Curve", "Drawn as"],
        editable_columns=[0, 2],
        cell_widgets={
            0: CellWidget.check_box(check_all=True),
            2: CellWidget.combobox(DRAWINGS),
        },
    )


@define_view
class ResultTabs(TabView):
    chart_tab: ChartTab = child(ChartTab, title="Chart")
    measurements_tab: MeasurementsTab = child(MeasurementsTab, title="Measurements")
    curves_tab: CurvesTab = child(CurvesTab, title="Curves")


@define_view
class PipeChartMainView(MainView):
    app_title = "Pipe Chart"
    extension = ".pipechart"

    pipe: PipeForm = Factory(PipeForm)
    buttons: CurveButtons = Factory(CurveButtons)
    results: ResultTabs = Factory(ResultTabs)
    #: every curve plotted, as computed, the hidden ones too: the chart draws the others
    _curves: list[Series] = Factory(list)

    @property
    def chart(self) -> ChartView:
        """The chart, on its tab."""
        return self.results.chart_tab.chart

    @property
    def measurements(self) -> RecordTableView[Measurement]:
        """The measurements' table, on its tab."""
        return self.results.measurements_tab.table

    @property
    def curves(self) -> TableView:
        """The curves' table, on its tab."""
        return self.results.curves_tab.table

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.buttons.add.clicked.connect(self.add_curve)
        self.buttons.measure.clicked.connect(self.add_measurements)
        self.buttons.clear.clicked.connect(self.clear_curves)
        self.curves.cell_edited.connect(self._edit_curve)
        self.measurements.record_edited.connect(self._keep_measurement)
        self._show_measurements()

    @property
    def summary(self) -> TableView:
        """The summary of the measurements kept, under them."""
        return self.results.measurements_tab.summary

    def load_state_data(self, data: Any) -> None:
        super().load_state_data(data)
        self._show_measurements()  # their looks follow from them, never saved

    def reset_state(self) -> None:
        super().reset_state()
        self._show_measurements()

    def add_curve(self) -> None:
        """Plot the form's pipe, replacing the curve of a pipe of the same diameter."""
        self._plot(pressure_drop_curve)

    def add_measurements(self) -> None:
        """Plot and list what the rig measured on the form's pipe, replacing earlier ones."""
        pipe = self._plot(measured_drops)
        if pipe is None:
            return
        diameter, length, max_flow = pipe
        name = f"D = {diameter:g} mm"
        added = [
            Measurement(
                name,
                _rounded(flow),
                _rounded(measured),
                _rounded(computed),
                round((measured - computed) / computed * 100, 1),
                # one the model can't compute can't be compared with it
                kept=not math.isnan(computed),
            )
            for flow, measured, computed in measurements(diameter, length, max_flow)
        ]
        others = [record for record in self.measurements.records if record.pipe != name]
        self.measurements.records = [*others, *added]
        self._show_measurements()

    def _keep_measurement(self, old: Measurement, new: Measurement) -> None:
        """Keep a measurement in the summary or not, as its Kept box says."""
        records = self.measurements.records
        self.measurements.records = [new if record is old else record for record in records]
        self._show_measurements()

    def _show_measurements(self) -> None:
        """Color, mark and group the measurements, and sum those kept up."""
        records = self.measurements.records
        pipe, computed, deviation, kept = map(
            column_index, ("pipe", "computed", "deviation", "kept")
        )
        styles: dict[tuple[int, int], CellStyle] = {}
        for index, record in enumerate(records):
            if index == 0 or records[index - 1].pipe != record.pipe:
                # the pipe's cell over its measurements, which follow each other
                end = next(
                    (end for end in range(index, len(records)) if records[end].pipe != record.pipe),
                    len(records),
                )
                styles[index, pipe] = CellStyle(row_span=end - index)
            if math.isnan(record.computed):
                styles[index, computed] = CellStyle(background=NAN_COLOR)
                styles[index, deviation] = CellStyle(background=NAN_COLOR)
                styles[index, kept] = CellStyle(is_disabled=True)
            elif abs(record.deviation) > DEVIATION_WARNING:
                styles[index, deviation] = CellStyle(
                    background=WARNING_COLOR, mark=NodeMark.WARNING
                )
        deviations = [record.deviation for record in records if record.kept]
        self.measurements.cell_styles = styles
        largest = max(deviations, key=abs, default=math.nan)
        mean = sum(deviations) / len(deviations) if deviations else math.nan
        self.summary.rows = [
            [f"{len(deviations)} of {len(records)}"],
            [_number(mean, "+.1f")],
            [_number(largest, "+.1f")],
        ]

    def _plot(
        self, compute: Callable[[float, float, float], Series]
    ) -> Optional[tuple[float, float, float]]:
        """Plot the form's pipe with `compute`; return its diameter, length and maximum flow.

        None, without plotting, when the form can't be plotted.
        """
        self.pipe.validate()  # shows why, when the form can't be plotted
        diameter, length = self.pipe.diameter.value, self.pipe.length.value
        max_flow = self.pipe.max_flow.value
        if diameter is None or length is None or max_flow is None:
            return None
        if min(diameter, length, max_flow) <= 0:
            return None
        curve = compute(diameter, length, max_flow)
        self._curves = [*(other for other in self._curves if other.name != curve.name), curve]
        drawing = "Dots" if curve.kind is ChartKind.SCATTER else "Line"
        others = [row for row in self.curves.rows if row[1] != curve.name]
        self.curves.rows = [*others, [CHECKED_TEXTS[True], curve.name, drawing]]
        self._draw()
        return diameter, length, max_flow

    def _edit_curve(self, row: int, column: int, text: str) -> None:
        """Show, hide or draw a curve as the user's edit says."""
        self.curves.rows = replace_cell(self.curves.rows, row, column, text)
        self._draw()

    def _draw(self) -> None:
        """Draw the curves shown, each as its row says, in the rows' order."""
        curves = {curve.name: curve for curve in self._curves}
        series = []
        for shown, name, drawing in self.curves.rows:
            if shown == CHECKED_TEXTS[True] and name in curves:
                kind, step = DRAWINGS.get(drawing, (curves[name].kind, curves[name].step))
                series.append(evolve(curves[name], kind=kind, step=step))
        self.chart.series = series

    def clear_curves(self) -> None:
        self._curves = []
        self.curves.rows = []
        self.chart.series = []
        self.measurements.records = []
        self._show_measurements()


def _rounded(value: float) -> float:
    """Round a number to the 3 significant digits the table shows."""
    return float(f"{value:.3g}")


def _number(value: float, spec: str) -> str:
    """Show a number as `spec` formats it, NaN as "NaN" rather than "nan" or "+nan"."""
    return "NaN" if math.isnan(value) else format(value, spec)


def main() -> None:
    application.run(PipeChartMainView, default_backend=RendererType.QT)


if __name__ == "__main__":
    main()
