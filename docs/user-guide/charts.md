# Charts

A `ChartView` plots results, for example a quantity against time or a swept dimension. Its
`series` is a list of `Series`. Each series is a layer of the chart: a line, dots, or bars,
with its own `x` and `y` (as many of each) and a `name` for the legend. The chart draws its
series over the same axes. A NaN is a point that the chart does not draw.

These sections cover the kinds of chart, axes and reference lines, colors, what each backend
draws, clicks, and report images.

```python
from composeui.core.view import Axis, ChartView, Series, child

chart: ChartView = child(
    ChartView, title="Pressure Drop", x=Axis("Flow Rate", unit="L/s"), y=Axis(unit="kPa")
)

chart.series = [*chart.series, Series.line("D = 50 mm", flows, drops)]
```

As for the rows of a table, set a new `series` list to draw the chart again. A job that
adds points does the same. The study saves the series.

## Kinds of chart

Three functions make a series, each of one kind (its `kind`, a `ChartKind`):

- `Series.line(name, x, y)` joins the points with a line. A NaN leaves a gap in the line.
- `Series.scatter(name, x, y)` draws the points as dots, for example measurements over the
  curve of a model.
- `Series.bars(name, values)` draws a bar for each value.

A chart can mix the kinds. The chart draws the bars first, then the lines and the dots over
them.

A chart with `categories` shows values per case. Its x axis shows the categories, and the x
of a series names a category by its index. `Series.bars` puts its values in the categories
in order. The bars of several series stand side by side in each category:

```python
from composeui.core.view import Axis, ChartView, Series, child

orders: ChartView = child(
    ChartView,
    title="Orders",
    y=Axis(unit="k"),
    categories=["Jan", "Feb", "Mar"],
    series=[
        Series.bars("Shop", [120, 140, 90]),
        Series.bars("Online", [80, 95, 130]),
        Series.line("Target", [0, 1, 2], [100, 110, 125]),
    ],
)
```

- **Bars at an x.** `Series.bars("People", [4, 6, 5], x=[10, 20, 40])` puts each bar at an x.
  With categories, the x is the index of a category: a category without an x has no bar.
  Without categories, the x is a value of the x axis. The bars then share the smallest step
  between two x.
- **Another kind for a series.** A `Series` does not change. To draw a series as another
  kind, make a new one: `attrs.evolve(series, kind=ChartKind.SCATTER)`.
- **Older studies.** Before, the chart held the kind. A study saved then opens with each
  series as the chart drew it.

`bar_chart`, from `composeui.core.dashboard`, gives a view field a chart of categories. It
takes the chart's `title` and `categories`, and optionally its axes (`x`, `y`) and its
`height`:

```python
from composeui.core.dashboard import bar_chart
from composeui.core.view import Axis, ChartView

energy: ChartView = bar_chart("Energy", ["Kitchen", "Bedroom", "Office"], y=Axis("Energy"))
```

`series_of(frame, x, y)` from `composeui.core.dataframesource` makes a line of two columns of a
pandas, Polars, or PyArrow frame. It leaves out the rows missing a value. Its `name` is the y
column's, or the `name` that you give.

## Axes

The `x` and `y` of the chart are its axes. Each one is an `Axis`: a title, a `unit`, and a
`scale`. `Axis("Time", unit="s")` shows the label "Time (s)", and the chart shows the unit
with the values that the user hovers over.

An `Axis` does not change. To change an axis, set a new one:

```python
import attrs

from composeui.core.view import Scale

chart.y = attrs.evolve(chart.y, scale=Scale.LOG)
```

The axes belong to the code of the app, as a title does. The study does not save them, and
`tr` translates their titles.

`Scale.LOG` makes an axis a log axis. A log axis leaves out what it cannot show: the chart
does not draw a point at an x of 0 or less, and a y of 0 or less leaves a gap. An x axis that
shows categories or bars stays linear.

## Reference lines

`reference_lines` draws lines across the chart at values. Each line is a `ReferenceLine`:

