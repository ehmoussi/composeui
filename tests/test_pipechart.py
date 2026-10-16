"""Tests of the example pipechart: a pipe's pressure drop swept along its flow rate."""

import math

from examples.pipechart import SWEEP_POINTS, PipeChartMainView, friction_factor


def test_the_friction_factor_has_no_value_between_laminar_and_turbulent_flow() -> None:
    assert friction_factor(1000, 0.05) == 64 / 1000
    assert math.isnan(friction_factor(3000, 0.05))
    assert 0.01 < friction_factor(1e5, 0.05) < 0.03  # Moody's chart, a steel pipe


def test_each_diameter_has_one_curve_with_a_gap_where_the_flow_is_transitional() -> None:
    view = PipeChartMainView()
    view.add_curve()
    view.pipe.diameter.value = 80
    view.add_curve()
    view.add_curve()  # the same pipe again: its curve is replaced

    assert [series.name for series in view.chart.series] == ["D = 50 mm", "D = 80 mm"]
    curve = view.chart.series[0]
    assert len(curve.x) == SWEEP_POINTS
    gap = [index for index, drop in enumerate(curve.y) if math.isnan(drop)]
    assert gap == list(range(gap[0], gap[-1] + 1))  # one gap, between the two laws
    assert curve.y[-1] > curve.y[gap[-1] + 1] > curve.y[gap[0] - 1]

    view.clear_curves()
    assert view.chart.series == []


def test_a_pipe_without_a_valid_diameter_is_not_plotted() -> None:
    view = PipeChartMainView()
    view.pipe.diameter.value = 0
    view.add_curve()

    assert view.chart.series == []
    assert "Every value must be greater than 0" in view.pipe.log_view.log_message
