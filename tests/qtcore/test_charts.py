"""Tests of the Qt chart."""

from __future__ import annotations

import datetime
import math
from typing import TYPE_CHECKING

import attrs
import numpy as np
import pyqtgraph as pg
import pytest
from qtpy.QtCore import QPointF, Qt
from qtpy.QtGui import (
    QColor,
    QFont,
    QPalette,
)
from qtpy.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMenu,
    QWidget,
)

from composeui.core import chartimage
from composeui.core.chartcolors import SERIES_COLORS
from composeui.core.registry import RendererType
from composeui.core.view import (
    BarMode,
    ChartKind,
    ChartView,
    LineStyle,
    ReferenceLine,
    Scale,
    Series,
)
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qchart import QChart
from examples.pipechart import PipeChartMainView
from tests.charts import ChartPagesMainView

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.core.chartimage import ImageOptions


def _rendered_chart(qtbot: QtBot) -> tuple[PipeChartMainView, QChart]:
    view = PipeChartMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.resize(900, 700)
    window.show()
    assert isinstance(view.chart.renderer, QtWidgetRenderer)
    chart = view.chart.renderer.qt_object
    assert isinstance(chart, QChart)
    return view, chart


def _plot_item(chart: QChart) -> pg.PlotItem:
    plot = chart.getPlotItem()
    assert isinstance(plot, pg.PlotItem)
    return plot


def _chart_scene(chart: QChart) -> pg.GraphicsScene:
    scene = chart.scene()
    assert isinstance(scene, pg.GraphicsScene)
    return scene


def _view_box(chart: QChart) -> pg.ViewBox:
    view_box = _plot_item(chart).getViewBox()
    assert isinstance(view_box, pg.ViewBox)
    return view_box


def test_the_chart_shows_its_titles_units_and_series(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    plot = _plot_item(chart)
    assert plot.titleLabel.text == "Pressure Drop"
    assert plot.getAxis("bottom").labelText == "Flow Rate"
    assert plot.getAxis("bottom").labelUnits == "L/s"
    assert plot.getAxis("left").labelUnits == "kPa"
    view.chart.x = attrs.evolve(view.chart.x, unit="m3/h")
    view.chart.y = attrs.evolve(view.chart.y, title="Drop")
    assert plot.getAxis("bottom").labelUnits == "m3/h"
    assert plot.getAxis("bottom").labelText == "Flow Rate"
    assert plot.getAxis("left").labelText == "Drop"

    view.chart.series = [
        Series.line("Pressure", [0, 1, 2, 3], [1, math.nan, 3, 4]),
        Series.line("Temperature", [0, 0.5], [2, 2]),  # an x of its own
    ]

    assert chart.legend_names() == ["Pressure", "Temperature"]
    pressure, temperature = plot.listDataItems()
    x, y = pressure.getData()
    assert list(x) == [0, 1, 2, 3]
    assert math.isnan(y[1])  # a gap: drawn with `connect="finite"`
    assert pressure.opts["connect"] == "finite"
    assert len(temperature.getData()[0]) == 2
    view.chart.series = view.chart.series[1:]
    assert chart.legend_names() == ["Temperature"]
    assert len(plot.listDataItems()) == 1


def test_new_series_keep_the_user_s_zoom(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.add_curve()
    view_box = _view_box(chart)
    view_box.setXRange(0.5, 1.0, padding=0)  # as the mouse wheel would

    view.pipe.diameter.value = 80
    view.add_curve()

    assert len(view.chart.series) == 2
    assert view_box.viewRange()[0] == [0.5, 1.0]


def test_hovering_the_chart_shows_the_values_at_the_cursor(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series.line("Pressure", [0, 1, 2], [10, 20, 30.5])]
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 2)
    assert chart.hover_text() == ""

    _chart_scene(chart).sigMouseMoved.emit(view_box.mapViewToScene(QPointF(1.05, 15)))

    qtbot.waitUntil(lambda: chart.hover_text() != "")
    lines = chart.hover_text().splitlines()
    assert lines[0].endswith(" L/s")
    assert lines[1] == "Pressure: 20.00 kPa"  # its trailing zeros kept, as on the web
    if hasattr(QFont, "Tag"):  # digits of one width, from Qt 6.7
        assert QFont.Tag("tnum") in chart._hover.textItem.font().featureTags()  # noqa: SLF001 (the chart's hover label, which only Qt draws)
    _chart_scene(chart).sigMouseMoved.emit(QPointF(-10, -10))  # off the plot
    qtbot.waitUntil(lambda: chart.hover_text() == "")


def test_a_step_series_holds_each_value_until_the_next_point(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series.line("Running", [0, 2, 5], [1, 3, 2], step=True)]
    (running,) = _plot_item(chart).listDataItems()

    x, y = running.getData()
    assert (list(x), list(y)) == ([0, 2, 2, 5, 5], [1, 1, 3, 3, 2])
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 5)
    # nearer 5 than 2, but still holding 2's value
    _chart_scene(chart).sigMouseMoved.emit(view_box.mapViewToScene(QPointF(4, 2)))
    qtbot.waitUntil(lambda: chart.hover_text() != "")
    assert chart.hover_text().splitlines()[1] == "Running: 3 kPa"  # a count, as it is

    view.chart.series = [Series.scatter("Running", [0, 2, 5], [1, 3, 2])]  # dots: as they are
    assert len(running.getData()[0]) == 3


