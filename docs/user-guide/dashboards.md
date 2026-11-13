# Dashboards from a dataframe

This page turns a dataframe into a dashboard. It starts with a dashboard's main view and a
tutorial, then describes each helper of `composeui.core.dashboard`. The helpers take any frame that
[Narwhals](https://narwhals-dev.github.io/narwhals/) reads: pandas, Polars, PyArrow, or a lazy
Polars frame. They fill ordinary views, or give plain values. The views keep the state, as in any
other app.

## A dashboard's main view

`DashboardView`, from `composeui.core.dashboard`, is a `MainView` for a dashboard. Its
[`width`](organizing-the-window.md#page-width) is `WIDE`, and it has no File menu:

```python
from composeui.core.dashboard import DashboardView
from composeui.core.view import ChartView, LabelView, child, define_view


@define_view
class SalesDashboard(DashboardView):
    app_title = "Sales"

    status: LabelView = child(LabelView)
    sales: ChartView = child(ChartView, title="Sales by month")
```

A dashboard that saves studies sets `has_file_menu = True` and its `extension`. The
[Uber pickups example](../../src/examples/uberpickups.py) does, so that a study keeps the
rows that it read.

## A first dashboard

This dashboard shows the NYC Uber pickups of September 2014, from a CSV file. The user
filters the pickups by base, by day, and by hour. A row of metrics, a bar chart, a map, and a
table show the pickups that the filters keep, and a button downloads them. The complete app is
the [first dashboard example](../../src/examples/uberdashboard.py).

### Read the data in a task

A task reads the file in a thread, so that the window shows while it reads. It returns a frame,
in your frame library. Here, Polars reads the file and adds the hour of each pickup:

```python
import polars as pl

from composeui.core.jobs import Job

DATA_URL = "https://s3-us-west-2.amazonaws.com/streamlit-demo-data/uber-raw-data-sep14.csv.gz"


def read_pickups(_job: Job[pl.DataFrame, int], url: str) -> pl.DataFrame:
    pickups = pl.read_csv(url).with_columns(
        pl.col("Date/Time").str.to_datetime("%m/%d/%Y %H:%M:%S")
    )
    return pickups.with_columns(Hour=pl.col("Date/Time").dt.hour())
```

### Declare the filters

`column_filter` gives a view field a filter of one column of the frame. Its first argument is the
view class, its second the column's name. The other arguments go to the view class. Here, a
sidebar holds three filters:

```python
from composeui.core.dashboard import column_filter
from composeui.core.view import (
    LabelRowDateRangeInputView,
    LabelRowMultiComboBoxView,
    LabelRowRangeSliderView,
    SidebarView,
    define_view,
)


@define_view
class Filters(SidebarView):
    bases: LabelRowMultiComboBoxView[str] = column_filter(
        LabelRowMultiComboBoxView[str], "Base", label="Bases"
    )
    days: LabelRowDateRangeInputView = column_filter(
        LabelRowDateRangeInputView, "Date/Time", label="Days"
    )
    hours: LabelRowRangeSliderView = column_filter(LabelRowRangeSliderView, "Hour", label="Hours")
```

[Filters of a frame's columns](#filters-of-a-frames-columns) lists the views that a filter can
be.

### Show the rows that the filters keep

The main view starts the task, and two [reactive methods](reactive-methods.md) read its result.
`fill_filters` gives each filter the values of its column. `filtered` gives the rows that every
filter keeps. Both find the filters in the view that they get and in its child views, at any
depth: here, the main view and its sidebar. Each method runs again when a field that it reads changes, so the dashboard
follows each change of a filter:

```python
from composeui.core.application import run
from composeui.core.dashboard import (
    DashboardView,
    bar_chart,
    counts_of,
    fill_filters,
    filtered,
    frame_content,
    show_frame,
)
from composeui.core.reactivity import reactive
from composeui.core.view import (
    ChartView,
    DownloadView,
    HorizontalView,
    LabelView,
    MetricView,
    Series,
    SourceTableView,
    child,
    define_view,
)

HOURS = [f"{hour:02d}:00" for hour in range(24)]


@define_view
class Summary(HorizontalView):
    pickups: MetricView = child(MetricView, label="Pickups")
    busiest_hour: MetricView = child(MetricView, label="Busiest hour")


@define_view
class PickupsDashboard(DashboardView):
    app_title = "Uber pickups in NYC"

    filters: Filters = child(Filters, title="Filters")
    status: LabelView = child(LabelView)
    summary: Summary = child(Summary)
    by_hour: ChartView = bar_chart("Pickups by hour", HOURS, y_title="Pickups")
    table: SourceTableView = child(SourceTableView)
    download_rows: DownloadView = child(
        DownloadView, text="Download these pickups", filename="pickups.csv"
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loader = self.jobs.task(read_pickups)
        self.loader.show_state(
            self.status, views=[self.summary, self.by_hour, self.table, self.download_rows]
        )
        self.loader.start(DATA_URL)

    @reactive
    def fill(self) -> None:
        pickups = self.loader.result
        if pickups is not None:
            fill_filters(self, pickups)

    @reactive
    def show_pickups(self) -> None:
        pickups = self.loader.result
        if pickups is None:
            return
        rows: pl.DataFrame = filtered(pickups, self)
        by_hour = counts_of(rows, "Hour", range(24))
        self.summary.pickups.value = f"{rows.height:,}"
        self.summary.busiest_hour.value = HOURS[by_hour.index(max(by_hour))] if rows.height else "-"
        self.by_hour.series = [Series.bars("Pickups", by_hour)]
        show_frame(self.table, rows)
        self.download_rows.content = lambda: frame_content(rows)


if __name__ == "__main__":
    run(PickupsDashboard)
```

Put the three blocks in a file, such as `app.py`, and run it with `python app.py`, or with
`--backend qt` or `--backend textual`. Fill the filters
from the whole frame, in a method of their own: filled from the rows filtered, a filter would
offer only the values that the other filters keep.

### Move a panel into its own view class

A filter is a field of a view, with its column, so it moves with its view class. A first
version of the dashboard can declare the three filters as fields of `PickupsDashboard` itself.
Moved into the `Filters` sidebar, they need no change to the methods: `fill_filters(self, ...)`
and `filtered(..., self)` find them in the sidebar, as they found them in the main view.

`fill_filters` and `filtered` read where the filters are without making it an input of the
reactive method. Only the filters' choices are its inputs: the method runs again when the user
changes a filter, and not when another view changes.

## Filters of a frame's columns

`column_filter(cls, column, ...)` gives a view field a `cls` view that filters the rows by the
frame's `column`. `cls` is one of these views, or one of its form rows, such as
`LabelRowMultiComboBoxView`:

| View | Column | What `fill_filters` sets |
| --- | --- | --- |
| `MultiComboBoxView[str]`, `CheckListView[str]` | texts, categories, whole numbers, booleans | `values`: the column's values, as texts, in order |
| `RangeSliderView` | whole numbers | `minimum`, `maximum`, and a `step` of at least 1 |
| `FloatRangeSliderView` | numbers | `minimum`, `maximum`, and a `step` of 1, 2, or 5 times a power of 10, for about a hundred steps |
| `DateRangeInputView` | dates, or dates and times | `minimum` and `maximum`: the first and the last day |

A choice takes the values as texts, so that a page posts a value by its text, never by its
position. It offers at most `MAX_CHOICES` (1000) values: a column with more raises a
`ValueError`. A range leaves out NaN and the infinities. `fill_filters` raises a `TypeError` for a
column of another kind, and a `ValueError` for a column that the frame doesn't have.

`filtered(frame, view)` keeps the rows that every filter accepts, and gives them in the frame's
own library, lazy if the frame was:

- **A choice** keeps the rows of its values. While nothing is chosen, it keeps no row.
- **A range** keeps the rows between its two ends, both included.
- **A date range** keeps the rows from its first day to its last day, the times of the last day
  included. A column with a time zone compares the days in its own time zone.
- **An untouched filter keeps every row.** A choice of all its values, and an end at its limit (a
  range's first or last step, an empty date), filter nothing: a row without a value stays too.

Filled again, for example with a newer file, a filter keeps what the user chose. A choice keeps
the values that are still there. A range keeps its ends, and an end at its limit moves to the new
limit.

## Counts for a bar chart

`counts_of(frame, column, categories)` counts the rows with each of `categories` in `column`. It
gives 0 for a category of no row, in the order of `categories`, so that each bar stays in place
while the rows change. The rows without a value are in no category. Give the counts to
`Series.bars`, and the categories' labels to the chart, for example with
[`bar_chart`](charts.md#kinds-of-chart).

## A frame in a table

`show_frame(table, frame)` shows the rows of `frame` in a
[large table](tables.md#a-large-table), on a [`DataFrameSource`](tables.md#rows-in-a-dataframe).
The table keeps its sort and its filters on the columns that the new frame still has. The table's
filter bar offers every column. With `filterable=False`, the
table keeps its own `filterable_columns`. A lazy frame needs a `DataFrameSource` with its
`id_column`: set the table's `source` yourself, or collect the frame first.

## A file from a user

`read_frame(path, backend=...)` reads a CSV or Parquet file that a user gave, for example the
`path` of an [uploaded file](widgets.md#file-upload). `backend` is the library that reads it, such
as `"polars"` or `"pandas"`. It gives a Narwhals frame: `to_native()` gives the library's own.

- **A file ending in `.parquet`** reads as Parquet. `read_frame` refuses a file that isn't Parquet,
  or whose description of its columns is damaged or larger than `MAX_PARQUET_METADATA_SIZE`
  (16 MiB).
- **Any other file** reads as CSV. Its separator is the most frequent of a comma, a semicolon, a
  tab, and a bar on its first line, outside quotes. `read_frame` refuses a compressed CSV file.
  It also refuses a file of more than `max_columns` columns (`MAX_COLUMNS`, 1000 by default), or
  whose first line is longer than 64 KiB: a library can take seconds to read a small file of
  many columns.

A refused file raises a `ValueError`, which a task shows as its error. Each session reads its
whole file into memory. A Parquet file's columns are compressed: it can take much more memory than
its size. Before you give such an app to the public, set `max_upload_size` for your server's
memory, or read the file in a process with a memory limit. The
[data explorer example](../../src/examples/dataexplorer.py) reads a user's file with it.

## Download a frame

`frame_content(frame)` gives the rows of `frame` as a file that a
[`DownloadView`](widgets.md#download) gives: a CSV file, or a Parquet file with
`is_parquet=True`. The frame's library writes the file as the user receives it (see
[Large files](widgets.md#large-files)). Set the button's `content` to a function that gives it,
where the rows are known:

```python
self.download_rows.content = lambda: frame_content(rows)  # in a reactive method
```

The file holds the rows as they are when the method runs. Name the file with the button's
`filename`, such as `pickups.csv`.
