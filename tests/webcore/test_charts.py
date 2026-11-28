"""Tests of the web chart."""

from __future__ import annotations

import datetime
import json
import math
import re
import sys
from typing import TYPE_CHECKING, Any

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

import attrs

from composeui.core import chartimage
from composeui.core.registry import RendererType
from composeui.core.view import (
    BarMode,
    ChartKind,
    ChartView,
    Scale,
    Series,
)
from composeui.webcore._renderers.charts import CHART_MAX_POINTS, WebChartRenderer
from composeui.webcore.changes import collect_dirty
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import (
    UnsupportedEventError,
    render_dirty,
)
from examples.batman import BatmanMainView
from examples.pipechart import MEASUREMENTS, PipeChartMainView
from tests.charts import ChartPagesMainView

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.testclient import TestClient


from tests.webcore.support import _Browser, _element, _swapped, _widget_id


@pytest.fixture
def chart_views() -> list[PipeChartMainView]:
    """Each session's main view, kept by `chart_client`'s app."""
    return []


@pytest.fixture
def chart_client(chart_views: list[PipeChartMainView]) -> Iterator[TestClient]:
    class ChartApp(WebApplication[PipeChartMainView]):
        def __init__(self) -> None:
            super().__init__(build_main_view=PipeChartMainView)

        @override
        def setup_session(self, main_view: PipeChartMainView) -> None:
            chart_views.append(main_view)

    with _Browser(ChartApp().create_starlette_app()) as client:
        yield client


def _chart_spec(markup: str, chart: ChartView) -> dict[str, Any]:
    plot = _element(markup, f"{_widget_id(chart.renderer)}-plot")
    spec: dict[str, Any] = json.loads(plot.attributes["data-chart"] or "")
    return spec


def test_the_chart_sends_its_series_for_the_page_to_draw(
    chart_views: list[PipeChartMainView], chart_client: TestClient
) -> None:
    page = chart_client.get("/").text
    (main_view,) = chart_views
    chart = main_view.chart
    figure = _element(page, _widget_id(chart.renderer))
    assert figure.tag == "figure"
    assert _chart_spec(page, chart) == {
        "title": "Pressure Drop",
        "x": {"label": "Flow Rate (L/s)", "unit": "L/s", "log": False},
        "y": {"label": "Pressure Drop (kPa)", "unit": "kPa", "log": False},
        "series": [],
        # the pump's, in the theme's text color
        "lines": [
            {
                "value": 20,
                "label": "Pump: 20 kPa",
                "vertical": False,
                "color": None,
                "style": "dashed",
            }
        ],
        "pairs": [],
    }

    chart.series = [
        Series.line("Pressure", [0, 1, 2], [1, math.nan, math.inf]),
        Series.line("Temperature", [0, 1, 2], [5, 6, 7], step=True),
    ]
    markup = chart_client.get(f"/_composeui/widget/{_widget_id(chart.renderer)}").text
    spec = _chart_spec(markup, chart)
    # uPlot's columns, the x shared; no NaN in JSON: a gap is null
    assert spec["data"] == [[0, 1, 2], [1, None, None], [5, 6, 7]]
    assert spec["series"] == [
        # the theme's colors, no fill; the temperature in steps, and in whole degrees
        {
            "name": "Pressure",
            "kind": "line",
            "color": None,
            "fill": False,
            "fill_color": None,
            "step": False,
            "whole": False,
        },
        {
            "name": "Temperature",
            "kind": "line",
            "color": None,
            "fill": False,
            "fill_color": None,
            "step": True,
            "whole": True,
        },
    ]
    plot = _element(markup, f"{_widget_id(chart.renderer)}-plot")
    assert plot.attributes["role"] == "img"
    assert plot.attributes["aria-label"] == (
        "Pressure Drop: Pressure, Temperature against Flow Rate (L/s); Pump: 20 kPa"
    )

    chart.series = [
        Series.line("Model", [2, 0, 1], [4, 0, 1]),  # sorted for uPlot
        Series.line("Measured", [0.5], [0.4]),
    ]
    spec = _chart_spec(
        chart_client.get(f"/_composeui/widget/{_widget_id(chart.renderer)}").text, chart
    )
    # each series by its own x, joined by the page
    assert spec["pairs"] == [[[0, 1, 2], [0, 1, 4]], [[0.5], [0.4]]]


