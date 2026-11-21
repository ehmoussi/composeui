"""Tests of the Textual chart."""

from __future__ import annotations

import attrs
import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

import math
import re
from typing import TYPE_CHECKING, Protocol, cast

from composeui.core import chartimage
from composeui.core.registry import RendererType
from composeui.core.view import (
    ChartKind,
    ReferenceLine,
    Scale,
    Series,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composechart import ComposeChart
from examples.batman import BatmanMainView
from examples.pipechart import MEASUREMENTS, PipeChartMainView
from tests.charts import ChartPagesMainView
from tests.textualcore.support import _app_of, _names, _widget

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_the_chart_draws_its_titles_and_series() -> None:
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        view.add_curve()
        view.chart.series = [
            *view.chart.series,
            Series.line("Measured", [0.5, 1, 1.5], [1, math.nan, 3]),
        ]
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        assert "Pressure Drop" in text
        assert "Flow Rate (L/s)" in text
        assert "Pressure Drop (kPa)" in text
        assert "D = 50 mm" in text
        assert "Measured" in text
        view.chart.x = attrs.evolve(view.chart.x, unit="m3/h")
        view.chart.series = []
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        assert "Flow Rate (m3/h)" in text
        assert "D = 50 mm" not in text


class _PlotMonitor(Protocol):
    label: list[str | None]
    lines: list[bool]
    x: list[list[float]]
    y: list[list[float]]
    xscale: list[str]
    yscale: list[str]
    #: by the y axis' side: the left's, then the right's
    ylabel: list[str | None]
    #: each plot's y axis: "left" or "right"
    yside: list[str]
    hcoord: list[list[float]]
    vcoord: list[list[float]]
    #: the ranges drawn, by side: the bottom's then the top's, the left's then the right's
    xlim: list[list[float]]
    ylim: list[list[float]]
    hcolors: list[list[tuple[int, int, int]]]
    color: list[list[tuple[int, int, int]]]
    fillx: list[float | bool]


class _PlotFigure(Protocol):
    _active: _PlotFigure
    monitor: _PlotMonitor


def _plot_monitor(chart: ComposeChart) -> _PlotMonitor:
    # textual-plotext's stubs omit the private state these rendering checks inspect.
    figure = cast("_PlotFigure", chart.plt)
    return figure._active.monitor  # noqa: SLF001 (plotext has no public monitor API)


@pytest.mark.asyncio
async def test_a_series_fill_color_paints_its_area_under_a_line_of_its_own_color() -> None:
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        view.chart.series = [
            Series.line("Load", [0, 1], [1, 1], color="#6096dd", fill=True, fill_color="#e2ebf7")
        ]
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        plotted = _plot_monitor(chart)
        area, line = (0xE2, 0xEB, 0xF7), (0x60, 0x96, 0xDD)
        assert [colors[0] for colors in plotted.color] == [area, line]
        assert [fill is not False for fill in plotted.fillx] == [True, False]  # the line is last
        assert text.count("Load") == 1  # one entry in the legend


@pytest.mark.asyncio
async def test_a_scatter_series_is_plotted_as_dots() -> None:
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        view.add_curve()
        view.add_measurements()
        await pilot.pause()
        chart.render()  # plotext's figure of the view now, not of the last paint
        plotted = _plot_monitor(chart)
        assert plotted.label == ["D = 50 mm", "Measured, D = 50 mm"]
        assert plotted.lines == [True, False]  # a line, then dots
        assert len(plotted.x[1]) == len(MEASUREMENTS)
        view.chart.series = [
            attrs.evolve(curve, kind=ChartKind.SCATTER) for curve in view.chart.series
        ]
        await pilot.pause()
        chart.render()  # plotext's figure of the view now, not of the last paint
        assert _plot_monitor(chart).lines == [False, False]


@pytest.mark.asyncio
async def test_a_bar_chart_plots_a_bar_per_series_in_each_category() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    energy = view.router.chart.energy
    assert isinstance(energy.renderer, TextualWidgetRenderer)
    chart = energy.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        view.router.current_route = "chart"
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        for name in ("Heating", "Cooling", "Kitchen", "Bedroom", "Office", "Energy"):
            assert name in text
        assert "120" in text  # the tallest bar's height, on the y axis


@pytest.mark.asyncio
async def test_a_line_is_plotted_over_the_bars_of_the_same_categories() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    orders = view.router.chart.orders
    assert isinstance(orders.renderer, TextualWidgetRenderer)
    chart = orders.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 150)) as pilot:
        view.router.current_route = "chart"
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        for name in ("Shop", "Online", "Target", "Jan", "Feb", "Mar"):
            assert name in text
        plotted = _plot_monitor(chart)
        # plotext counts the categories from 1: the line stands at them, over the bars,
        # which alone share a category's room
        assert plotted.x[-1] == [1, 2, 3]
        assert plotted.y[-1] == [100, 110, 125]
        assert plotted.x[0][1:3] == pytest.approx([0.6, 1.0])  # the shop's bar of January
        assert plotted.x[3][1:3] == pytest.approx([1.0, 1.4])  # the online one beside it

        # no bars to name the categories: the line and dots still stand at them
        orders.series = [Series.scatter("Target", [0, 1, 2], [100, 110, 125])]
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        for name in ("Jan", "Feb", "Mar"):
            assert name in text
        assert _plot_monitor(chart).x == [[1, 2, 3]]


