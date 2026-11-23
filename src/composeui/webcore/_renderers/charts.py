"""The web renderer of charts, which the page's script draws with uPlot (`charts.js`)."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any, Final

from markupsafe import Markup
from typing_extensions import Protocol, override

from composeui.core import chartimage
from composeui.core.renderer import ViewLike
from composeui.core.view import BarMode, ChartKind, ChartView
from composeui.webcore.webrenderer import UnsupportedEventError, WebRenderer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from composeui.core.signal import Signal
    from composeui.core.view import Axis, ReferenceLine, Series


class ChartViewLike(ViewLike, Protocol):
    title: str
    x: Axis
    y: Axis
    y2: Axis
    series: list[Series]
    reference_lines: list[ReferenceLine]
    categories: list[str]
    bar_mode: BarMode
    save_image_text: str
    clicked: Signal[float, float]
    height: int | None


#: the points a series sends at most, about twice a wide chart's pixels: a longer one is
#: thinned to the extremes of each bucket of its points, so its peaks stay
CHART_MAX_POINTS: Final = 4000


def _json_number(value: float) -> float | None:
    """Get `value` for JSON, which has no NaN or infinity: None, uPlot's gap."""
    return value if math.isfinite(value) else None


def _thin(x: list[float], y: list[float], max_points: int) -> tuple[list[float], list[float]]:
    """Keep each bucket's lowest and highest point, and a gap it holds, of a long series."""
    if len(x) <= max_points:
        return x, y
    # two points a bucket, and room for a gap in some of them
    bucket_count = max(1, max_points // 3)
    kept: list[int] = []
    for bucket in range(bucket_count):
        start = bucket * len(x) // bucket_count
        end = (bucket + 1) * len(x) // bucket_count
        drawn = [index for index in range(start, end) if math.isfinite(y[index])]
        indexes = set()
        if len(drawn) > 0:
            indexes.add(min(drawn, key=y.__getitem__))
            indexes.add(max(drawn, key=y.__getitem__))
        if len(drawn) < end - start:
            indexes.add(next(i for i in range(start, end) if not math.isfinite(y[i])))
        kept.extend(sorted(indexes))
    return [x[index] for index in kept], [y[index] for index in kept]


def _chart_points(
    series: Series, categories: list[str], *, x_log: bool, y_log: bool
) -> tuple[list[float], list[float]]:
    """Get a series' points as uPlot draws them: by ascending x, thinned when long.

    A log axis' values it can't show are left out (`ChartView.drawn_points`), and a bar
    series gives the bars it draws (`ChartView.bars_of`).
    """
    if series.kind is ChartKind.BAR:
        xs, ys = ChartView.bars_of(series, categories, y_log=y_log)
    else:
        xs, ys = ChartView.drawn_points(series, x_log=x_log, y_log=y_log)
    points = [(x, y) for x, y in zip(xs, ys) if math.isfinite(x)]
    if any(a[0] > b[0] for a, b in zip(points, points[1:])):
        points.sort(key=lambda point: point[0])
    x, y = [point[0] for point in points], [point[1] for point in points]
    return _thin(x, y, CHART_MAX_POINTS)


#: how precise a time axis' times are, by the format they show in (`ChartView.time_format`)
_TIME_PRECISIONS = {"%Y-%m-%d": "day", "%Y-%m-%d %H:%M": "minute", "%Y-%m-%d %H:%M:%S": "second"}


def _add_y2(spec: dict[str, Any], view: ChartViewLike, lines: list[ReferenceLine]) -> None:
    """Give the chart its second y axis, at the right, and flag `on_y2` what is on it.

    Shown only with something on it.
    """
    spec["y2"] = _axis_spec(view.y2, is_log=view.y2.is_log)
    for series, sent in zip(view.series, spec["series"]):
        if series.on_y2:
            sent["on_y2"] = True
    for line, sent in zip(lines, spec["lines"]):
        if line.is_on_y2:
            sent["on_y2"] = True


def _add_stacks(spec: dict[str, Any], view: ChartViewLike, xs: list[list[float]]) -> None:
    """Give each stacked bar series its bars' bases, at the `xs` sent, and each y axis its reach.

    How far the stacks of a y axis reach, which its range takes in: uPlot fits the
    series' own values.
    """
    reach: dict[bool, list[float]] = {}
    for index, bases in ChartView.stack_bases(view.series, view.categories).items():
        series = view.series[index]
        bar_xs, heights = ChartView.bars_of(series, view.categories)
        base_at = dict(zip(bar_xs, bases))
        spec["series"][index]["bases"] = [base_at[x] for x in xs[index]]
        reach.setdefault(series.on_y2, []).extend(
            end for base, height in zip(bases, heights) for end in (base, base + height)
        )
    for on_y2, ends in reach.items():
        # no bar drawn: 0, which bars stand on anyway
        spec["y2" if on_y2 else "y"]["stack"] = [min(ends, default=0), max(ends, default=0)]


def _x_spec(view: ChartViewLike, *, is_log: bool) -> dict[str, Any]:
    """Get what the page's script draws the x axis with, e.g. how precise its times are."""
    # an x axis of categories has no bounds: they are its own
    spec = _axis_spec(view.x, is_log=is_log, is_bounded=len(view.categories) == 0)
    if ChartView.is_x_time(view.x, view.categories):
        # which the legend shows at the cursor
        time_format = ChartView.time_format(x for series in view.series for x in series.x)
        spec["time"] = _TIME_PRECISIONS[time_format]
    return spec


def _axis_spec(axis: Axis, *, is_log: bool, is_bounded: bool = True) -> dict[str, Any]:
    """Get what the page's script draws an axis with: its bounds only when it has them."""
    spec: dict[str, Any] = {"label": axis.label, "unit": axis.unit, "log": is_log}
    if is_bounded:
        spec.update(
            (name, bound)
            for name, bound in (("minimum", axis.minimum), ("maximum", axis.maximum))
            if bound is not None
        )
    return spec


def _query_range(query: Mapping[str, str], axis: str) -> tuple[float, float] | None:
    """Get an axis' range from a query's `x_min` and `x_max` (or `y_...`, `y2_...`), if any."""
    low, high = query.get(f"{axis}_min"), query.get(f"{axis}_max")
    if low is None or high is None:
        return None
    bounds = (float(low), float(high))  # a ValueError for text that isn't a number
    if not all(math.isfinite(bound) for bound in bounds):
        msg = f"Cannot draw the {axis} range {bounds}."
        raise ValueError(msg)
    return bounds


class WebChartRenderer(WebRenderer[ChartViewLike]):
    """A chart the page's script draws with uPlot, from the JSON in its `data-chart`.

    The user zooms by dragging across it, back out with a double click, and reads the
    values at the cursor in its legend. A series' legend entry hides or shows it. A new
    `series` list swaps the figure, the page keeping the user's zoom (see `charts.js`).

    A click on the plot, rather than the end of a drag, posts its point: `clicked` emits
    it. Its corner downloads its image as a report's figure, in the format picked beside.
    Matplotlib draws it from the view's data at the user's zoom (see `image`), the same
    file as Qt saves. Without matplotlib, the page draws a PNG of what it shows instead.
    """

    _role = "chart"
    is_labelable = False

    def __init__(self, view: ChartViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            dict.fromkeys(
                (
                    "title",
                    "x",
                    "y",
                    "y2",
                    "series",
                    "reference_lines",
                    "categories",
                    "bar_mode",
                    "save_image_text",
                    "height",
                ),
                self._mark_dirty,
            )
        )

    def chart_json(self) -> str:
        """Get what the page's script draws, as JSON."""
        view = self._view
        x_log = ChartView.is_x_log(view.x, view.categories, view.series)
        slots = ChartView.bar_slots(view.series, view.categories, view.bar_mode)
        lines = ChartView.drawn_lines(
            view.reference_lines, x_log=x_log, y_log=view.y.is_log, y2_log=view.y2.is_log
        )
        spec: dict[str, Any] = {
            "title": view.title,
            "x": _x_spec(view, is_log=x_log),
            "y": _axis_spec(view.y, is_log=view.y.is_log),
            "series": [
                {
                    "name": series.name,
                    "kind": series.kind.name.lower(),
                    # None: the theme's
                    "color": series.color,
                    "fill": series.fill,
                    # None: the color of its line
                    "fill_color": series.fill_color,
                    "step": series.step,
                    # its hovered values shown as integers, e.g. counts
                    "whole": ChartView.is_whole(series.y),
                }
                for series in view.series
            ],
            "lines": [
                # a color of None: the theme's text
                {
                    "value": line.value,
                    "label": line.label,
                    "vertical": line.vertical,
                    "color": line.color,
                    "style": line.style.name.lower(),
                }
                for line in lines
            ],
        }
        if ChartView.has_y2(view.series, view.reference_lines):
            _add_y2(spec, view, lines)
        # a bar in its group, by its middle's offset from its x, and its width
        for index, (offset, width) in slots.items():
            spec["series"][index].update({"offset": offset, "width": width})
        if len(slots) > 0:
            # the room between two bars' x: half of it past the first and the last
            spec["bar_step"] = ChartView.bar_step(view.series, view.categories)
        if len(view.categories) > 0:
            spec["categories"] = view.categories
        points = [
            _chart_points(
                series,
                view.categories,
                x_log=x_log,
                y_log=(view.y2 if series.on_y2 else view.y).is_log,
            )
            for series in view.series
        ]
        if view.bar_mode is BarMode.STACKED:
            _add_stacks(spec, view, [x for x, _y in points])
        if len(points) > 0 and all(x == points[0][0] for x, _y in points):
            # uPlot's own columns: the x shared, then each series' y
            spec["data"] = [points[0][0], *([_json_number(v) for v in y] for _x, y in points)]
        else:
            # each series by its own x, joined in the browser
            spec["pairs"] = [[x, [_json_number(v) for v in y]] for x, y in points]
        return json.dumps(spec, allow_nan=False, separators=(",", ":"))

    def _description(self) -> str:
        """Describe the chart to a screen reader, which can't read its canvas."""
        view = self._view
        names = ", ".join(series.name for series in view.series)
        if len(view.categories) > 0:
            x_label, link = ", ".join(view.categories), "for"
        else:
            x_label, link = view.x.label, "against"
        description = f"{names} {link} {x_label}" if names and x_label else names or x_label
        labels = ", ".join(line.label for line in view.reference_lines if line.label)
        description = (
            f"{description}; {labels}" if description and labels else description or labels
        )
        return f"{view.title}: {description}" if view.title and description else view.title

    @override
    def dispatch(self, event: str, form: Mapping[str, str]) -> None:
        # a click on the plot (see `charts.js`), at a point in the axes' values
        if event != "click" or not self.is_enabled:
            super().dispatch(event, form)
        try:
            x, y = float(form.get("x", "")), float(form.get("y", ""))
        except ValueError:
            raise UnsupportedEventError(self, event) from None
        if not (math.isfinite(x) and math.isfinite(y)):
            super().dispatch(event, form)
        self._view.clicked.emit(x, y)

    def image(self, image_format: str, query: Mapping[str, str]) -> tuple[str, bytes]:
        """Draw the chart's image, e.g. at the zoom in `query` (`x_min`, `x_max`...).

        Returns the file's name and content; raises `ValueError` for a format or a
        range it can't draw, and `ImportError` without matplotlib.
        """
        view = self._view
        assert isinstance(view, ChartView)  # the chart renderer's only view
        options = chartimage.ImageOptions(
            x_range=_query_range(query, "x"),
            y_range=_query_range(query, "y"),
            y2_range=_query_range(query, "y2"),
        )
        content = chartimage.chart_image_bytes(view, image_format, options)
        return chartimage.image_name(view.title, image_format.lower()), content

    @override
    def to_html(self, *, oob: bool = False) -> Markup:
        title = self._view.title
        # the corner's controls at the end of the row, the title in the middle of the rest
        caption = (
            Markup(
                '<figcaption class="min-w-0 flex-1 text-center font-semibold">{}</figcaption>'
            ).format(title)
            if title
            else Markup('<span class="flex-1"></span>')
        )
        return (
            # a column: a card's figures are rows of images otherwise (daisyUI's `card`)
            Markup(
                '<figure {root_attributes} class="flex w-full flex-col gap-2">'
                '<div class="flex w-full items-center gap-2">{caption}{save_image_html}</div>'
                '<div id="{widget_id}-plot" data-chart="{chart_json}"'
                ' role="img" aria-label="{description}"'
                "{height_attributes}></div></figure>"
            ).format(
                root_attributes=self._root_attributes(oob=oob),
                caption=caption,
                save_image_html=self._save_image_html(),
                widget_id=self.widget_id,
                chart_json=self.chart_json(),
                description=self._description(),
                height_attributes=self._height_attributes(),
            )
        )

    def _height_attributes(self) -> Markup:
        """Get the plot's height: the view's, or the page's own (the script fits it to it)."""
        height = self._view.height
        if height is None:
            return Markup(' class="h-72 w-full"')
        return Markup(' class="w-full" style="height: {}px"').format(int(height))

    def _save_image_html(self) -> Markup:
        """Get the figure's corner: its image's download, in a format picked beside it."""
        text = self._view.save_image_text
        if not chartimage.is_available():
            # no matplotlib: the page draws what it shows, as a PNG
            name = chartimage.image_name(self._view.title, "png")
            return Markup(
                '<button type="button" class="btn btn-ghost btn-xs" data-chart-png="{}">'
                "{} (PNG)</button>"
            ).format(name, text)
        options = Markup("").join(
            Markup('<option value="{}">{}</option>').format(image_format, image_format.upper())
            for image_format in ("pdf", "svg", "png")
        )
        # a plain link: htmx can't start a download. The page's script adds the zoom
        return Markup(
            '<div class="join">'
            '<select class="select select-xs join-item w-auto" aria-label="Image format"'
            " data-chart-format>{options}</select>"
            '<a class="btn btn-ghost btn-xs join-item" data-chart-image download'
            ' href="/_composeui/widget/{widget_id}/image?format=pdf">{text}</a></div>'
        ).format(options=options, widget_id=self.widget_id, text=text)
