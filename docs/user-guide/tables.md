# Tables

These views show records in a table: a table that the user edits, and a large table that reads
its rows from a source.

## A table of records

A `TableView` shows text that the app formats itself. A `RecordTableView` shows `attrs`
records, such as the records that `fetch` returns, with a column per field:

```python
from composeui.core.view import Column, RecordTableView, T, child

runs: RecordTableView[Run] = child(
    RecordTableView[Run],
    columns=[Column("id", T("Run")), Column("radius", T("Radius"), editable=True)],
)
```

- Assign `records` to update the table (`table.records = model.runs.above(0.1)`).
- Read `selected_record`, or `selected_records`.
- The table parses an edited cell into the type of its field, through the `cattrs`
  converter of the views. `record_edited` emits the old and the new record.
- When a cell doesn't parse, the table refuses the edit and says why in the status bar.

The study saves and loads the records by their type. So build the table as
`RecordTableView[Run]`, or subclass it.

### Sorting and filtering

Mark a column that the user sorts and filters:
`Column("radius", T("Radius"), sortable=True, filterable=True)`. On a `TableView`,
`sortable_columns` and `filterable_columns` list these columns.

A click on a sortable header sorts by its column: ascending, then descending, then back in
the app's order.

While a column is filterable, a bar above the table has:

- a search over the text of the filterable columns, once the user stops typing for
  `SEARCH_DELAY_MS` (300 ms), or presses Enter;
- "+ Filter", which adds a filter on a column. The filter shows as a chip. A click on the
  chip opens it for editing, and so does Enter, since the focus lands on the chip.

A filter accepts these values:

- In a text column, ignoring case:
  - the text: the cells that contain it;
  - `=kitchen`: the cells equal to it;
  - `!=kitchen`: the cells not equal to it;
  - `!kit`: the cells that do not contain it;
  - `kit*`: the cells that start with it;
  - `*en`: the cells that end with it;
  - with the `.*` toggle of the editor on, a regular expression, for example `Room [1-3]`.
    The chip reads "Room matches Room [1-3]". The app sets this filter as
    `as_pattern("Room [1-3]")`, between slashes.
- In a number or a date column: `>20`, `>=20`, `<20`, `<=20`, `!=20`, a range `18..24`
  (both ends included), or a bare value, which means `=`.
- In a boolean column: `true` or `false`.
- In any column: `=` alone, for the empty cells.

A `RecordTableView` sorts by the values of the fields, so numbers and dates sort as numbers
and dates. A `TableView` sorts its text.

The app sets the order and the filters too: `sort_column`, `sort_descending`, `search`,
`filters`, or `sort_by(column)`, as a click does. The study saves them.

`shown_rows` lists the rows shown, in order, as indexes into `rows`. `selected_rows`,
`selection_changed`, and the edited row always use indexes into `rows`, whatever the
order. When a search or a filter hides a selected row, the table deselects it.

### Widgets in cells

A column can show a widget in each of its cells, such as a check box to keep a variable or
a combobox to pick its role. Set the column's `widget` to a `CellWidget`:

```python
from composeui.core.view import CellWidget, Column, RecordTableView, T, child

variables: RecordTableView[Variable] = child(
    RecordTableView[Variable],
    columns=[
        Column("is_kept", T("Keep"), editable=True, widget=CellWidget.check_box(check_all=True)),
        Column("name", T("Variable")),
        Column("role", T("Role"), editable=True, widget=CellWidget.combobox()),
        Column("distribution", T("Distribution"), widget=CellWidget.button()),
        Column("doc", T("Help"), widget=CellWidget.link()),
    ],
)
```

On a `TableView`, `cell_widgets` maps each column's index to its `CellWidget`.

- **`CellWidget.check_box()`** shows a check box. The box is checked when the cell's text
  is "true", ignoring case. A change sets the text to "True" or "False".
- **`CellWidget.combobox(options)`** shows the cell's text in a combobox of `options`.
  Without options, on an enum field of a `RecordTableView`, it offers the enum's members.
- **`CellWidget.button(text)`** shows the cell's text, then a button ("…" by default).
  A text such as `T("Retry")` follows the app's language.
- **`CellWidget.link()`** shows the cell's text as a link.

A check box or a combobox changes its cell only when the column is editable. Otherwise it
only shows the cell. The change is an edit, as when the user types in a cell:
`cell_edited` emits it, and on a `RecordTableView`, `record_edited` too. The user does not
type in these cells.

A click on a button or a link emits `cell_clicked` with the row and the column. The row
is an index into `rows`, whatever the order.

