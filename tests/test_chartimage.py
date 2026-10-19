"""A chart drawn by matplotlib as a report's figure, the same whatever the backend."""

from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("matplotlib")
import matplotlib as mpl
from matplotlib.lines import Line2D

from composeui.core.chartimage import (
    REFERENCE_LINE_COLOR,
    ImageOptions,
    chart_figure,
    chart_image_bytes,
    image_name,
    save_chart_image,
)
from composeui.core.view import ChartKind, ChartView, ReferenceLine, Series
from examples.pipechart import PipeChartMainView
from tests.charts import ChartPagesMainView

if TYPE_CHECKING:
    from pathlib import Path


def _pipe_chart() -> ChartView:
    view = PipeChartMainView()
    view.add_curve()
    view.pipe.diameter.value = 80
    view.add_curve()
    view.add_measurements()
    return view.chart


def test_the_figure_draws_the_chart_s_series_and_labels() -> None:
    chart = _pipe_chart()

    figure = chart_figure(chart, ImageOptions(x_range=(0.5, 1.5)))

    (axes,) = figure.axes
    assert axes.get_xlabel() == "Flow Rate (L/s)"
    assert axes.get_ylabel() == "Pressure Drop (kPa)"
    assert axes.get_title() == ""  # a report captions its figure itself
    assert axes.get_xlim() == (0.5, 1.5)
    assert (axes.get_xscale(), axes.get_yscale()) == ("linear", "linear")
    # the series', not the pump's reference line, which the legend leaves out
    lines = [line for line in axes.get_lines() if not line.get_label().startswith("_")]
    assert all(isinstance(line, Line2D) for line in lines)
    assert [line.get_label() for line in lines] == [series.name for series in chart.series]
    model, other, measured = lines
    assert model.get_linestyle() != other.get_linestyle()  # told apart in black and white
    assert measured.get_linestyle() == "None"
    assert measured.get_marker() == "^"  # its own marker, the third series
    # the transitional flow's gap stays a gap
    assert any(math.isnan(y) for y in model.get_ydata())
    legend = axes.get_legend()
    assert legend is not None
    assert [text.get_text() for text in legend.get_texts()] == [s.name for s in chart.series]


def test_the_title_and_log_axes_are_drawn_when_asked() -> None:
    chart = ChartView(
        title="Decay",
        x_log=True,
        y_log=True,
        series=[Series(name="Activity", x=[0, 1, 10, 100], y=[1, 1000, -1, 10])],
    )

    (axes,) = chart_figure(chart, ImageOptions(show_title=True)).axes

    assert axes.get_title() == "Decay"
    assert (axes.get_xscale(), axes.get_yscale()) == ("log", "log")
    (line,) = axes.get_lines()
    assert list(line.get_xdata()) == [1, 10, 100]  # no x of 0 on a log axis
    assert math.isnan(line.get_ydata()[1])  # no y of -1 either: a gap


def test_a_bar_chart_draws_a_group_of_bars_per_category() -> None:
    energy = ChartPagesMainView().router.chart.energy
    assert energy.kind is ChartKind.BAR

    (axes,) = chart_figure(energy).axes

    heating, cooling = axes.containers
    assert [bar.get_height() for bar in heating] == [120, 80, 95]
    assert [bar.get_height() for bar in cooling] == [30, 45]  # none in the bedroom
    assert [bar.get_x() + bar.get_width() / 2 for bar in heating] == pytest.approx([-0.2, 0.8, 1.8])
    assert [label.get_text() for label in axes.get_xticklabels()] == [
        "Kitchen",
        "Bedroom",
        "Office",
    ]


def test_many_series_are_named_beside_the_data() -> None:
    chart = ChartView(
        series=[Series(name=f"Run {index}", x=[0, 1], y=[index, index]) for index in range(5)]
    )

    figure = chart_figure(chart)

    assert figure.axes[0].get_legend() is None
    assert len(figure.legends) == 1


def test_a_png_is_as_large_as_its_millimetres_at_its_resolution(tmp_path: Path) -> None:
    path = tmp_path / "pressure.png"

    save_chart_image(_pipe_chart(), path, ImageOptions(width_mm=50.8, height_mm=25.4, dpi=100))

    content = path.read_bytes()
    assert content.startswith(b"\x89PNG")
    width, height = struct.unpack(">II", content[16:24])
    assert (width, height) == (200, 100)  # 2 by 1 inches


def test_vector_images_keep_their_text_as_text(tmp_path: Path) -> None:
    chart = _pipe_chart()
    defaults = dict(mpl.rcParams)

    svg = chart_image_bytes(chart, "svg").decode()
    save_chart_image(chart, tmp_path / "pressure.pdf")

    assert "<text" in svg
    assert "Flow Rate (L/s)" in svg
    pdf = (tmp_path / "pressure.pdf").read_bytes()
    assert pdf.startswith(b"%PDF")
    assert b"/FontFile2" in pdf  # TrueType embedded, not outlines
    assert dict(mpl.rcParams) == defaults  # its settings were its own


def test_an_unknown_format_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="'jpg'"):
        save_chart_image(_pipe_chart(), tmp_path / "pressure.jpg")


def test_an_image_is_named_after_its_chart_s_title() -> None:
    assert image_name("Drop / Flow: 50 mm", "pdf") == "Drop _ Flow_ 50 mm.pdf"
    assert image_name("", "png") == "chart.png"


def test_a_series_of_its_own_color_is_drawn_so_filled_down_to_0() -> None:
    chart = ChartView(
        series=[
            Series(name="Oval", x=[0, 1], y=[1, 1], color="#ffd700", fill=True),
            Series(name="Theme", x=[0, 1], y=[2, 2]),
        ]
    )

    (axes,) = chart_figure(chart).axes

    oval, theme = axes.get_lines()
    assert oval.get_color() == "#ffd700"
    assert theme.get_color() == "#D55E00"  # Okabe and Ito's second
    (filled,) = axes.collections  # the oval's alone
    assert mpl.colors.to_hex(filled.get_facecolor()[0]) == "#ffd700"


def test_reference_lines_are_dashed_labeled_and_in_range() -> None:
    chart = ChartPagesMainView().router.chart.chart  # its lines past its data
    chart.y_log = True
    chart.reference_lines = [*chart.reference_lines, ReferenceLine(-1, "Never")]

    (axes,) = chart_figure(chart).axes

    _inlet, maximum, now = axes.get_lines()
    assert (list(maximum.get_ydata()), list(now.get_xdata())) == ([4.6, 4.6], [2.3, 2.3])
    assert maximum.get_color() == "#d03030"
    assert now.get_color() == REFERENCE_LINE_COLOR
    assert maximum.get_linestyle() == now.get_linestyle() == "--"
    # shown, though past the data; -1, on a log axis, isn't drawn
    assert axes.get_ylim()[1] > 4.6
    assert [text.get_text() for text in axes.texts] == ["Max: 4.6", "Now"]
    legend = axes.get_legend()
    assert legend is not None
    assert [text.get_text() for text in legend.get_texts()] == ["Inlet"]