@pytest.mark.asyncio
async def test_a_series_on_the_second_y_axis_is_plotted_against_an_axis_at_the_right() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    sales = view.router.chart.sales
    assert isinstance(sales.renderer, TextualWidgetRenderer)
    chart = sales.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 200)) as pilot:
        view.router.current_route = "chart"
        await pilot.pause()
        chart.render()  # plotext's figure of the view now, not of the last paint
        plotted = _plot_monitor(chart)
        assert plotted.ylabel == ["Units", "Revenue (k€)"]
        assert plotted.yscale == ["linear", "log"]
        # the bars at the left; the revenue, then the target, at the right as their logs:
        # month 3's 0 a gap, and no break-even
        assert plotted.yside == ["left"] * 3 + ["right"] * 2
        assert plotted.y[3] == [
            pytest.approx(math.log10(3.2)),
            pytest.approx(math.log10(41)),
            pytest.approx(math.nan, nan_ok=True),
        ]
        assert plotted.y[4] == [pytest.approx(math.log10(200))] * 2
        assert plotted.hcoord == [[100], []]  # the minimum, at the left
        assert "Target" in chart.render().plain  # type: ignore[union-attr]

        # nothing left at the right: the revenue on the left's linear axis
        sales.series = [attrs.evolve(curve, on_y2=False) for curve in sales.series]
        sales.reference_lines = sales.reference_lines[:1]
        await pilot.pause()
        chart.render()  # plotext's figure of the view now, not of the last paint
        plotted = _plot_monitor(chart)
        assert plotted.ylabel == ["Units", None]
        assert plotted.yside == ["left"] * 4
        assert plotted.y[3] == [3.2, 41, 0]


@pytest.mark.asyncio
async def test_a_time_axis_shows_dates_in_utc() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    visits = view.router.chart.visits
    assert isinstance(visits.renderer, TextualWidgetRenderer)
    chart = visits.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 200)) as pilot:
        view.router.current_route = "chart"
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]

        # round days, as many as fit, as the times were given
        labels = re.findall(r"2026-11-\d\d", text)
        assert labels == sorted(labels)
        assert 2 <= len(labels) <= 120 // 18
        assert "Release" in text


@pytest.mark.asyncio
async def test_stacked_bars_are_plotted_to_where_each_ends() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    balance = view.router.chart.balance
    assert isinstance(balance.renderer, TextualWidgetRenderer)
    chart = balance.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 200)) as pilot:
        view.router.current_route = "chart"
        await pilot.pause()
        chart.render()
        plotted = _plot_monitor(chart)

        # plotext has no base: each bar from 0 to its end, the stack's last first, which
        # the others then cover
        assert [label for label in plotted.label if label is not None] == [
            "Guests",
            "Solar",
            "Cooling",
            "Heating",
            "Target",
        ]
        ends = [max(rectangle, key=abs) for rectangle in plotted.y[:12]]
        assert ends[3:12] == [-40, -20, -60, 150, 0, 140, 120, 80, 95]


@pytest.mark.asyncio
async def test_an_axis_shows_the_app_s_bounds() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    page = view.router.chart
    charts = {}
    for name in ("load", "sales", "orders"):
        renderer = getattr(page, name).renderer
        assert isinstance(renderer, TextualWidgetRenderer)
        assert isinstance(renderer.widget, ComposeChart)
        charts[name] = renderer.widget

    async with app.run_test(size=(120, 200)) as pilot:
        view.router.current_route = "chart"
        await pilot.pause()
        page.sales.y2 = attrs.evolve(page.sales.y2, maximum=100)
        page.orders.x = attrs.evolve(page.orders.x, minimum=1, maximum=2)
        await pilot.pause()

        text = charts["load"].render().plain  # type: ignore[union-attr]
        plotted = _plot_monitor(charts["load"])
        # from 0 to 10, and from 0 up to the maximum's line, its label at the bounds' end
        assert plotted.xlim[0] == [0, 10]
        assert plotted.ylim[0] == [0, 20]
        assert "Max: 20" in text
        assert "Late" not in text  # past the x bounds
        # a log axis takes its bounds as their logs, here the right one
        charts["sales"].render()
        assert _plot_monitor(charts["sales"]).ylim[1][1] == pytest.approx(2)
        # an x axis of categories: its own range, whatever the bounds
        charts["orders"].render()
        assert _plot_monitor(charts["orders"]).xlim[0] == [0.5, 3.5]