With `check_all=True`, the column's header starts with a check box. The box is checked when
all the shown rows are, and partly checked when only some are. A click checks every shown
row, or unchecks them all when all are checked. Each changed cell is an edit. The app does
the same with `check_all(column, is_checked=True)`. `column_checked(column)` tells whether
the shown rows are all checked (`True`), none (`False`), or some (`None`).

The study does not save `cell_widgets`: they are the app's setup.

[`pipechart.py`](../../src/examples/pipechart.py) shows or hides each curve with a check box,
and picks how to draw it with a combobox. [`taskview.py`](../../src/examples/taskview.py) runs
a task again from its Retry button, and opens the error of a failed task from a link.

What each backend shows:

- **Qt** draws a checkable cell, a combobox frame, a push button, or underlined link text.
  A click or F2 on an editable combobox cell opens a `QComboBox`. Space toggles the current
  check box, or clicks the current button or link.
- **Textual** shows the cell as text: a box (☑ or ☐), the text and ▾, the text and the
  button's text in brackets, or underlined text. A click toggles a box, and so does Space
  on the cursor's row. A click on an editable combobox cell opens a list of its options. A click on
  a button or a link cell clicks it. A check-all header shows its box (▣ when partly
  checked), and a click on the header toggles it instead of sorting.
- **The web** shows a check box, a `<select>`, a button, or a link-like button. A click on
  a widget does not select its row.

### How cells and headers look

A cell can have a background color, such as red for NaN or orange for a warning. It can be
disabled, show a mark, or span the rows under it. Set `cell_styles`, a `CellStyle` per cell
by its index in `rows` and its column:

```python
from composeui.core.view import CellStyle, HeaderGroup, NodeMark, T

table.headers = ["Group", "Point", "Standard space", "Physical space"]
table.header_groups = [HeaderGroup(T("Coordinates"), column=2, column_count=2)]
table.rows = [["A", "P1", "0.5", "12.0"], ["", "P2", "nan", "nan"]]
table.cell_styles = {
    (0, 0): CellStyle(row_span=2),
    (1, 2): CellStyle(background="#dc2626"),
    (1, 3): CellStyle(background="#fde68a", mark=NodeMark.WARNING),
    (1, 1): CellStyle(is_disabled=True),
}
```

- **`background`** is a color as `#rrggbb`, the same in every theme. The text on it is black
  or white, whichever reads better (`text_color`).
- **`is_disabled`** grays the cell. The user never edits it, even in an editable column, and
  its widget is disabled. `check_all` leaves it as it is, and `column_checked` ignores it.
- **`mark`** shows a `NodeMark` before the text: done, warning, or error. `done_text`,
  `warning_text`, and `error_text` name it, as a tooltip (Qt, the web) and for screen
  readers (the web).
- **`row_span`** makes the cell cover the cells under it in its column, for example a group
  over its rows. The span holds only while the table shows those rows right under the cell,
  in their order. A sort or a filter that moves or hides them shortens it.

Assign `cell_styles` together with the rows that they describe. The styles go by index, so
new rows take the styles of the rows that were at their indexes.

On a `RecordTableView`, `column_index(field)` gives the index of the column that shows a
field, for example `table.column_index("deviation")`.

`header_groups` puts a header over several columns, on a row above their headers. A
`HeaderGroup` has its text, its first column, and its number of columns. A column is in one
group at most.

`row_headers` puts a header before each row, by its index in `rows`. Use it for a small
key/value table of results:

```python
table.headers = [T("Value")]
table.row_headers = [T("Number of calls"), T("Time (s)")]
table.rows = [["2500"], ["3.2"]]
```

The study does not save `cell_styles`, `header_groups`, or `row_headers`: the app sets them.

What each backend shows:

- **Qt** colors the cell, grays a disabled cell, and draws the mark as an icon. A cell
  spans its rows (`QTableView.setSpan`). The header is twice as tall with groups. A click on
  a group sorts nothing. The rows' headers show in the vertical header.
- **Textual** colors the cell's text, dims a disabled cell, and shows the mark as a glyph
  (✓, !, ✗). A terminal has no cell across rows: the covered cells are empty. With groups,
  the header has two lines, each group's text over its first column. The rows' headers are
  the `DataTable`'s row labels.
- **The web** colors the cell, grays a disabled cell, and shows the mark as an icon named
  for screen readers. A cell spans its rows (`rowspan`), and a group its columns
  (`colspan`). Each row starts with its header (`<th scope="row">`).

The Measurements tab of [`pipechart.py`](../../src/examples/pipechart.py) uses each of these
looks.

## A large table

A `DataTableView` shows the rows of a source, such as a million results of a study. It
never reads all the rows. It reads only the rows that it shows, a window at a time. A
`TableView` keeps every row as text, which suits a small table that the user edits.