def test_the_chart_follows_the_palette(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series.line("Pressure", [0, 1], [0, 1])]
    (curve,) = _plot_item(chart).listDataItems()
    assert curve.opts["pen"].color().name() == SERIES_COLORS[False][0]
    palette = chart.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))

    chart.setPalette(palette)

    assert curve.opts["pen"].color().name() == SERIES_COLORS[True][0]
    assert chart.backgroundBrush().color().name() == "#202020"
    assert _plot_item(chart).getAxis("left").textPen().color().name() == "#f0f0f0"


def test_a_scatter_series_is_drawn_as_dots_over_the_lines(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.add_curve()
    view.add_measurements()
    model, measured = _plot_item(chart).listDataItems()

    assert model.opts["symbol"] is None
    assert model.opts["pen"].color().name() == SERIES_COLORS[False][0]
    assert measured.opts["pen"].style() == Qt.PenStyle.NoPen
    assert measured.opts["symbol"] == "o"
    assert measured.opts["symbolBrush"].color().name() == SERIES_COLORS[False][1]
    assert chart.legend_names() == ["D = 50 mm", "Measured, D = 50 mm"]

    view.chart.series = [attrs.evolve(curve, kind=ChartKind.SCATTER) for curve in view.chart.series]
    assert model.opts["symbol"] == "o"
    assert model.opts["pen"].style() == Qt.PenStyle.NoPen


def _chart_page_chart(qtbot: QtBot, name: str = "energy") -> tuple[ChartPagesMainView, QChart]:
    view = ChartPagesMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.resize(900, 900)
    window.show()
    view.router.current_route = "chart"
    chart_view = getattr(view.router.chart, name)
    assert isinstance(chart_view.renderer, QtWidgetRenderer)
    chart = chart_view.renderer.qt_object
    assert isinstance(chart, QChart)
    return view, chart


def test_a_bar_chart_groups_a_bar_per_series_in_each_category(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot)
    plot = _plot_item(chart)
    assert not any(isinstance(item, pg.PlotDataItem) for item in plot.items)
    heating, cooling = (item for item in plot.items if isinstance(item, pg.BarGraphItem))

    assert list(np.asarray(heating.opts["height"])) == [120, 80, 95]
    assert list(np.asarray(cooling.opts["height"])) == [30, 45]  # none in the bedroom
    # side by side in each category's group, centered on its index
    assert heating.opts["width"] == cooling.opts["width"] == pytest.approx(0.4)
    assert list(np.asarray(heating.opts["x0"])) == pytest.approx([-0.4, 0.6, 1.6])
    assert list(np.asarray(cooling.opts["x0"])) == pytest.approx([0.0, 2.0])
    assert pg.mkBrush(heating.opts["brush"]).color().name() == SERIES_COLORS[False][0]
    assert chart.legend_names() == ["Heating", "Cooling"]
    ticks = plot.getAxis("bottom")._tickLevels  # noqa: SLF001 (pyqtgraph has no public call for the ticks)
    assert ticks == [[(0, "Kitchen"), (1, "Bedroom"), (2, "Office")]]

    energy = view.router.chart.energy
    # its series as curves again, over the same categories
    energy.series = [attrs.evolve(curve, kind=ChartKind.LINE) for curve in energy.series]
    assert sum(isinstance(item, pg.PlotDataItem) for item in plot.items) == 2
    assert not any(isinstance(item, pg.BarGraphItem) for item in plot.items)
    assert plot.getAxis("bottom")._tickLevels == ticks  # noqa: SLF001 (pyqtgraph has no public call for the ticks)


def test_a_line_is_drawn_over_the_bars_of_the_same_categories(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot, "orders")
    plot = _plot_item(chart)
    shop, online = (item for item in plot.items if isinstance(item, pg.BarGraphItem))
    (target,) = (item for item in plot.items if isinstance(item, pg.PlotDataItem))

    # only the bars share a category's room: the line stands at the categories
    assert shop.opts["width"] == online.opts["width"] == pytest.approx(0.4)
    assert list(np.asarray(shop.opts["x0"])) == pytest.approx([-0.4, 0.6, 1.6])
    assert list(np.asarray(online.opts["x0"])) == pytest.approx([0.0, 1.0, 2.0])
    assert target.xData is not None
    assert list(target.xData) == [0, 1, 2]
    assert target.zValue() > shop.zValue()
    # each in its series' color and place in the legend, bars or not
    assert pg.mkBrush(online.opts["brush"]).color().name() == SERIES_COLORS[False][2]
    assert pg.mkPen(target.opts["pen"]).color().name() == SERIES_COLORS[False][1]
    assert chart.legend_names() == ["Shop", "Target", "Online"]
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] > 2)
    chart.show_hover(view_box.mapViewToScene(QPointF(1.1, 50)))
    assert chart.hover_text().splitlines() == [
        "Feb",
        "Shop: 140 k",
        "Target: 110 k",
        "Online: 95 k",
    ]

    orders = view.router.chart.orders
    # the line as bars too: its item replaced, and a third of the room each
    orders.series = [attrs.evolve(curve, kind=ChartKind.BAR) for curve in orders.series]
    bars = [item for item in plot.items if isinstance(item, pg.BarGraphItem)]
    assert not any(isinstance(item, pg.PlotDataItem) for item in plot.items)
    assert [item.opts["width"] for item in bars] == [pytest.approx(0.8 / 3)] * 3
    assert chart.legend_names() == ["Shop", "Target", "Online"]