- A horizontal line at a y, for example a capacity.
- With `vertical=True`, a vertical line at an x, for example now. On a chart with
  categories, the x is the index of a category.

```python
from composeui.core.view import LineStyle, ReferenceLine

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
axis, the chart does not draw a line at 0 or less. Textual draws each line solid, because a
terminal has no dashes.

## Colors, fill, steps, and height

The view holds data and labels. Each backend draws the chart in the colors of its theme,
with these exceptions:

- **A color of its own.** A series can have a `color` (`"#rrggbb"`), the same in every theme, for
  example the color of a logo.
- **Fill.** On a line, `fill=True` fills the area between the line of the series and 0, in the color of the
  line. With `fill`, set `fill_color` (`"#rrggbb"`) to give the area its own color, for example a
  pale area under a strong line. This color is the same in every theme.
- **Steps.** A line with `step=True` holds each value until its next point, for example the number
  of jobs running over time. With `fill`, it draws a step area. When the user hovers over the
  series, the chart shows the value held at the cursor.
  [`src/examples/taskview.py`](../../src/examples/taskview.py) charts its running tasks this way.

`height` sets the height of the chart on screen, in pixels, for example to keep the
proportions of a shape. A terminal row is about 16 pixels. `None`, the default, leaves the
height to the backend.

## What each backend draws

- **Qt** draws the chart with [pyqtgraph](https://www.pyqtgraph.org/) (in the `pyside6` extra).
  The mouse zooms and pans. When the user hovers over the chart, it shows the value of each
  series at the cursor.
- **The web** draws the chart with [uPlot](https://github.com/leeoniya/uPlot). The page loads
  uPlot once it shows a chart. A drag across the chart zooms, and a double click zooms back
  out. The legend shows the values at the cursor. Before the server sends a long series, it
  thins the series to the extremes of each bucket of its points.
- **Textual** draws the chart with `textual-plotext` (in the `tui` extra), without zoom or hover.
  Its legend names the bars before the lines and the dots.

A new `series` list keeps the user's zoom.

[`src/examples/pipechart.py`](../../src/examples/pipechart.py) plots the pressure drop of a
pipe against its flow rate, with measurements over it, and the pressure of the pump as a
reference line (`uv run python -m examples.pipechart --backend qt`, or `textual`, or `web`).

## Clicks on a chart

A click on the chart emits its point from `clicked`, in the values of the axes (`x`, then
`y`). Clicks work in Qt and on the web. On the web, a drag zooms instead: when the pointer
moves more than 3 pixels during a click, the click is a drag. A terminal has no pointer to
click with.

[`src/examples/batman.py`](../../src/examples/batman.py) draws the Batman logo, in its own
yellow and black, and says whether a click was on the bat
(`uv run python -m examples.batman --backend web`, or `qt`).

## Report images

A chart on screen follows its window and its theme. The figure of a report has the size and
fonts of the page, and a light background. `composeui.core.chartimage` draws such a figure
from the data of the chart with Matplotlib (the `report` extra). The figure is the same
whatever the backend, and needs no UI, for example in a batch run that writes the figures of
a report:

```python
from pathlib import Path

from composeui.core.chartimage import ImageOptions, chart_figure, save_chart_image

save_chart_image(chart, Path("drop.pdf"), ImageOptions(width_mm=80, font_size=8))
figure = chart_figure(chart)  # a Matplotlib `Figure`, to annotate before saving it
```

- The suffix of the file picks the format. PDF, SVG, and EPS keep their text as text. PNG is
  drawn at `dpi`.
- `x_range` and `y_range` show a region of the data.

Each backend offers this as Save Image. Its text is translated like the other built-in text.

- **Qt** offers it in the context menu of the chart, at the region shown.
- **The web** offers it in the corner of the figure, with a format to pick, at the user's zoom.
- **Textual** offers it with the `s` key on a chart.

Without the `report` extra, Qt keeps the Export of pyqtgraph, and the web page draws a PNG
of the chart itself.
