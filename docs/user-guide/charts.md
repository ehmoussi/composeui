# Charts

A `ChartView` plots results, for example a quantity against time or a swept dimension. Its
`series` is a list of `Series`. Each series is a curve with its own `x` and `y` (as many of
each) and a `name` for the legend. A NaN leaves a gap in its curve.

```python
from composeui.core.view import ChartView, LineStyle, ReferenceLine, Series, child

chart: ChartView = child(
    ChartView, title="Pressure Drop", x_title="Flow Rate", x_unit="L/s", y_unit="kPa"
)

chart.series = [*chart.series, Series(name="D = 50 mm", x=flows, y=drops)]
```

As for the rows of a table, assign a new `series` list to draw the chart again. A job that
adds points does the same. The study saves the series.

## Kinds of chart

The `kind` of the chart (`ChartKind`) draws the series as lines (`LINE`, the default) or
dots (`SCATTER`). The `kind` of a series overrides it, for example measurements as dots over
the curve of a model.

A `BAR` chart draws values per case: a group of bars for each of its `categories`, one bar
per series. The x of a series names a category by its index, and its y is the height of the
bar:

```python
from composeui.core.view import ChartKind, ChartView, Series, child

energy: ChartView = child(
    ChartView,
    kind=ChartKind.BAR,
    y_unit="kWh",
    categories=["Kitchen", "Bedroom", "Office"],
    series=[Series(name="Heating", x=[0, 1, 2], y=[120, 80, 95])],
)
```

`Series.bars("Heating", [120, 80, 95])` makes the same series: a bar per value, in the
categories in order.

With the `dataframe` extra, `series_of(frame, x, y)` from `composeui.core.dataframesource`
makes a series of two columns of a pandas, Polars, or PyArrow frame. It leaves out the rows
missing a value. Its `name` is the y column's, or the `name` that you give.

## Log axes

`x_log` and `y_log` make an axis a log axis. A log axis leaves out what it can't show: the
chart doesn't draw a point at an x of 0 or less, and a y of 0 or less leaves a gap.

## Reference lines

`reference_lines` draws lines across the chart at values. Each line is a `ReferenceLine`:

- A horizontal line at a y, for example a capacity.
- With `vertical=True`, a vertical line at an x, for example now. On a bar chart, the x is
  the index of a category.

```python
chart.reference_lines = [
    ReferenceLine(40, "Max: 40", style=LineStyle.SOLID),
    ReferenceLine(now, "Now", vertical=True),
]
```

- Its `label` ("Max: 40") shows beside the line, not in the legend.
- Its `color` (`"#rrggbb"`) defaults to the color of the theme's text.
- Its `style` (`LineStyle`) defaults to `DASHED`. The other styles are `SOLID`, `DOTTED`,
  and `DASH_DOT`.

The range of the chart includes the lines, so a line past the data still shows. On a log
axis, the chart doesn't draw a line at 0 or less. Textual draws each line solid, because a
terminal has no dashes.

## Colors, fill, steps, and height

The view holds data and labels. Each backend draws the chart in the colors of its theme,
with these exceptions:

- A series can have a `color` of its own (`"#rrggbb"`), the same in every theme, for
  example the color of a logo.
- `fill=True` fills the area between the line of the series and 0, in its color.
- A series with `step=True` holds each value until its next point, for example the number of
  jobs running over time. With `fill`, it draws a step area. When the user hovers over the
  series, the chart shows the value held at the cursor.
  [`src/examples/taskview.py`](../../src/examples/taskview.py) charts its running tasks this
  way.

`height` sets the height of the chart on screen, in pixels, for example to keep the
proportions of a shape. A terminal row is about 16 pixels. `None`, the default, leaves the
height to the backend.

## What each backend draws

- Qt draws the chart with [pyqtgraph](https://www.pyqtgraph.org/) (in the `pyside6` extra).
  The mouse zooms and pans. When the user hovers over the chart, it shows the value of each
  series at the cursor.
- The web draws the chart with [uPlot](https://github.com/leeoniya/uPlot). The page loads
  uPlot once it shows a chart. A drag across the chart zooms, and a double click zooms back
  out. The legend shows the values at the cursor. Before the server sends a long series, it
  thins the series to the extremes of each bucket of its points.
- Textual draws the chart with `textual-plotext` (in the `tui` extra), without zoom or hover.

A new `series` list keeps the user's zoom.

[`src/examples/pipechart.py`](../../src/examples/pipechart.py) plots the pressure drop of a
pipe against its flow rate, with measurements over it, and the pressure of the pump as a
reference line (`uv run python -m examples.pipechart --backend qt`, or `textual`, or `web`).

## Clicks on a chart

A click on the chart emits its point from `clicked`, in the values of the axes (`x`, then
`y`). Clicks work in Qt, and on the web, where a drag still zooms. A terminal has no pointer
to click with.

[`src/examples/batman.py`](../../src/examples/batman.py) draws the Batman logo, in its own
yellow and black, and says whether a click was on the bat
(`uv run python -m examples.batman --backend web`, or `qt`).

## Report images

A chart on screen follows its window and its theme. The figure of a report has the size and
fonts of the page, and a light background. `composeui.core.chartimage` draws such a figure
from the data of the chart with matplotlib (the `report` extra). The figure is the same
whatever the backend, and needs no UI, for example in a batch run that writes the figures of
a report:

```python
from pathlib import Path

from composeui.core.chartimage import ImageOptions, chart_figure, save_chart_image

save_chart_image(chart, Path("drop.pdf"), ImageOptions(width_mm=80, font_size=8))
figure = chart_figure(chart)  # a matplotlib `Figure`, to annotate before saving it
```

- The suffix of the file picks the format. PDF, SVG, and EPS keep their text as text. PNG is
  drawn at `dpi`.
- `x_range` and `y_range` show a region of the data.

Each backend offers this as Save Image. Its text is translated like the other built-in text.

- Qt offers it in the context menu of the chart, at the region shown.
- The web offers it in the corner of the figure, with a format to pick, at the user's zoom.
- Textual offers it with the `s` key on a chart.

Without the `report` extra, Qt keeps the Export of pyqtgraph, and the web page draws a PNG
of the chart itself.