def test_a_series_on_the_second_y_axis_is_drawn_against_an_axis_at_the_right(
    qtbot: QtBot,
) -> None:
    view, chart = _chart_page_chart(qtbot, "sales")
    plot = _plot_item(chart)
    view_box = _view_box(chart)
    # laid out: pyqtgraph draws only the points within the view, as it shows them then
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] > 3)
    right = plot.getAxis("right")
    view2 = right.linkedView()
    assert isinstance(view2, pg.ViewBox)
    assert right.isVisible()
    assert (right.labelText, right.labelUnits, right.logMode) == ("Revenue", "k€", True)
    # the bars and the minimum in the plot's own view, on its linear axis
    (units,) = (item for item in plot.items if isinstance(item, pg.BarGraphItem))
    assert list(np.asarray(units.opts["height"])) == [120, 150, 90]
    assert not any(isinstance(item, pg.PlotDataItem) for item in plot.items)
    assert [item.value() for item in plot.items if isinstance(item, pg.InfiniteLine)] == [100]
    # the revenue and the target in the right's, as its logs; no break-even on a log axis
    (revenue,) = (item for item in view2.addedItems if isinstance(item, pg.PlotDataItem))
    _xs, drawn = revenue.getData()
    assert drawn is not None
    assert list(drawn) == [
        pytest.approx(math.log10(3.2)),
        pytest.approx(math.log10(41)),
        pytest.approx(math.nan, nan_ok=True),
    ]
    lines = [item for item in view2.addedItems if isinstance(item, pg.InfiniteLine)]
    (target,) = (line for line in lines if line.angle == 0)
    assert target.value() == pytest.approx(math.log10(200))
    assert target.zValue() > revenue.zValue()  # over the series, as in the plot's own view
    # the right axis fits its own series and lines, given in their values
    y2_range = chart.shown_y2_range()
    assert y2_range is not None
    assert y2_range[0] <= 3.2
    assert y2_range[1] >= 200
    # a zoom into the lower half of the left axis: the right one shows its own lower half,
    # the same part of the plot
    (low, high), (low2, high2) = view_box.viewRange()[1], view2.viewRange()[1]
    view_box.setRange(yRange=(low, (low + high) / 2), padding=0)
    assert view2.viewRange()[1] == [pytest.approx(low2), pytest.approx((low2 + high2) / 2)]
    # fitted to the data again, as a double click does: each axis fits its own
    view_box.enableAutoRange()
    qtbot.waitUntil(lambda: view2.viewRange()[1] == [pytest.approx(low2), pytest.approx(high2)])
    # each value in its own axis' unit, over everything either axis draws
    chart.show_hover(view_box.mapViewToScene(QPointF(2, 50)))
    assert chart.hover_text().splitlines()[1:] == ["Units: 150", "Revenue: 41.00 k€"]
    stacked = _chart_scene(chart).items(Qt.SortOrder.DescendingOrder)
    (hover,) = (
        item
        for item in stacked
        if isinstance(item, pg.TextItem) and item.toPlainText() == chart.hover_text()
    )
    assert stacked.index(hover) < stacked.index(revenue)

    sales = view.router.chart.sales
    # nothing left at the right: its axis hides, and the revenue is on the left's linear axis
    sales.series = [attrs.evolve(curve, on_y2=False) for curve in sales.series]
    sales.reference_lines = sales.reference_lines[:1]
    assert not right.isVisible()
    assert chart.shown_y2_range() is None
    (revenue,) = (item for item in plot.items if isinstance(item, pg.PlotDataItem))
    _xs, drawn = revenue.getData()
    assert drawn is not None
    assert list(drawn) == [3.2, 41, 0]
    assert not any(isinstance(item, pg.PlotDataItem) for item in view2.addedItems)


