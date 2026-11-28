"""A chart as a report's figure, drawn by matplotlib alike on every backend, or with none.

A screen chart follows its window and theme; a report's figure has its page's size and
fonts, and a light background. So the figure is drawn from the `ChartView`'s data, e.g.
by a batch run writing a report's figures:

    save_chart_image(chart, Path("pressure.pdf"), ImageOptions(width_mm=80))

It needs the `report` extra (matplotlib), imported only by these functions. Without it
they raise an `ImportError` naming the extra, and `is_available` is False.
"""

from __future__ import annotations

import contextlib
import datetime
import importlib.util
import io
import threading
from typing import TYPE_CHECKING, Any

import attrs

from composeui.core._views.charts import SECONDS_PER_DAY
from composeui.core.view import BarMode, ChartKind, ChartView, LineStyle

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from matplotlib.artist import Artist
    from matplotlib.axes import Axes
    from matplotlib.container import Container
    from matplotlib.figure import Figure
    from matplotlib.text import Annotation

    from composeui.core.view import ReferenceLine

__all__ = ["ImageOptions", "chart_figure", "save_chart_image"]


#: the formats of an image, by its file's suffix: vector ones, then PNG, a raster
FORMATS = ("pdf", "svg", "eps", "png")
MEDIA_TYPES = {
    "pdf": "application/pdf",
    "svg": "image/svg+xml",
    "eps": "application/postscript",
    "png": "image/png",
}
#: Okabe and Ito's colors, told apart with color blindness too, the yellow last: it is
#: faint on white
SERIES_COLORS = (
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#E69F00",
    "#56B4E9",
    "#000000",
    "#F0E442",
)
#: a dash pattern, a marker and a hatch per series: printed in black and white, a figure
#: still tells its series apart
LINE_STYLES: tuple[Any, ...] = (
    "-",
    (0, (5, 2)),
    (0, (5, 2, 1, 2)),
    (0, (1, 1.5)),
    (0, (8, 2, 2, 2)),
    (0, (3, 1, 1, 1, 1, 1)),
)
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*")
HATCHES = ("", "//", "..", "xx", "\\\\", "oo", "--", "++")
#: a reference line's color, unless it has its own: the axes'
REFERENCE_LINE_COLOR = "#333333"
#: a reference line's dash pattern, by its style
REFERENCE_LINE_STYLES: dict[LineStyle, Any] = {
    LineStyle.SOLID: "-",
    LineStyle.DASHED: (0, (5, 3)),
    LineStyle.DOTTED: (0, (1, 2)),
    LineStyle.DASH_DOT: (0, (5, 2, 1, 2)),
}
#: the series a legend lists inside the axes; more, and it goes beside them
_INSIDE_LEGEND_MAX = 3
_MM_PER_INCH = 25.4


@attrs.frozen
class ImageOptions:
    """How a chart's image looks: its size, fonts and range."""

    #: an A4 page's text width
    width_mm: float = 160
    height_mm: float = 100
    #: the resolution of a PNG; a vector image has none
    dpi: int = 300
    #: points, as the report's body text
    font_size: float = 9
    #: a report usually captions its figures itself
    show_title: bool = False
    #: the region shown, e.g. the one the user zoomed into; None: all the data
    x_range: tuple[float, float] | None = None
    y_range: tuple[float, float] | None = None
    #: the second y axis' (`ChartView.y2`), if the chart shows it
    y2_range: tuple[float, float] | None = None


#: an image for a report's page, in its body text's font size
DEFAULT_OPTIONS = ImageOptions()


def is_available() -> bool:
    """Check whether matplotlib, the `report` extra, is installed."""
    return importlib.util.find_spec("matplotlib") is not None


def _require() -> None:
    if not is_available():
        msg = (
            "A chart's image is drawn by matplotlib: install composeui's `report` extra"
            " (pip install 'composeui[report]')."
        )
        raise ImportError(msg)


#: held while a block depends on Matplotlib's global settings, which every thread shares
#: (reentrant: a block can call `chart_figure`, which enters `image_style` again)
_STYLE_LOCK = threading.RLock()


