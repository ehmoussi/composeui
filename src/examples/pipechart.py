"""A pipe's pressure drop against its flow rate: `python -m examples.pipechart --backend qt`.

Each click on Add Curve sweeps the flow rate through the pipe of the form's diameter and
plots the pressure drop it causes, one curve per diameter, each with its own flow rates.
Between laminar and turbulent flow neither law holds: the curve leaves a gap there. Add
Measurements plots, as dots over the curves, what a test rig measured on that pipe, and
lists them on the Measurements tab beside the chart's, each against the computed drop.
"""

import math
from collections.abc import Callable
from typing import Optional

from attrs import Factory

from composeui.core import application
from composeui.core.registry import RendererType
from composeui.core.view import (
    Align,
    ButtonVariant,
    ButtonView,
    ChartKind,
    ChartView,
    GroupFormView,
    HorizontalView,
    LabelRowFloatInputView,
    MainView,
    ReferenceLine,
    Series,
    TableView,
    TabPage,
    TabView,
    child,
    define_view,
)

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
#: and the ratio of each measured drop to the computed one
MEASUREMENTS = ((0.2, 1.06), (0.35, 0.95), (0.5, 1.03), (0.65, 0.98), (0.8, 1.04), (0.95, 0.97))
#: the pressure the pump gives (kPa): a pipe whose drop is over it can't pass that flow
PUMP_PRESSURE = 20.0


def friction_factor(reynolds: float, diameter: float) -> float:
    """Get Darcy's friction factor, NaN where the flow is transitional."""
    if reynolds < LAMINAR_LIMIT:
        return 64.0 / reynolds
    if reynolds < TURBULENT_LIMIT:
        return math.nan
    # Haaland's explicit approximation of Colebrook's equation
    term = (ROUGHNESS / diameter / 3.7) ** 1.11 + 6.9 / reynolds
    return float((-1.8 * math.log10(term)) ** -2)


def pressure_drop_curve(diameter_mm: float, length: float, max_flow: float) -> Series:
    """Sweep the flow rate (L/s) up to `max_flow` through a pipe; the drop is in kPa."""
    diameter = diameter_mm / 1000
    area = math.pi * diameter**2 / 4
    flows: list[float] = []
    drops: list[float] = []
    for index in range(1, SWEEP_POINTS + 1):
        flow = max_flow * index / SWEEP_POINTS
        velocity = flow / 1000 / area
        reynolds = DENSITY * velocity * diameter / VISCOSITY
        factor = friction_factor(reynolds, diameter)
        flows.append(flow)
        drops.append(factor * length / diameter * DENSITY * velocity**2 / 2 / 1000)
    return Series(name=f"D = {diameter_mm:g} mm", x=flows, y=drops)


def measurements(
    diameter_mm: float, length: float, max_flow: float
) -> list[tuple[float, float, float]]:
    """Get what the test rig measured on a pipe: each flow rate, measured and computed drop."""
    model = pressure_drop_curve(diameter_mm, length, max_flow)
    points: list[tuple[float, float, float]] = []
    for share, ratio in MEASUREMENTS:
        index = round(share * SWEEP_POINTS) - 1
        points.append((model.x[index], model.y[index] * ratio, model.y[index]))
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


@define_view
class MeasurementsTab(TabPage):
    """The rig's measurements, a row each, against the drop the curve computes there."""

    table: TableView = child(
        TableView,
        headers=["Pipe", "Flow Rate (L/s)", "Measured (kPa)", "Computed (kPa)", "Deviation (%)"],
    )


@define_view
class ResultTabs(TabView):
    chart_tab: ChartTab = child(ChartTab, title="Chart")
    measurements_tab: MeasurementsTab = child(MeasurementsTab, title="Measurements")


@define_view
class PipeChartMainView(MainView):
    app_title = "Pipe Chart"
    extension = ".pipechart"

    pipe: PipeForm = Factory(PipeForm)
    buttons: CurveButtons = Factory(CurveButtons)
    results: ResultTabs = Factory(ResultTabs)

    @property
    def chart(self) -> ChartView:
        """The chart, on its tab."""
        return self.results.chart_tab.chart

    @property
    def measurements(self) -> TableView:
        """The measurements' table, on its tab."""
        return self.results.measurements_tab.table

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.buttons.add.clicked.connect(self.add_curve)
        self.buttons.measure.clicked.connect(self.add_measurements)
        self.buttons.clear.clicked.connect(self.clear_curves)

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
        rows = [
            [
                name,
                f"{flow:.3g}",
                f"{measured:.3g}",
                f"{computed:.3g}",
                f"{(measured - computed) / computed * 100:+.1f}",
            ]
            for flow, measured, computed in measurements(diameter, length, max_flow)
        ]
        others = [row for row in self.measurements.rows if row[0] != name]
        self.measurements.rows = [*others, *rows]

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
        others = [series for series in self.chart.series if series.name != curve.name]
        self.chart.series = [*others, curve]
        return diameter, length, max_flow

    def clear_curves(self) -> None:
        self.chart.series = []
        self.measurements.rows = []


def main() -> None:
    application.run(PipeChartMainView, default_backend=RendererType.QT)


if __name__ == "__main__":
    main()