def test_an_axis_shows_the_app_s_bounds_until_the_user_zooms(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot, "load")
    view_box = _view_box(chart)
    load = view.router.chart.load

    def shown() -> list[list[float]]:
        return [[float(bound) for bound in axis] for axis in view_box.viewRange()]

    # from 0 to 10, and from 0 up to the maximum's line, once pyqtgraph fitted the data
    qtbot.waitUntil(lambda: shown()[0] == [0, 10] and shown()[1][1] >= 20)
    assert shown()[1][0] == 0
    # the user's zoom, past the bounds, stays; back out, the bounds again
    view_box.setRange(xRange=(-5, 20), yRange=(-1, 5), padding=0)
    assert shown() == [[-5, 20], [-1, 5]]
    view_box.enableAutoRange()
    qtbot.waitUntil(lambda: shown()[0] == [0, 10])
    # the app's new bounds, over the user's zoom
    view_box.setRange(yRange=(-1, 5), padding=0)
    load.y = attrs.evolve(load.y, minimum=None, maximum=4)
    qtbot.waitUntil(lambda: shown()[1][1] == 4)
    assert shown()[1][0] < 0  # its bottom fits the data again: the crane's -2

    # a log axis: bounded as its logs, here the right one's
    sales = view.router.chart.sales
    assert isinstance(sales.renderer, QtWidgetRenderer)
    sales_chart = sales.renderer.qt_object
    assert isinstance(sales_chart, QChart)
    view2 = _plot_item(sales_chart).getAxis("right").linkedView()
    assert isinstance(view2, pg.ViewBox)
    sales.y2 = attrs.evolve(sales.y2, maximum=100)
    qtbot.waitUntil(lambda: view2.viewRange()[1][1] == pytest.approx(2))
    # an x axis of categories: its own range, whatever the bounds
    orders = view.router.chart.orders
    assert isinstance(orders.renderer, QtWidgetRenderer)
    orders_chart = orders.renderer.qt_object
    assert isinstance(orders_chart, QChart)
    orders_box = _view_box(orders_chart)
    drawn = orders_box.viewRange()[0]
    orders.x = attrs.evolve(orders.x, minimum=1, maximum=2)
    assert orders_box.viewRange()[0] == drawn