@contextlib.contextmanager
def image_style(options: ImageOptions = DEFAULT_OPTIONS) -> Iterator[None]:
    """Draw and save figures with the options' fonts while the block runs.

    Text stays text in a vector image: TrueType fonts in a PDF or EPS, ``<text>`` in an
    SVG. So its labels can still be edited or searched. Matplotlib's global settings are
    left as they were: wrap a `chart_figure` saved with `Figure.savefig` in it too. One
    thread at a time runs such a block: an export of another thread waits for it to end.
    """
    _require()
    import matplotlib as mpl  # noqa: PLC0415 (an optional dependency, loaded when used)

    size = options.font_size
    with (
        _STYLE_LOCK,
        mpl.rc_context(
            {
                "pdf.fonttype": 42,
                "ps.fonttype": 42,
                "svg.fonttype": "none",
                "font.size": size,
                "axes.titlesize": size * 1.1,
                "axes.labelsize": size,
                "xtick.labelsize": size * 0.9,
                "ytick.labelsize": size * 0.9,
                "legend.fontsize": size * 0.9,
                "figure.facecolor": "white",
                "axes.facecolor": "white",
                "savefig.facecolor": "white",
                "axes.edgecolor": "#333333",
                "axes.grid": True,
                "grid.color": "#e5e5e5",
                "grid.linewidth": 0.5,
                "axes.axisbelow": True,
            }
        ),
    ):
        yield


def chart_figure(chart: ChartView, options: ImageOptions = DEFAULT_OPTIONS) -> Figure:
    """Draw `chart` as a report's figure, which app code can add to before saving it.

    Save it in `image_style` for its text to stay text, or with `save_chart_image`.
    """
    _require()
    from matplotlib.dates import (  # noqa: PLC0415 (an optional dependency, loaded when used)
        AutoDateLocator,
        ConciseDateFormatter,
    )
    from matplotlib.figure import Figure  # noqa: PLC0415 (an optional dependency, loaded when used)

    with image_style(options):
        figure = Figure(
            figsize=(options.width_mm / _MM_PER_INCH, options.height_mm / _MM_PER_INCH),
            dpi=options.dpi,
            layout="constrained",
        )
        axes = figure.add_subplot()
        # each y axis' own, by whether it is the second: the same without a second one
        sides = {False: axes, True: axes}
        if ChartView.has_y2(chart.series, chart.reference_lines):
            sides[True] = right = axes.twinx()
            right.set_ylabel(chart.y2.label)
            right.grid(visible=False)  # the first axis' lines alone
        handles = _draw_series(sides, chart)
        labels = _draw_reference_lines(sides, chart)
        if options.show_title and chart.title:
            axes.set_title(chart.title)
        # horizontal, the x down the left side, the y along the bottom
        axes.set_xlabel(chart.y.label if chart.horizontal else chart.x.label)
        axes.set_ylabel(chart.x.label if chart.horizontal else chart.y.label)
        # the app's bounds, then the user's zoom over them
        if len(chart.categories) == 0:
            scale = _x_scale(chart)
            bounds = chart.x.bounded(*(value / scale for value in _x_range(axes, chart)))
            _set_x_range(axes, chart, *(value * scale for value in bounds))
        _set_y_range(axes, chart, *chart.y.bounded(*_y_range(axes, chart)))
        if sides[True] is not axes:  # without a second y axis, its bounds bound nothing
            sides[True].set_ylim(*chart.y2.bounded(*sides[True].get_ylim()))
        if options.x_range is not None:
            _set_x_range(axes, chart, *(value * _x_scale(chart) for value in options.x_range))
        if options.y_range is not None:
            _set_y_range(axes, chart, *options.y_range)
        if options.y2_range is not None:
            sides[True].set_ylim(*options.y2_range)
        _hide_labels_past(sides, labels, chart)
        if ChartView.is_x_time(chart.x, chart.categories):
            # in UTC, as the times were given (see `Scale.TIME`)
            locator = AutoDateLocator(tz=datetime.timezone.utc)
            axes.xaxis.set_major_locator(locator)
            axes.xaxis.set_major_formatter(ConciseDateFormatter(locator, tz=datetime.timezone.utc))
        _add_legend(figure, axes, handles, is_inside=sides[True] is axes)
    return figure


def _x_range(axes: Axes, chart: ChartView) -> tuple[float, float]:
    """Get the range of the chart's x axis, its lowest value first: down the side horizontal."""
    low, high = sorted(axes.get_ylim() if chart.horizontal else axes.get_xlim())
    return low, high


def _set_x_range(axes: Axes, chart: ChartView, low: float, high: float) -> None:
    if chart.horizontal:
        axes.set_ylim(high, low)  # the first value at the top
    else:
        axes.set_xlim(low, high)


def _y_range(axes: Axes, chart: ChartView) -> tuple[float, float]:
    """Get the range of the chart's y axis: along the bottom horizontal."""
    low, high = axes.get_xlim() if chart.horizontal else axes.get_ylim()
    return low, high