@pytest.mark.asyncio
async def test_bars_without_categories_are_plotted_at_their_x_on_a_linear_axis() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    ages = view.router.chart.ages
    assert isinstance(ages.renderer, TextualWidgetRenderer)
    chart = ages.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 150)) as pilot:
        view.router.current_route = "chart"
        await pilot.pause()
        chart.render()
        plotted = _plot_monitor(chart)
        # as wide as its share of the smallest step between two x, 10, though the x are
        # uneven; on a linear axis: bars are never on a log one, even when asked
        assert [bar[1:3] for bar in plotted.x] == [[6, 14], [16, 24], [36, 44]]
        assert plotted.xscale[0] == "linear"

        # series whose bars are at other x: each where it has one, none elsewhere
        ages.series = [
            Series.bars("Women", [4, 6], x=[10, 20]),
            Series.bars("Men", [5], x=[20]),
            Series.bars("None", [math.nan], x=[30]),
        ]
        await pilot.pause()
        chart.render()
        plotted = _plot_monitor(chart)
        # at 10 and 20, the x that have a bar: the women's, the men's, then none
        assert [bar[1] for bar in plotted.y] == [4, 6, 0, 5, 0, 0]

        ages.series = [Series.bars("None", [math.nan], x=[30])]  # no bar to draw
        await pilot.pause()
        chart.render()
        assert _plot_monitor(chart).x == []


@pytest.mark.asyncio
async def test_a_log_axis_plots_what_it_can_show() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    page = view.router.chart
    assert isinstance(page.chart.renderer, TextualWidgetRenderer)
    chart = page.chart.renderer.widget
    assert isinstance(chart, ComposeChart)
    assert isinstance(page.energy.renderer, TextualWidgetRenderer)
    energy = page.energy.renderer.widget
    assert isinstance(energy, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        view.router.current_route = "chart"
        page.chart.series = [Series.line("Decay", [0, 1, 10, 100], [5, -1, 10, 100])]
        page.chart.x = attrs.evolve(page.chart.x, scale=Scale.LOG)
        page.chart.y = attrs.evolve(page.chart.y, scale=Scale.LOG)
        page.energy.series = [Series.bars("Heating", [1000, 0, 50])]
        page.energy.y = attrs.evolve(page.energy.y, scale=Scale.LOG)
        await pilot.pause()
        chart.render()  # plotext's figure of the view now, not of the last paint
        plotted = _plot_monitor(chart)
        # the scales of the axes at the bottom and left, those drawn
        assert (plotted.xscale[0], plotted.yscale[0]) == ("log", "log")
        assert list(plotted.x[0]) == [0, 1, 2]  # 1, 10 and 100, as their logs: no x of 0
        assert math.isnan(plotted.y[0][0])  # a y of -1: a gap
        text = energy.render().plain  # type: ignore[union-attr]
        assert "1000" in text  # its axis, log from 10
        assert _plot_monitor(energy).yscale[0] == "log"


@pytest.mark.parametrize(
    ("series", "lines", "named"),
    [
        pytest.param([], [], [], id="empty"),
        pytest.param([], [ReferenceLine(10, "Now", vertical=True)], [], id="a vertical line"),
        pytest.param(
            [Series.line("Rate", [1, 10], [1, 2], on_y2=True)], [], ["Rate"], id="all on y2"
        ),
        # one of nothing but values the log axis can't show, beside one it draws
        pytest.param(
            [Series.line("Activity", [1, 10], [0, -1]), Series.line("Rate", [1, 10], [1, 2])],
            [],
            ["Rate"],
            id="a series of gaps",
        ),
    ],
)
@pytest.mark.asyncio
async def test_a_chart_with_an_axis_without_values_is_plotted(
    series: list[Series], lines: list[ReferenceLine], named: list[str]
) -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    decay = view.router.chart.decay  # log x and y axes
    assert isinstance(decay.renderer, TextualWidgetRenderer)
    chart = decay.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 200)) as pilot:
        view.router.current_route = "chart"
        decay.series = series
        decay.reference_lines = lines
        await pilot.pause()

        text = chart.render().plain  # type: ignore[union-attr]
        assert "Decay" in text
        for name in named:
            assert name in text
        assert "Activity" not in text  # no point to draw, nor to name