def test_a_time_axis_shows_dates_in_utc(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot, "visits")
    plot = _plot_item(chart)
    view_box = _view_box(chart)
    bottom = plot.getAxis("bottom")
    assert isinstance(bottom, pg.DateAxisItem)
    assert bottom.utcOffset == 0  # as the times were given, whatever the system's zone
    assert (bottom.labelText, bottom.grid is not False) == ("Day", True)
    fourth = (datetime.date(2026, 11, 4) - datetime.date(1970, 1, 1)).days * 86400

    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] > fourth)
    chart.show_hover(view_box.mapViewToScene(QPointF(fourth, 1)))
    assert chart.hover_text().splitlines()[:2] == ["2026-11-04", "Visits: 9"]

    # numbers again: pyqtgraph's own axis, with the label and the grid of the old one
    visits = view.router.chart.visits
    visits.x = attrs.evolve(visits.x, scale=Scale.LINEAR)
    numbers = plot.getAxis("bottom")
    assert not isinstance(numbers, pg.DateAxisItem)
    assert numbers.labelText == "Day"
    assert numbers.grid is not False


def test_stacked_bars_stand_on_the_values_before_them(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot, "balance")
    plot = _plot_item(chart)
    view_box = _view_box(chart)
    heating, cooling, solar = (item for item in plot.items if isinstance(item, pg.BarGraphItem))

    assert list(np.asarray(cooling.opts["y0"])) == [120, 95]  # on the heating
    assert list(np.asarray(cooling.opts["height"])) == [30, 45]
    assert list(np.asarray(solar.opts["y0"]) + np.asarray(solar.opts["height"])) == [-40, -20, -60]
    # the room of a slot: the left axis' stack beside the right one's
    assert heating.opts["width"] == pytest.approx(0.4)
    qtbot.waitUntil(lambda: view_box.viewRange()[1][1] >= 150)  # the totals
    chart.show_hover(view_box.mapViewToScene(QPointF(-0.2, 50)))
    # each series' own value
    assert chart.hover_text().splitlines()[:4] == [
        "Kitchen",
        "Heating: 120 kWh",
        "Cooling: 30 kWh",
        "Solar: -40 kWh",
    ]

    balance = view.router.chart.balance
    balance.bar_mode = BarMode.GROUPED
    assert np.asarray(cooling.opts["y0"]).max(initial=0) == 0  # from 0 again
    assert cooling.opts["width"] == pytest.approx(0.8 / 4)


def test_bars_without_categories_stand_at_their_x_on_a_linear_axis(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot, "ages")
    plot = _plot_item(chart)
    (people,) = (item for item in plot.items if isinstance(item, pg.BarGraphItem))

    # as wide as its share of the smallest step between two x, 10
    assert list(np.asarray(people.opts["x0"])) == pytest.approx([6, 16, 36])
    assert people.opts["width"] == pytest.approx(8)
    assert plot.getAxis("bottom")._tickLevels is None  # noqa: SLF001 (numbers, not categories)
    assert not plot.getAxis("bottom").logMode  # bars: never a log axis, even when asked
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 40)
    chart.show_hover(view_box.mapViewToScene(QPointF(22, 3)))
    assert chart.hover_text().splitlines()[1:] == ["People: 6"]
    # between two bars, further than half a step from each: no bar there
    chart.show_hover(view_box.mapViewToScene(QPointF(30, 3)))
    assert chart.hover_text().splitlines()[1:] == []

    ages = view.router.chart.ages
    ages.series = [Series.line("Trend", [10, 40], [5, 5])]
    assert plot.getAxis("bottom").logMode  # no bars left: the log axis asked