```python
from composeui.core.view import DataTableView, ListSource, T, child

readings: DataTableView = child(
    DataTableView,
    column_formats={"temperature": ".2f"},
    filterable_columns=["sensor", "temperature"],
)

# once the app has the records
main_view.readings.source = ListSource(
    Reading, {"sensor": T("Sensor"), "temperature": T("Temperature")}, records
)
```

The source is a `TableSource`. Three sources come with ComposeUI:

- **A `ListSource`** keeps `attrs` records in memory, for rows that the app has already.
- **A `SqliteSource`** reads the rows from SQLite (see [Rows in SQLite](#rows-in-sqlite)).
- **A `DataFrameSource`** reads the rows of a pandas, Polars, or PyArrow frame (see
  [Rows in a dataframe](#rows-in-a-dataframe)).

A source of your own gives:

| Member | What it gives |
| --- | --- |
| `columns` | The columns of the rows |
| `count` | The number of rows |
| `ordered_ids` | The ids of the rows shown, in order |
| `cells` | The values of some rows |
| `changed` | A signal that the rows changed |

When the app sets a new source, the view drops the sort and the filters on the columns that
the new source doesn't have.

### Order a large table

These settings of the view name the columns of the source:

- `sort_column` and `sort_descending` sort the rows.
- `search` finds a text in the text columns.
- `filters` hold the filters, written as the user types them (see
  [Sorting and filtering](#sorting-and-filtering)).

A click on a column's header sorts by it: ascending, descending, then in the source's
order. The app does the same with `sort_by(column)`.

Each new setting asks the source for the order once. The view keeps only the ids of the
rows shown. Integer ids go in an `array`, at 8 bytes each. `ordered` emits once the rows
have their new order. For example, its callback shows `row_count` of `total`. `total` is
the number of the source's rows, before the search and the filters.

A source of 100,000 rows or more (`DATA_TABLE_JOB_ROWS`) orders its rows in a
[job](threads.md) on Qt and Textual, so that the window stays
responsive:

- While the job runs, the table shows the previous order, and `is_ordering` is true.
- A setting changed while the job runs orders the rows once more, when the job is over.
- When the source changed, the job also counts its rows.

The web orders the rows in the thread of the request. The page never freezes.

`filterable_columns` names the columns that the user filters. The table then shows the
filter bar of [Sorting and filtering](#sorting-and-filtering) above its rows. The bar has a
search, "+ Filter", the filters as chips, and the count of the rows shown
("1,234 of 1,000,000"). Without `filterable_columns`, only the app sets the search and the
filters.

### Cells, selection, copy, and export

- **The cells** show the values in the format that `column_formats` gives, such as `".2f"`
  or `".0%"`. A cell of `None` is empty. An enum shows its text.
- **The selection** is a list of ids: `selected_ids`. A new order keeps the selected rows
  that it still shows. A click on a row selects it. With `SelectionMode.MULTIPLE`, the
  click adds the row, or removes it if it is selected. `selection_changed` emits the ids.
  A double click emits the id of the row with `row_activated`.
- **Ctrl+C** copies the selected rows, in their order, as tab-separated text that a
  spreadsheet takes. Each row is a line, with its cells as shown, and without the headers
  (`selection_text`). The view reads the rows from the source a window at a time.
- **Export CSV** writes the rows shown, in their order, to a CSV file in UTF-8
  (`export_csv`). The file has the headers, then each value in full, not in its
  `column_formats` format. In an app, a job writes the file, a window of rows at a time,
  and the status bar says when the file is done. A new order during the export doesn't
  change the file. `csv_chunks` gives the same text in pieces. `export_filename` is the
  name offered for the file (`table.csv`).

The study saves the settings and `selected_ids`. It never saves the rows or the source:
the app gives the view its source again, for example from its command line or its model.

What each backend shows:

- **Qt** shows a `QTableView`. Its model asks the view only for the rows that Qt draws.
  - Each row starts with its position, and the header shows Qt's sort indicator.
  - A selected row has the highlight colors. Shift+click selects the rows from the row
    clicked last. Space selects the current row, and Enter activates it.
  - "Export CSV…", above the rows and in their context menu, asks where to save the file.
  - While a job orders the rows, the cursor over them is busy.
- **Textual** draws the headers on the first line, then only the lines on screen.
  - A cursor marks a row. The arrow keys, Page Up, Page Down, Home, and End move it.
  - Space selects the row of the cursor, and Shift+Space or Shift+click a range. Enter or
    a double click activates the row.
  - The header of the sorted column ends with ▲ or ▼.
  - The key `e` asks where to export the rows as CSV.
  - While a job orders the rows, Textual's loading indicator covers them.
- **The web** scrolls the rows in a frame, and draws only the rows near the view.
  - Once the user stops scrolling, the page asks for the rows shown. Past 400,000 rows,
    the scroll bar keeps the height of 400,000 rows, and its position maps to a row by its
    ratio.
  - Each header is a button, with `aria-sort`. A sort scrolls back to the top.
  - A click or Enter on a row selects it (`aria-selected`, or `aria-current` for one row
    at most). The web selects no range and activates no row.
  - The "Export CSV" link above the frame downloads the rows. The server streams them, a
    window at a time.

[`largetable.py`](../../src/examples/largetable.py) shows a million rows this way.

### Rows in SQLite

A `SqliteSource` gives a large table the rows of a query on a `SqliteModel`. SQLite sorts
and filters the rows. The table reads only the ids of the rows shown, and the rows that it
draws. So the rows never all come to Python.

For a [`CSVSqliteTable`](sqlite-model.md#importing-csv-data), use `model.readings.source()`
to infer columns and types from its row class. Pass `headers={"field": "Label", ...}` to
select, order, and label the columns. For other tables or custom queries, declare the
query and columns explicitly:

```python
from composeui.core.sqlitemodel import SqliteSource
from composeui.core.view import SourceColumn, T

main_view.readings.source = SqliteSource(
    model.readings,  # a SqliteTable: its connection, and its changed signal
    "SELECT * FROM reading",
    id_column="id",
    columns=[
        SourceColumn("sensor", T("Sensor")),
        SourceColumn("temperature", T("Temperature"), float),
    ],
)
```

- **`columns` lists the columns of the query that the table shows,** with their types.
  They sort and filter as the columns of a `ListSource` do. Only these columns sort and
  filter, because SQLite takes no column name as a parameter. The values of the filters
  are parameters. Without a sort, the rows come in the order of their ids.
- **The `changed` signal of the table reads the rows again,** for example after a job
  wrote rows.
- **Index the columns that sort.** With no search and no filter, SQLite reads the rows in
  the order of the index. This takes about 0.4 seconds for a million rows, where a sort
  takes about a second. A search or a filter sorts only the rows that pass it.
- **The source reads on connections of its own** (`SqliteModel.reading`). The order and
  the cells never wait for each other, or for a write, such as a job that writes rows.
  They read the committed rows. Once a write commits, the `changed` signal of the table
  reads the rows again.
- **The search and the filters ignore the case of a text,** as for a `ListSource`, with
  one difference:
  - SQLite compares a text typed in ASCII only (`COLLATE NOCASE`), so an index serves it.
    It doesn't find a cell whose letters fold into the text: "strasse" doesn't find
    "Straße".
  - For other text, SQLite calls Python on each row, as for a `/regex/` filter: "École"
    finds "ÉCOLE".

  A sort ignores the case of ASCII letters only.

[`largetable.py`](../../src/examples/largetable.py) writes its readings into SQLite in a job,
then shows them this way.

### Rows in a dataframe

A `DataFrameSource` gives a large table the rows of a dataframe. The frame's library sorts
and filters the rows with its own expressions, never row by row in Python. It needs the
`dataframe` extra, which installs [narwhals](https://narwhals-dev.github.io/narwhals/).
Narwhals reads the frames of pandas, Polars, PyArrow, and other libraries through one API.

```python
import polars as pl

from composeui.core.dataframesource import DataFrameSource

frame = pl.read_csv("readings.csv")
main_view.readings.source = DataFrameSource(
    frame, {"sensor": "Sensor", "temperature": "Temperature"}
)
```

- **The headers select, order, and label the columns.** Without them, the table shows every
  column under its name. The types of the columns come from the frame's schema: a number, a
  date, or a boolean sorts and filters as one, any other column as text.
- **A row's id is its position in the frame,** or the value of its `id_column` when the
  source has one. A lazy frame, such as a Polars `LazyFrame`, needs an `id_column`: its
  rows have no position of their own. The source then reads only the columns it needs.
- **Assign a new `frame` to change the rows.** The source emits `changed`, and the table
  reads the rows again. Assign it on the main thread, for example from a job's result.
- **The cells are Python values.** A missing value of pandas (`NaN`, `NaT`, or `NA`) is
  `None`, and a numpy value is the Python value it holds.
- **The search and the filters ignore the case of a text,** as for a `ListSource`, with
  two differences:
  - They compare the text in lower case, which isn't Python's `casefold`: "strasse"
    doesn't find "Straße".
  - A `/regex/` filter is in the syntax of the frame's library: Rust's `regex` for Polars,
    Python's `re` for pandas.

[`uberpickupsframe.py`](../../src/examples/uberpickupsframe.py) shows a million pickups of a
Polars frame this way.