def test_each_series_is_sent_with_how_it_is_drawn(
    chart_views: list[PipeChartMainView], chart_client: TestClient
) -> None:
    chart_client.get("/")
    (main_view,) = chart_views
    main_view.add_curve()
    main_view.add_measurements()
    chart = main_view.chart

    spec = _chart_spec(
        chart_client.get(f"/_composeui/widget/{_widget_id(chart.renderer)}").text, chart
    )
    assert [series["kind"] for series in spec["series"]] == ["line", "scatter"]
    assert len(spec["pairs"][1][0]) == len(MEASUREMENTS)  # the measured flow rates, their own x

    with collect_dirty() as dirty:
        chart.series = [attrs.evolve(curve, kind=ChartKind.SCATTER) for curve in chart.series]
        spec = _chart_spec(render_dirty(dirty), chart)
    assert [series["kind"] for series in spec["series"]] == ["scatter", "scatter"]


def test_a_long_series_is_thinned_keeping_its_peaks_and_gaps() -> None:
    count = 100_000
    y = [math.sin(index / 50) for index in range(count)]
    y[500], y[70_000] = 5.0, -5.0  # spikes the thinning must keep
    y[30_000] = math.nan
    chart = ChartView(series=[Series.line("Signal", range(count), y)])
    chart.render(RendererType.WEB)
    assert isinstance(chart.renderer, WebChartRenderer)

    spec = json.loads(chart.renderer.chart_json())

    xs, ys = spec["data"]
    assert len(xs) <= CHART_MAX_POINTS
    assert xs == sorted(xs)
    assert max(ys, key=lambda v: -math.inf if v is None else v) == 5.0
    assert min(ys, key=lambda v: math.inf if v is None else v) == -5.0
    assert ys[xs.index(30_000)] is None  # the gap stays a gap


def test_a_new_series_list_swaps_the_figure(
    chart_views: list[PipeChartMainView], chart_client: TestClient
) -> None:
    chart_client.get("/")
    (main_view,) = chart_views
    add = main_view.buttons.add

    response = chart_client.post(
        f"/_composeui/widget/{_widget_id(add.renderer)}", data={"event": "click"}
    )

    figure = _swapped(response.text, _widget_id(main_view.chart.renderer))
    assert figure.tag == "figure"
    spec = _chart_spec(response.text, main_view.chart)
    assert spec["series"] == [
        {
            "name": "D = 50 mm",
            "kind": "line",
            "color": None,
            "fill": False,
            "fill_color": None,
            "step": False,
            "whole": False,
        }
    ]


def test_the_page_loads_the_chart_script_only_from_its_own_script(
    client: TestClient, chart_client: TestClient
) -> None:
    """No tag loads the chart library with the page: its script does, once a chart shows."""
    for page in (client.get("/").text, chart_client.get("/").text):
        assert re.findall(r"<script src=\"[^\"]*uPlot", page) == []
    (address,) = re.findall(
        r'"(/_composeui/static/uPlot\.iife\.min\.js[^"]*)"', client.get("/").text
    )
    assert chart_client.get(address).is_success


def test_a_bar_chart_sends_its_categories_and_each_series_bars() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    main_view.router.navigate(main_view.router.chart.route)  # built once it shows
    energy = main_view.router.chart.energy
    assert isinstance(energy.renderer, WebChartRenderer)

    markup = energy.renderer.to_html()

    spec = _chart_spec(markup, energy)
    assert spec["categories"] == ["Kitchen", "Bedroom", "Office"]
    # each series' bars by their categories' indexes; no cooling in the bedroom
    assert spec["pairs"] == [[[0, 1, 2], [120, 80, 95]], [[0, 2], [30, 45]]]
    assert spec["series"] == [
        {
            "name": "Heating",
            "kind": "bar",
            "color": None,
            "fill": False,
            "fill_color": None,
            "step": False,
            "whole": True,
            "offset": pytest.approx(-0.2),
            "width": 0.4,
        },
        {
            "name": "Cooling",
            "kind": "bar",
            "color": None,
            "fill": False,
            "fill_color": None,
            "step": False,
            # its gap aside
            "whole": True,
            "offset": pytest.approx(0.2),
            "width": 0.4,
        },
    ]
    plot = _element(markup, f"{_widget_id(energy.renderer)}-plot")
    assert plot.attributes["aria-label"] == "Energy: Heating, Cooling for Kitchen, Bedroom, Office"