def test_hovering_a_bar_chart_shows_its_category_s_values(qtbot: QtBot) -> None:
    _view, chart = _chart_page_chart(qtbot)
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] > 2)

    _chart_scene(chart).sigMouseMoved.emit(view_box.mapViewToScene(QPointF(1.1, 50)))

    qtbot.waitUntil(lambda: chart.hover_text() != "")
    # whole numbers, as they are: not 80.00, nor 4.528e+04 for a count of 45280
    assert chart.hover_text().splitlines() == ["Bedroom", "Heating: 80 kWh"]


def test_a_log_axis_leaves_out_what_it_cannot_show(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    plot = _plot_item(chart)
    view.chart.series = [Series.line("Decay", [0, 1, 10, 100], [5, -1, 10, 100])]

    view.chart.x = attrs.evolve(view.chart.x, scale=Scale.LOG)
    view.chart.y = attrs.evolve(view.chart.y, scale=Scale.LOG)

    assert plot.getAxis("bottom").logMode
    assert plot.getAxis("left").logMode
    (curve,) = (item for item in plot.items if isinstance(item, pg.PlotDataItem))
    # no x of 0 on a log axis: left out; a y of -1: a gap
    assert curve.xData is not None
    assert curve.yData is not None
    assert list(curve.xData) == [1, 10, 100]
    assert math.isnan(curve.yData[0])
    assert list(curve.yData[1:]) == [10, 100]
    view.chart.x = attrs.evolve(view.chart.x, scale=Scale.LINEAR)
    assert not plot.getAxis("bottom").logMode
    assert list(curve.xData) == [0, 1, 10, 100]


def test_a_log_axis_shows_the_hovered_value_not_its_log(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series.line("Decay", [1, 10, 100], [3, 2, 1])]
    view.chart.x = attrs.evolve(view.chart.x, scale=Scale.LOG)
    view_box = _view_box(chart)
    # the log range, 0 to 2: the linear one, 1 to 100, reaches 2 too
    qtbot.waitUntil(lambda: 2 <= view_box.viewRange()[0][1] < 3)

    # straight to the hover, not through the mouse's rate-limited proxy: its delay leaves
    # the range, still settling on the log axis, time to move under the cursor
    chart.show_hover(view_box.mapViewToScene(QPointF(1.02, 2)))  # x = 10^1.02

    assert chart.hover_text().splitlines() == ["10.47 L/s", "Decay: 2 kPa"]


def test_log_bars_rise_from_the_power_of_10_under_the_lowest(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot)
    energy = view.router.chart.energy
    energy.series = [Series.bars("Heating", [1000, 0, 50])]

    energy.y = attrs.evolve(energy.y, scale=Scale.LOG)

    (bars,) = (item for item in _plot_item(chart).items if isinstance(item, pg.BarGraphItem))
    # none of 0 in the bedroom
    assert list(np.asarray(bars.opts["x0"])) == pytest.approx([-0.4, 1.6])
    assert bars.opts["y0"] == 1  # 10 kWh, under 50
    assert list(np.asarray(bars.opts["height"])) == pytest.approx([2, math.log10(50) - 1])
    assert _plot_item(chart).getAxis("left").logMode


@pytest.mark.parametrize(
    ("picked", "saved_as"),
    [
        ("drop", ["drop.svg"]),  # by the filter chosen
        ("drop.png", ["drop.png"]),  # by the name's own extension
        ("", []),  # cancelled
    ],
)
def test_save_image_saves_the_chart_as_it_shows(
    picked: str,
    saved_as: list[str],
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("matplotlib")
    view, chart = _rendered_chart(qtbot)
    view.add_curve()
    _view_box(chart).setRange(xRange=(0.5, 1.5), yRange=(0, 10), padding=0)
    asked: list[tuple[str, str]] = []

    def get_save_file_name(
        _parent: QWidget, caption: str, name: str, filters: str
    ) -> tuple[str, str]:
        asked.append((caption, name))
        assert filters.startswith("PDF (*.pdf)")  # vector first
        return (str(tmp_path / picked) if picked else ""), "SVG (*.svg)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", get_save_file_name)
    saved: list[ImageOptions] = []
    save = chartimage.save_chart_image

    def save_chart_image(chart_view: ChartView, path: Path, options: ImageOptions) -> None:
        saved.append(options)
        save(chart_view, path, options)

    monkeypatch.setattr(chartimage, "save_chart_image", save_chart_image)
    menu = _view_box(chart).menu
    assert isinstance(menu, QMenu)
    (action,) = (action for action in menu.actions() if action.text() == "Save Image…")

    action.trigger()

    assert asked == [("Save Image", "Pressure Drop.pdf")]
    assert [path.name for path in tmp_path.iterdir()] == saved_as
    # the zoom the user looks at
    assert [(options.x_range, options.y_range) for options in saved] == [
        (pytest.approx((0.5, 1.5)), pytest.approx((0, 10)))
    ] * len(saved_as)


def test_without_matplotlib_the_chart_offers_only_its_own_export(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chartimage, "is_available", lambda: False)

    _view, chart = _rendered_chart(qtbot)

    menu = _view_box(chart).menu
    assert isinstance(menu, QMenu)
    texts = [action.text() for action in menu.actions()]
    assert "Save Image…" not in texts
    # pyqtgraph's own, saving an image of the screen's chart
    assert [action.text() for action in _chart_scene(chart).contextMenu] == ["Export..."]


def test_a_click_on_the_plot_emits_its_point(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series.line("Decay", [1, 10, 100], [3, 2, 1])]
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 100)
    clicks: list[tuple[float, float]] = []
    view.chart.clicked.connect(lambda x, y: clicks.append((x, y)))

    chart.click(view_box.mapViewToScene(QPointF(10, 2)))
    view.chart.x = attrs.evolve(view.chart.x, scale=Scale.LOG)
    chart.click(view_box.mapViewToScene(QPointF(1, 2)))  # the log of 10
    chart.click(QPointF(-10, -10))  # off the plot

    assert clicks == [pytest.approx((10, 2)), pytest.approx((10, 2))]


