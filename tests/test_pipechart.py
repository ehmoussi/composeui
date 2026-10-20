"""Tests of the example pipechart: a pipe's pressure drop swept along its flow rate."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest

from composeui.core.view import CellStyle, ChartKind, NodeMark
from examples.pipechart import (
    MEASUREMENTS,
    NAN_COLOR,
    SWEEP_POINTS,
    WARNING_COLOR,
    PipeChartMainView,
    friction_factor,
)

if TYPE_CHECKING:
    from pathlib import Path


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


def test_the_measurements_tab_lists_each_measured_drop_against_the_computed_one() -> None:
    view = PipeChartMainView()
    view.add_measurements()
    view.pipe.diameter.value = 80
    view.add_measurements()
    view.pipe.diameter.value = 50
    view.add_measurements()  # the same pipe again: its rows are replaced

    rows = view.measurements.rows
    count = len(MEASUREMENTS)
    assert [row[0] for row in rows] == ["D = 80 mm"] * count + ["D = 50 mm"] * count
    # each point as plotted, its deviation the rig's ratio to the computed drop; the first
    # is in transitional flow, where the model computes none
    measured = next(s for s in view.chart.series if s.name == "Measured, D = 50 mm")
    assert [float(row[2]) for row in rows[count:]] == pytest.approx(measured.y, rel=1e-2)
    assert [row[4] for row in rows[count:]] == [
        "NaN",
        *(f"{(r - 1) * 100:+.1f}" for _, r in MEASUREMENTS[1:]),
    ]

    view.clear_curves()
    assert view.measurements.rows == []


def test_the_curves_tab_shows_hides_and_draws_each_curve(tmp_path: Path) -> None:
    view = PipeChartMainView()
    view.add_curve()
    view.add_measurements()
    curves = view.curves
    assert curves.rows == [["True", "D = 50 mm", "Line"], ["True", "Measured, D = 50 mm", "Dots"]]

    # hidden, the curve leaves the chart; checked again, it comes back
    curves.emit_cell_edited(0, 0, "False")
    assert [series.name for series in view.chart.series] == ["Measured, D = 50 mm"]
    curves.check_all(0, is_checked=True)
    assert [series.name for series in view.chart.series] == ["D = 50 mm", "Measured, D = 50 mm"]
    curves.emit_cell_edited(0, 2, "Steps")
    curves.emit_cell_edited(1, 2, "Line")
    computed, measured = view.chart.series
    assert (computed.kind, computed.step) == (None, True)
    assert (measured.kind, measured.step) == (None, False)

    # a study keeps the curves hidden, to show them again once loaded
    curves.check_all(0, is_checked=False)
    assert view.chart.series == []
    path = tmp_path / "study.pipechart"
    view.save_state(path)
    loaded = PipeChartMainView()
    loaded.load_state(path)
    loaded.curves.emit_cell_edited(1, 0, "True")
    (shown,) = loaded.chart.series
    assert (shown.name, shown.kind) == ("Measured, D = 50 mm", None)

    view.clear_curves()
    assert (view.curves.rows, view.chart.series) == ([], [])
    view.add_measurements()
    assert view.chart.series[0].kind is ChartKind.SCATTER


def test_the_measurements_show_what_the_model_can_t_compute_and_sum_those_kept_up(
    tmp_path: Path,
) -> None:
    view = PipeChartMainView()
    view.add_measurements()
    table, count = view.measurements, len(MEASUREMENTS)
    styles = table.cell_styles
    # the pipe's cell over its measurements
    assert styles[0, 0] == CellStyle(row_span=count)
    # no computed drop: in red, and not kept, nor can it be
    assert (styles[0, 3].background, styles[0, 4].background) == (NAN_COLOR, NAN_COLOR)
    assert (table.rows[0][5], table.is_cell_editable(0, 5)) == ("False", False)
    # a deviation over 10 % marked
    assert styles[5, 4] == CellStyle(background=WARNING_COLOR, mark=NodeMark.WARNING)
    assert view.summary.rows == [["6 of 7"], ["+1.8"], ["+12.0"]]

    # unchecking the measurement off the model leaves it out of the summary
    table.emit_cell_edited(5, 5, "False")
    assert view.summary.rows == [["5 of 7"], ["-0.2"], ["+6.0"]]
    table.check_all(5, is_checked=False)
    assert view.summary.rows == [["0 of 7"], ["NaN"], ["NaN"]]

    # an opened study shows its measurements as they look
    view.save_state(tmp_path / "study.pipechart")
    loaded = PipeChartMainView()
    loaded.load_state(tmp_path / "study.pipechart")
    assert loaded.measurements.cell_styles == styles
    assert loaded.summary.rows == [["0 of 7"], ["NaN"], ["NaN"]]
    loaded.reset_state()
    assert (loaded.measurements.cell_styles, loaded.summary.rows[0]) == ({}, ["0 of 0"])