@pytest.mark.asyncio
async def test_reference_lines_are_plotted_labeled() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    page = view.router.chart
    assert isinstance(page.chart.renderer, TextualWidgetRenderer)
    chart = page.chart.renderer.widget
    assert isinstance(chart, ComposeChart)
    assert isinstance(page.energy.renderer, TextualWidgetRenderer)
    energy = page.energy.renderer.widget
    assert isinstance(energy, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        view.router.current_route = "chart"
        page.energy.reference_lines = [ReferenceLine(1, "Mine", vertical=True)]
        await pilot.pause()
        text = chart.render().plain  # type: ignore[union-attr]
        assert "Max: 4.6" in text
        assert "Now" in text
        plotted = _plot_monitor(chart)
        assert (plotted.hcoord[0], plotted.vcoord[0]) == ([4.6, 0.6], [2.3])
        assert plotted.hcolors[0] == [(208, 48, 48), (32, 128, 64)]  # their own colors
        assert "Mine" in energy.render().plain  # type: ignore[union-attr]
        # on the bedroom's bars: plotext draws the categories from 1
        assert _plot_monitor(energy).vcoord[0] == [2]


@pytest.mark.asyncio
async def test_a_step_series_is_plotted_in_steps() -> None:
    view = ChartPagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    jobs = view.router.chart.jobs
    assert isinstance(jobs.renderer, TextualWidgetRenderer)
    chart = jobs.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        view.router.current_route = "chart"
        await pilot.pause()
        chart.render()
        plotted = _plot_monitor(chart)
        # each count held until the next change
        assert list(plotted.x[0]) == [0, 2, 2, 5, 5, 6, 6]
        assert list(plotted.y[0]) == [1, 1, 3, 3, 2, 2, 4]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("picked", "saved"),
    [
        ("drop", ["drop.pdf"]),  # PDF unless named
        ("drop.png", ["drop.png"]),
        (None, []),  # cancelled
    ],
)
async def test_its_key_saves_the_chart_s_image(
    picked: str | None, saved: list[str], tmp_path: Path
) -> None:
    pytest.importorskip("matplotlib")
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        view.add_curve()
        chart.focus()
        await pilot.pause()
        footer = [binding.description for (_, binding, *_rest) in app.active_bindings.values()]
        assert "Save Image" in footer

        await pilot.press("s")
        await pilot.pause()
        assert [type(screen).__name__ for screen in app.screen_stack] == ["Screen", "FileSave"]
        # as the dialog's Save button does, or Cancel
        app.screen.dismiss(None if picked is None else tmp_path / picked)
        await pilot.pause()

    assert _names(tmp_path) == saved


@pytest.mark.asyncio
async def test_without_matplotlib_the_chart_has_no_key_saving_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chartimage, "is_available", lambda: False)
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        chart.focus()
        await pilot.press("s")
        await pilot.pause()
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_a_series_of_its_own_color_is_plotted_so_filled() -> None:
    view = BatmanMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        chart.render()  # plotext's figure of the view now, not of the last paint
        plotted = _plot_monitor(chart)
        assert [colors[0] for colors in plotted.color] == [(255, 215, 0)] * 2 + [(0, 0, 0)] * 2
        assert plotted.fillx == [0] * 4  # filled down to 0; an unfilled one is False


@pytest.mark.asyncio
async def test_the_chart_is_as_tall_as_its_view_says_in_rows() -> None:
    view = PipeChartMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    assert isinstance(view.chart.renderer, TextualWidgetRenderer)
    chart = view.chart.renderer.widget
    assert isinstance(chart, ComposeChart)

    async with app.run_test(size=(120, 80)) as pilot:
        await pilot.pause()
        assert chart.size.height == 20  # its own CSS's
        view.chart.height = 480
        await pilot.pause()
        assert chart.size.height == 30  # rows of about 16 pixels
        view.chart.height = 10
        await pilot.pause()
        assert chart.size.height == 5  # enough for its axes still
        view.chart.height = None
        await pilot.pause()
        assert chart.size.height == 20


@pytest.mark.asyncio
async def test_the_chart_leaves_out_what_it_has_no_data_for() -> None:
    view = PipeChartMainView()
    view.chart.series = []
    view.chart.reference_lines = [ReferenceLine(5, vertical=True, label="Start")]
    bars = ChartPagesMainView()
    bars.router.chart.energy.series = []
    app, bars_app = _app_of(view), _app_of(bars)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        chart = _widget(view.chart)
        assert isinstance(chart, ComposeChart)
        assert "Start" not in str(chart.render())  # a label beside no data
    async with bars_app.run_test(size=(120, 40)) as pilot:
        bars.router.current_route = "chart"
        await pilot.pause()
        energy = _widget(bars.router.chart.energy)
        assert isinstance(energy, ComposeChart)
        assert "Kitchen" not in str(energy.render())  # no bar, nor its category