def test_a_line_over_bars_is_sent_with_the_slots_of_the_bars_alone() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    main_view.router.navigate(main_view.router.chart.route)  # built once it shows
    orders = main_view.router.chart.orders
    assert isinstance(orders.renderer, WebChartRenderer)

    spec = json.loads(orders.renderer.chart_json())

    shop, target, online = spec["series"]
    assert [series["kind"] for series in spec["series"]] == ["bar", "line", "bar"]
    # only the bars share a category's room
    assert (shop["offset"], shop["width"]) == (pytest.approx(-0.2), 0.4)
    assert (online["offset"], online["width"]) == (pytest.approx(0.2), 0.4)
    assert "offset" not in target
    assert spec["bar_step"] == 1
    assert spec["categories"] == ["Jan", "Feb", "Mar"]
    assert spec["data"] == [[0, 1, 2], [120, 140, 90], [100, 110, 125], [80, 95, 130]]
    assert _chart_spec(orders.renderer.to_html(), orders) == spec
    plot = _element(orders.renderer.to_html(), f"{_widget_id(orders.renderer)}-plot")
    assert plot.attributes["aria-label"] == "Orders: Shop, Target, Online for Jan, Feb, Mar"


def test_a_series_on_the_second_y_axis_is_sent_with_that_axis() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    main_view.router.navigate(main_view.router.chart.route)  # built once it shows
    sales = main_view.router.chart.sales
    assert isinstance(sales.renderer, WebChartRenderer)

    spec = json.loads(sales.renderer.chart_json())

    assert spec["y2"] == {"label": "Revenue (k€)", "unit": "k€", "log": True}
    assert [series.get("on_y2") for series in spec["series"]] == [None, True]
    # month 3's 0 a gap of the right axis' log, not of the left's
    assert spec["data"] == [[1, 2, 3], [120, 150, 90], [3.2, 41, None]]
    # no break-even on a log axis
    assert [(line["label"], line.get("on_y2")) for line in spec["lines"]] == [
        ("Minimum", None),
        ("Target", True),
    ]

    # nothing left at the right: no axis there, and month 3's revenue on the left's
    sales.series = [attrs.evolve(series, on_y2=False) for series in sales.series]
    sales.reference_lines = sales.reference_lines[:1]
    spec = json.loads(sales.renderer.chart_json())
    assert "y2" not in spec
    assert not any("on_y2" in series for series in spec["series"])
    assert spec["data"][2] == [3.2, 41, 0]


def test_an_axis_is_sent_with_its_bounds_but_one_of_categories() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    main_view.router.navigate(main_view.router.chart.route)  # built once it shows
    page = main_view.router.chart
    assert isinstance(page.load.renderer, WebChartRenderer)
    assert isinstance(page.orders.renderer, WebChartRenderer)
    page.orders.x = attrs.evolve(page.orders.x, minimum=1, maximum=2)

    load = json.loads(page.load.renderer.chart_json())
    orders = json.loads(page.orders.renderer.chart_json())

    assert (load["x"]["minimum"], load["x"]["maximum"]) == (0, 10)
    assert load["y"]["minimum"] == 0
    assert "maximum" not in load["y"]  # its top fits the data
    assert "minimum" not in orders["x"]  # the categories' own range


def test_a_time_axis_is_sent_with_how_precise_its_times_are() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    main_view.router.navigate(main_view.router.chart.route)  # built once it shows
    visits = main_view.router.chart.visits
    assert isinstance(visits.renderer, WebChartRenderer)

    spec = json.loads(visits.renderer.chart_json())
    first = (datetime.date(2026, 11, 1) - datetime.date(1970, 1, 1)).days * 86400

    assert spec["x"]["time"] == "day"  # dates alone
    assert spec["pairs"][0][0][:2] == [first, first + 86400]  # seconds since 1970, in UTC
    # a time of day: shown with its hours and minutes
    visits.series = [*visits.series, Series.scatter("Visit", [first + 9 * 3600], [1])]
    assert json.loads(visits.renderer.chart_json())["x"]["time"] == "minute"
    visits.x = attrs.evolve(visits.x, scale=Scale.LINEAR)
    assert "time" not in json.loads(visits.renderer.chart_json())["x"]


def test_stacked_bars_are_sent_with_their_bases_and_each_axis_its_stacks_reach() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    main_view.router.navigate(main_view.router.chart.route)  # built once it shows
    balance = main_view.router.chart.balance
    assert isinstance(balance.renderer, WebChartRenderer)

    spec = json.loads(balance.renderer.chart_json())

    heating, cooling, solar, target, visits = spec["series"]
    # by the points sent: the cooling's at the kitchen and the office alone
    assert spec["pairs"][1][0] == [0, 2]
    assert cooling["bases"] == [120, 95]
    assert (heating["bases"], solar["bases"], visits["bases"]) == ([0, 0, 0],) * 3
    assert "bases" not in target
    # each stack in its axis' slot
    assert (heating["offset"], visits["offset"]) == (pytest.approx(-0.2), pytest.approx(0.2))
    assert (spec["y"]["stack"], spec["y2"]["stack"]) == ([-60, 150], [0, 5])
    balance.bar_mode = BarMode.GROUPED
    assert "stack" not in json.loads(balance.renderer.chart_json())["y"]


