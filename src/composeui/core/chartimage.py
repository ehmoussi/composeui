"""A chart as a report's figure, drawn by matplotlib alike on every backend, or with none.

A screen chart follows its window and theme; a report's figure has its page's size and
fonts, and a light background. So the figure is drawn from the `ChartView`'s data, e.g.
by a batch run writing a report's figures:

    save_chart_image(chart, Path("pressure.pdf"), ImageOptions(width_mm=80))

It needs the `report` extra (matplotlib), imported only by these functions; without it
they raise an `ImportError` naming the extra, and `is_available` is False.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import math
from typing import TYPE_CHECKING, Any

import attrs

from composeui.core.view import ChartKind, ChartView, LineStyle

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


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


@contextlib.contextmanager
def image_style(options: ImageOptions = DEFAULT_OPTIONS) -> Iterator[None]:
    """Draw and save figures with the options' fonts while the block runs.

    Text stays text in a vector image (TrueType fonts in a PDF or EPS, ``<text>`` in an
    SVG), so its labels can still be edited or searched. Matplotlib's global settings
    are left as they were: wrap a `chart_figure` saved with `Figure.savefig` in it too.
    """
    _require()
    import matplotlib as mpl  # noqa: PLC0415

    size = options.font_size
    with mpl.rc_context(
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
    ):
        yield


def chart_figure(chart: ChartView, options: ImageOptions = DEFAULT_OPTIONS) -> Figure:
    """Draw `chart` as a report's figure, which app code can add to before saving it.

    Save it in `image_style` for its text to stay text, or with `save_chart_image`.
    """
    _require()
    from matplotlib.figure import Figure  # noqa: PLC0415

    with image_style(options):
        figure = Figure(
            figsize=(options.width_mm / _MM_PER_INCH, options.height_mm / _MM_PER_INCH),
            dpi=options.dpi,
            layout="constrained",
        )
        axes = figure.add_subplot()
        if chart.kind is ChartKind.BAR:
            _draw_bars(axes, chart)
        else:
            _draw_curves(axes, chart)
        _draw_reference_lines(axes, chart)
        if options.show_title and chart.title:
            axes.set_title(chart.title)
        axes.set_xlabel(ChartView.axis_label(chart.x_title, chart.x_unit))
        axes.set_ylabel(ChartView.axis_label(chart.y_title, chart.y_unit))
        if options.x_range is not None:
            axes.set_xlim(*options.x_range)
        if options.y_range is not None:
            axes.set_ylim(*options.y_range)
        _add_legend(figure, axes, chart)
    return figure


def _draw_curves(axes: Axes, chart: ChartView) -> None:
    if chart.x_log:
        axes.set_xscale("log")
    if chart.y_log:
        axes.set_yscale("log")
    for index, series in enumerate(chart.series):
        x, y = ChartView.drawn_points(series, x_log=chart.x_log, y_log=chart.y_log)
        color = series.color or SERIES_COLORS[index % len(SERIES_COLORS)]
        if ChartView.kind_of(series, chart.kind) is ChartKind.SCATTER:
            axes.plot(
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
            axes.plot(
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
                    x, y, 0, color=color, linewidth=0, step="post" if series.step else None
                )


def _draw_bars(axes: Axes, chart: ChartView) -> None:
    count = len(chart.categories)
    if chart.y_log:
        axes.set_yscale("log")
    for index, series in enumerate(chart.series):
        heights = ChartView.bar_heights(series, count, y_log=chart.y_log)
        offset, width = ChartView.bar_slot(index, len(chart.series))
        drawn = [category for category, height in enumerate(heights) if math.isfinite(height)]
        axes.bar(
            [category + offset for category in drawn],
            [heights[category] for category in drawn],
            width=width,
            color=series.color or SERIES_COLORS[index % len(SERIES_COLORS)],
            hatch=HATCHES[index % len(HATCHES)],
            edgecolor="white",
            linewidth=0.5,
            label=series.name,
        )
    axes.set_xticks(range(count), chart.categories)
    axes.grid(visible=False, axis="x")


def _draw_reference_lines(axes: Axes, chart: ChartView) -> None:
    """Draw the chart's reference lines, labeled inside the axes, at their ends."""
    x_log = chart.x_log and chart.kind is not ChartKind.BAR
    for line in ChartView.drawn_lines(chart.reference_lines, x_log=x_log, y_log=chart.y_log):
        color = line.color or REFERENCE_LINE_COLOR
        style = REFERENCE_LINE_STYLES[line.style]
        # not in the legend, which names the series: its label is beside it
        if line.vertical:
            axes.axvline(line.value, color=color, linestyle=style, linewidth=1)
            # at its top, left of it (now, after the data): the x in data, the y in the
            # axes' share
            axes.annotate(
                line.label,
                (line.value, 1),
                xycoords=axes.get_xaxis_transform(),
                xytext=(-3, -3),
                textcoords="offset points",
                ha="right",
                va="top",
                color=color,
            )
        else:
            axes.axhline(line.value, color=color, linestyle=style, linewidth=1)
            # at its right end, over it
            axes.annotate(
                line.label,
                (1, line.value),
                xycoords=axes.get_yaxis_transform(),
                xytext=(-3, 2),
                textcoords="offset points",
                ha="right",
                va="bottom",
                color=color,
            )


def _add_legend(figure: Figure, axes: Axes, chart: ChartView) -> None:
    """Name the series, beside the axes when there are more than a few of them."""
    if len(chart.series) == 0:
        return
    if len(chart.series) <= _INSIDE_LEGEND_MAX:
        axes.legend(frameon=False)
    else:
        figure.legend(loc="outside right upper", frameon=False)


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