def test_a_series_of_its_own_color_is_drawn_so_filled_down_to_0(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [
        Series.line("Oval", [0, 1], [1, 1], color="#ffd700", fill=True),
        Series.line("Theme", [0, 1], [2, 2]),
    ]
    oval, theme = (item for item in _plot_item(chart).items if isinstance(item, pg.PlotDataItem))

    assert pg.mkPen(oval.opts["pen"]).color().name() == "#ffd700"
    assert (oval.opts["fillLevel"], pg.mkBrush(oval.opts["fillBrush"]).color().name()) == (
        0,
        "#ffd700",
    )
    assert pg.mkPen(theme.opts["pen"]).color().name() == SERIES_COLORS[False][1]
    assert theme.opts["fillLevel"] is None
    palette = chart.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    chart.setPalette(palette)
    assert pg.mkPen(oval.opts["pen"]).color().name() == "#ffd700"  # the same in a dark theme


def test_a_series_fill_color_paints_its_area_under_a_line_of_its_own_color(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [
        Series.line("Load", [0, 1], [1, 1], color="#6096dd", fill=True, fill_color="#e2ebf7")
    ]
    (load,) = (item for item in _plot_item(chart).items if isinstance(item, pg.PlotDataItem))

    assert pg.mkPen(load.opts["pen"]).color().name() == "#6096dd"
    assert pg.mkBrush(load.opts["fillBrush"]).color().name() == "#e2ebf7"


def test_reference_lines_are_styled_labeled_and_in_range(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    plot = _plot_item(chart)
    view.chart.series = [Series.line("Decay", [1, 10], [3, 2])]

    view.chart.reference_lines = [
        ReferenceLine(40, "Max: {40}", color="#d03030", style=LineStyle.DOTTED),  # braces are text
        ReferenceLine(100, "Now", vertical=True),
    ]

    # labeled lines, unlike the hover's crosshair
    maximum, now = (item for item in plot.items if hasattr(item, "label"))
    assert (maximum.angle, maximum.value(), now.angle, now.value()) == (0, 40, 90, 100)
    assert maximum.label.toPlainText() == "Max: {40}"
    assert maximum.pen.color().name() == "#d03030"
    assert maximum.pen.style() == Qt.PenStyle.DotLine
    assert now.pen.style() == Qt.PenStyle.DashLine  # by default
    assert now.pen.color() == chart.palette().color(QPalette.ColorRole.WindowText)
    # each shows, though past the data
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 100 and view_box.viewRange()[1][1] >= 40)
    palette = chart.palette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))
    chart.setPalette(palette)
    assert now.pen.color().name() == "#f0f0f0"
    assert now.label.color.name() == "#f0f0f0"

    view.chart.x = attrs.evolve(
        view.chart.x, scale=Scale.LOG
    )  # at its log, as pyqtgraph draws the series
    view.chart.reference_lines = [
        *view.chart.reference_lines,
        ReferenceLine(0, "Start", vertical=True),
    ]

    lines = [item for item in plot.items if hasattr(item, "label")]
    assert [line.value() for line in lines] == [40, 2]  # no x of 0 on a log axis