def test_bars_without_categories_are_sent_at_their_x_on_a_linear_axis() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    main_view.router.navigate(main_view.router.chart.route)  # built once it shows
    ages = main_view.router.chart.ages
    assert isinstance(ages.renderer, WebChartRenderer)

    spec = json.loads(ages.renderer.chart_json())

    assert "categories" not in spec
    assert spec["x"]["log"] is False  # bars: never a log axis, even when asked
    assert spec["data"] == [[10, 20, 40], [4, 6, 5]]
    # the smallest step between two x, which a bar takes its share of
    assert spec["bar_step"] == 10
    assert (spec["series"][0]["offset"], spec["series"][0]["width"]) == (0, 8)


def test_a_horizontal_chart_is_sent_as_one_and_swapped_when_it_stands() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    main_view.router.navigate(main_view.router.chart.route)  # built once it shows
    pickups = main_view.router.chart.pickups
    assert isinstance(pickups.renderer, WebChartRenderer)

    spec = json.loads(pickups.renderer.chart_json())

    # the axes as they are, which the page lays out: the x down the side
    assert spec["horizontal"] is True
    assert (spec["x"]["label"], spec["y"]["label"]) == ("Station", "Pickups (k)")
    with collect_dirty() as dirty:
        pickups.horizontal = False
        spec = _chart_spec(render_dirty(dirty), pickups)
    assert "horizontal" not in spec


def test_a_chart_without_bars_sends_no_bar_step() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    main_view.router.navigate(main_view.router.chart.route)  # built once it shows
    chart = main_view.router.chart.chart
    assert isinstance(chart.renderer, WebChartRenderer)

    assert "bar_step" not in json.loads(chart.renderer.chart_json())


def test_a_log_axis_sends_only_what_it_can_show() -> None:
    main_view = ChartPagesMainView()
    main_view.render(RendererType.WEB)
    page = main_view.router.chart
    main_view.router.navigate(page.route)  # its charts are built once it shows
    chart, energy = page.chart, page.energy
    assert isinstance(chart.renderer, WebChartRenderer)
    assert isinstance(energy.renderer, WebChartRenderer)
    chart.series = [Series.line("Decay", [0, 1, 10, 100], [5, -1, 10, 100])]
    chart.x = attrs.evolve(chart.x, scale=Scale.LOG)
    chart.y = attrs.evolve(chart.y, scale=Scale.LOG)
    energy.series = [Series.bars("Heating", [1000, 0, 50])]
    energy.x = attrs.evolve(energy.x, scale=Scale.LOG)
    energy.y = attrs.evolve(energy.y, scale=Scale.LOG)

    spec = json.loads(chart.renderer.chart_json())
    assert (spec["x"]["log"], spec["y"]["log"]) == (True, True)
    # no x of 0 on a log axis: left out; a y of -1: a gap
    assert spec["data"] == [[1, 10, 100], [None, 10, 100]]
    bars = json.loads(energy.renderer.chart_json())
    assert (bars["x"]["log"], bars["y"]["log"]) == (False, True)  # x: its categories
    assert bars["data"] == [[0, 2], [1000, 50]]  # no bar of 0 on a log axis