def _set_y_range(axes: Axes, chart: ChartView, low: float, high: float) -> None:
    if chart.horizontal:
        axes.set_xlim(low, high)
    else:
        axes.set_ylim(low, high)


def _draw_series(sides: dict[bool, Axes], chart: ChartView) -> list[Artist | Container]:
    """Draw each series as its kind, on its y axis (`sides`, by whether it is the second).

    Matplotlib draws the lines and dots over the bars of the same axis. Returns what the
    legend names, in the series' order.
    """
    handles: list[Artist | Container] = []
    x_log = ChartView.is_x_log(chart.x, chart.categories, chart.series)
    _lay_out_axes(sides, chart, x_log=x_log)
    slots = ChartView.bar_slots(chart.series, chart.categories, chart.bar_mode)
    is_stacked = chart.bar_mode is BarMode.STACKED
    bases = ChartView.stack_bases(chart.series, chart.categories) if is_stacked else {}
    scale = _x_scale(chart)
    for index, series in enumerate(chart.series):
        axes = sides[series.on_y2]
        y_log = chart.y2.is_log if series.on_y2 else chart.y.is_log
        color = series.color or SERIES_COLORS[index % len(SERIES_COLORS)]
        if series.kind is ChartKind.BAR:
            xs, heights = ChartView.bars_of(series, chart.categories, y_log=y_log)
            offset, width = slots[index]
            places = [(x + offset) * scale for x in xs]
            hatch = HATCHES[index % len(HATCHES)]
            if chart.horizontal:
                bars = axes.barh(
                    places,
                    heights,
                    left=bases.get(index, 0),
                    height=width * scale,
                    color=color,
                    hatch=hatch,
                    edgecolor="white",
                    linewidth=0.5,
                    label=series.name,
                )
            else:
                bars = axes.bar(
                    places,
                    heights,
                    bottom=bases.get(index, 0),
                    width=width * scale,
                    color=color,
                    hatch=hatch,
                    edgecolor="white",
                    linewidth=0.5,
                    label=series.name,
                )
            handles.append(bars)
            continue
        x, y = ChartView.drawn_points(series, x_log=x_log, y_log=y_log)
        x = [value * scale for value in x]
        if series.kind is ChartKind.SCATTER:
            handles += axes.plot(
                x,
                y,
                linestyle="none",
                marker=MARKERS[index % len(MARKERS)],
                markersize=4,
                markeredgewidth=0.5,
                markeredgecolor="white",
                color=color,
                label=series.name,
            )
        else:
            # a NaN is a gap in a matplotlib line too; its path simplification keeps what
            # shows at the figure's resolution, so a long series needs no thinning
            handles += axes.plot(
                x,
                y,
                linestyle=LINE_STYLES[index % len(LINE_STYLES)],
                linewidth=1.2,
                color=color,
                label=series.name,
                # each value held until the next point
                drawstyle="steps-post" if series.step else "default",
            )
            if series.fill:  # down to 0, e.g. a shape
                axes.fill_between(
                    x,
                    y,
                    0,
                    color=series.fill_color or color,
                    linewidth=0,
                    step="post" if series.step else None,
                )
    return handles


def _lay_out_axes(sides: dict[bool, Axes], chart: ChartView, *, x_log: bool) -> None:
    """Give the axes their scales and categories: horizontal, the x down the left side."""
    axes = sides[False]
    if x_log:
        axes.set_xscale("log")
    if chart.y.is_log:
        if chart.horizontal:
            axes.set_xscale("log")
        else:
            axes.set_yscale("log")
    if chart.y2.is_log:
        sides[True].set_yscale("log")
    if len(chart.categories) > 0:
        if chart.horizontal:
            axes.set_yticks(range(len(chart.categories)), chart.categories)
        else:
            axes.set_xticks(range(len(chart.categories)), chart.categories)
        axes.grid(visible=False, axis="y" if chart.horizontal else "x")
    if chart.horizontal:
        axes.invert_yaxis()  # the first x at the top