def test_the_chart_is_as_tall_as_its_view_says(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    assert chart.height() > 250  # its share of the window's 700 pixels

    view.chart.height = 250
    qtbot.waitUntil(lambda: chart.height() == 250)
    assert (chart.minimumHeight(), chart.maximumHeight()) == (250, 250)

    view.chart.height = None  # as tall as the layout makes it again
    assert (chart.minimumHeight(), chart.maximumHeight()) == (0, 16777215)
    qtbot.waitUntil(lambda: chart.height() > 250)


def test_a_click_with_the_left_button_alone_emits_its_point(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    qtbot.waitExposed(chart.window())
    view.chart.series = [Series.line("Decay", [1, 10, 100], [1, 10, 100])]
    view_box = _view_box(chart)
    view.chart.y = attrs.evolve(view.chart.y, scale=Scale.LOG)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] >= 100 and view_box.viewRange()[1][1] < 3)
    clicks: list[tuple[float, float]] = []
    view.chart.clicked.connect(lambda x, y: clicks.append((x, y)))
    point = chart.mapFromScene(view_box.mapViewToScene(QPointF(10, 1)))  # the log of 10

    # first: pyqtgraph takes a click soon after another for a double one
    qtbot.mouseClick(chart.viewport(), Qt.MouseButton.LeftButton, pos=point)
    qtbot.mouseClick(chart.viewport(), Qt.MouseButton.MiddleButton, pos=point)
    qtbot.mouseDClick(chart.viewport(), Qt.MouseButton.LeftButton, pos=point)

    (click,) = clicks
    assert click == pytest.approx((10, 10), rel=0.05)  # within the pixel the mouse hit


def test_a_log_chart_s_shown_range_is_its_values_not_their_logs(qtbot: QtBot) -> None:
    view, chart = _rendered_chart(qtbot)
    view.chart.series = [Series.line("Decay", [1, 10, 100], [1, 10, 100])]
    view.chart.x = attrs.evolve(view.chart.x, scale=Scale.LOG)
    view.chart.y = attrs.evolve(view.chart.y, scale=Scale.LOG)

    _view_box(chart).setRange(xRange=(0, 2), yRange=(1, 3), padding=0)

    assert chart.shown_range() == (pytest.approx((1, 100)), pytest.approx((10, 1000)))


def test_the_hover_leaves_out_what_isn_t_drawn_there(qtbot: QtBot) -> None:
    view, chart = _chart_page_chart(qtbot)
    energy = view.router.chart.energy
    view_box = _view_box(chart)
    qtbot.waitUntil(lambda: view_box.viewRange()[0][1] > 2)

    view_box.setRange(xRange=(-3, 5), padding=0)  # zoomed out, past the categories
    chart.show_hover(view_box.mapViewToScene(QPointF(4, 50)))
    past = chart.hover_text()
    energy.series = [
        Series.line("Heating", [0, 1, 2], [10, 20, 30]),
        Series.line("Unknown", [0, 1, 2], [math.nan] * 3),  # no point drawn
    ]
    chart.show_hover(view_box.mapViewToScene(QPointF(1, 20)))

    assert past == ""
    assert chart.hover_text().splitlines()[1:] == ["Heating: 20 kWh"]