def test_the_chart_s_corner_downloads_its_image_at_the_zoom_asked(
    chart_views: list[PipeChartMainView],
    chart_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("matplotlib")
    page = chart_client.get("/").text
    (main_view,) = chart_views
    main_view.add_curve()
    chart_id = _widget_id(main_view.chart.renderer)
    figure = _element(page, chart_id)
    links = [element for element in figure.descendants if element[0] == "a"]
    ((_, link),) = links
    assert link["href"] == f"/_composeui/widget/{chart_id}/image?format=pdf"
    assert "download" in link
    assert (
        "select",
        {
            "class": "select select-xs join-item w-auto",
            "aria-label": "Image format",
            "data-chart-format": None,
        },
    ) in figure.descendants
    drawn: list[chartimage.ImageOptions] = []
    draw = chartimage.chart_image_bytes

    def chart_image_bytes(
        chart: ChartView, image_format: str, options: chartimage.ImageOptions
    ) -> bytes:
        drawn.append(options)
        return draw(chart, image_format, options)

    monkeypatch.setattr(chartimage, "chart_image_bytes", chart_image_bytes)

    response = chart_client.get(
        f"/_composeui/widget/{chart_id}/image",
        params={"format": "svg", "x_min": 0.5, "x_max": "1.5", "y2_min": 1, "y2_max": 100},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"Pressure Drop.svg\"; filename*=UTF-8''Pressure%20Drop.svg"
    )
    assert "Flow Rate (L/s)" in response.text
    (options,) = drawn
    assert (options.x_range, options.y_range, options.y2_range) == ((0.5, 1.5), None, (1, 100))
    bad = chart_client.get(f"/_composeui/widget/{chart_id}/image", params={"format": "jpg"})
    assert bad.status_code == 400
    assert (
        chart_client.get(
            f"/_composeui/widget/{chart_id}/image", params={"x_min": "a", "x_max": "1"}
        ).status_code
        == 400
    )
    infinite = chart_client.get(
        f"/_composeui/widget/{chart_id}/image", params={"x_min": "-inf", "x_max": "1"}
    )
    assert infinite.status_code == 400
    assert (
        chart_client.get(
            f"/_composeui/widget/{_widget_id(main_view.buttons.add.renderer)}/image"
        ).status_code
        == 404
    )


def test_without_matplotlib_the_page_draws_the_chart_s_png(
    chart_views: list[PipeChartMainView],
    chart_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chartimage, "is_available", lambda: False)
    page = chart_client.get("/").text
    (main_view,) = chart_views
    chart_id = _widget_id(main_view.chart.renderer)
    figure = _element(page, chart_id)

    tags = [tag for tag, _ in figure.descendants]
    assert "select" not in tags
    assert "a" not in tags
    (button,) = [attributes for tag, attributes in figure.descendants if tag == "button"]
    assert button["data-chart-png"] == "Pressure Drop.png"
    assert chart_client.get(f"/_composeui/widget/{chart_id}/image").status_code == 404


def test_a_click_on_the_chart_reaches_the_view() -> None:
    main_view = BatmanMainView()
    main_view.render(RendererType.WEB)
    chart = main_view.chart
    assert isinstance(chart.renderer, WebChartRenderer)

    with collect_dirty() as dirty:
        chart.renderer.dispatch("click", {"x": "0", "y": "0.5"})
        message = _swapped(render_dirty(dirty), _widget_id(main_view.message.renderer))
    assert message.text == "I'm Batman"
    for form in ({"x": "a", "y": "0"}, {"x": "nan", "y": "0"}, {}):
        with pytest.raises(UnsupportedEventError):
            chart.renderer.dispatch("click", form)
    chart.is_enabled = False
    with pytest.raises(UnsupportedEventError):
        chart.renderer.dispatch("click", {"x": "0", "y": "0"})


def test_a_series_sends_its_own_color_and_fill() -> None:
    main_view = BatmanMainView()
    main_view.render(RendererType.WEB)
    assert isinstance(main_view.chart.renderer, WebChartRenderer)

    spec = json.loads(main_view.chart.renderer.chart_json())

    assert [(series["color"], series["fill"]) for series in spec["series"]] == [
        ("#ffd700", True),
        ("#ffd700", True),
        ("#000000", True),
        ("#000000", True),
    ]


def test_the_chart_s_plot_is_as_tall_as_its_view_says() -> None:
    chart = ChartView(title="Pressure")
    chart.render(RendererType.WEB)
    assert isinstance(chart.renderer, WebChartRenderer)
    plot_id = f"{_widget_id(chart.renderer)}-plot"
    assert _element(chart.renderer.to_html(), plot_id).attributes["class"] == "h-72 w-full"

    with collect_dirty() as dirty:
        chart.height = 420
        plot = _element(render_dirty(dirty), plot_id)  # the figure swapped, at its height

    assert plot.attributes["style"] == "height: 420px"
    assert plot.attributes["class"] == "w-full"


def test_a_long_series_s_bucket_of_gaps_only_stays_a_gap() -> None:
    count = 100_000
    y = [math.sin(index / 50) for index in range(count)]
    y[40_000:41_000] = [math.nan] * 1000  # a whole bucket, and more
    chart = ChartView(series=[Series.line("Signal", range(count), y)])
    chart.render(RendererType.WEB)
    assert isinstance(chart.renderer, WebChartRenderer)

    xs, ys = json.loads(chart.renderer.chart_json())["data"]

    gap = [y for x, y in zip(xs, ys) if 40_000 <= x < 41_000]
    assert gap != []
    assert all(y is None for y in gap)