def _draw_reference_lines(
    sides: dict[bool, Axes], chart: ChartView
) -> list[tuple[ReferenceLine, Annotation]]:
    """Draw the chart's reference lines, labeled inside the axes, at their ends.

    Returns each line with its label, which `_hide_labels_past` hides once the range is
    set: matplotlib doesn't clip it.
    """
    labels: list[tuple[ReferenceLine, Annotation]] = []
    x_log = ChartView.is_x_log(chart.x, chart.categories, chart.series)
    lines = ChartView.drawn_lines(
        chart.reference_lines, x_log=x_log, y_log=chart.y.is_log, y2_log=chart.y2.is_log
    )
    for line in lines:
        axes = sides[line.is_on_y2]
        color = line.color or REFERENCE_LINE_COLOR
        style = REFERENCE_LINE_STYLES[line.style]
        value = line.value * _x_scale(chart) if line.vertical else line.value
        # not in the legend, which names the series: its label is beside it
        if line.vertical != chart.horizontal:  # upright: at an x, or at a y horizontal
            axes.axvline(value, color=color, linestyle=style, linewidth=1)
            # at its top, left of it (now, after the data): the x in data, the y in the
            # axes' share
            label = axes.annotate(
                line.label,
                (value, 1),
                xycoords=axes.get_xaxis_transform(),
                xytext=(-3, -3),
                textcoords="offset points",
                ha="right",
                va="top",
                color=color,
            )
        else:
            axes.axhline(value, color=color, linestyle=style, linewidth=1)
            # at its right end, over it
            label = axes.annotate(
                line.label,
                (1, value),
                xycoords=axes.get_yaxis_transform(),
                xytext=(-3, 2),
                textcoords="offset points",
                ha="right",
                va="bottom",
                color=color,
            )
        labels.append((line, label))
    return labels


def _hide_labels_past(
    sides: dict[bool, Axes], labels: list[tuple[ReferenceLine, Annotation]], chart: ChartView
) -> None:
    """Hide the label of a reference line past the range shown, e.g. the axis' bounds."""
    for line, label in labels:
        axes = sides[line.is_on_y2]
        is_upright = line.vertical != chart.horizontal
        low, high = sorted(axes.get_xlim() if is_upright else axes.get_ylim())
        value = line.value * _x_scale(chart) if line.vertical else line.value
        label.set_visible(low <= value <= high)


def _x_scale(chart: ChartView) -> float:
    """Get matplotlib's x of the chart's 1: on a time axis, its days rather than seconds."""
    return 1 / SECONDS_PER_DAY if ChartView.is_x_time(chart.x, chart.categories) else 1.0


def _add_legend(
    figure: Figure, axes: Axes, handles: list[Artist | Container], *, is_inside: bool
) -> None:
    """Name the series, in their order, beside the axes when there are more than a few.

    Not `is_inside` (two y axes): beside them too. The place matplotlib finds in `axes`
    avoids what `axes` draws alone, not what the other y axis draws.
    """
    if len(handles) == 0:
        return
    if is_inside and len(handles) <= _INSIDE_LEGEND_MAX:
        axes.legend(handles=handles, frameon=False)
    else:
        figure.legend(handles=handles, loc="outside right upper", frameon=False)


def save_figure(figure: Figure, path: Path, options: ImageOptions = DEFAULT_OPTIONS) -> None:
    """Save `figure` to `path`, in the format its suffix names (see `FORMATS`)."""
    image_format = _format_of(path.suffix.lstrip("."))
    with image_style(options):
        figure.savefig(path, format=image_format, dpi=options.dpi)


def save_chart_image(
    chart: ChartView,
    path: Path,
    options: ImageOptions = DEFAULT_OPTIONS,
) -> None:
    """Save `chart`'s figure to `path`, in the format its suffix names (see `FORMATS`)."""
    _format_of(path.suffix.lstrip("."))  # before drawing a figure it can't save
    save_figure(chart_figure(chart, options), path, options)


def chart_image_bytes(
    chart: ChartView,
    image_format: str,
    options: ImageOptions = DEFAULT_OPTIONS,
) -> bytes:
    """Get `chart`'s figure as a file of `image_format`'s (see `FORMATS`), e.g. to send."""
    image_format = _format_of(image_format)
    figure = chart_figure(chart, options)
    buffer = io.BytesIO()
    with image_style(options):
        figure.savefig(buffer, format=image_format, dpi=options.dpi)
    return buffer.getvalue()


def image_name(title: str, image_format: str) -> str:
    """Get a file name for the image of a chart of `title`, as a file can be named."""
    stem = "".join(
        character if character.isalnum() or character in " -_" else "_" for character in title
    ).strip()
    return f"{stem or 'chart'}.{image_format}"


def _format_of(image_format: str) -> str:
    image_format = image_format.lower()
    if image_format not in FORMATS:
        msg = f"Cannot save a chart's image as {image_format!r}: choose one of {FORMATS}."
        raise ValueError(msg)
    return image_format
