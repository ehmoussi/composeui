# Roadmap

What's left to do on ComposeUI. It merges the earlier plans and the library review
(`NEXT_PLAN.md`, `PAGES_PLAN.md`, `WEB_BACKEND_PLAN.md`, `REVIEW.md`); everything they
listed as done is gone from here, and lives in the code, the docs and `git log`. Build
and test each step before moving on, and delete a step's entry once it lands.

## 1 — Widgets

One widget at a time, each on Qt, Textual and the web with tests (the registry consistency
test requires all three backends to register the same keys). Already there: input, float
input, integer input, date input, file path input (a "…" button and a reload button),
slider, label, log, button, progress bar, metric, expander, checkbox, radio group,
combobox, table (editable cells, sorting and filtering, widgets in cells, cell colors,
marks, disabled cells, row spans, header groups and row headers included),
tree (its nodes with an icon, a mark and a style), Markdown, forms, pages, tabs, resizable
panes (a splitter), sidebar, a list of views from data, message, confirm and form dialogs.

Charts (2) have a section of their own.

### Missing for a scientific app

A scientific app's GUI (a study tree beside a result's tabs of tables and charts, wizards
to set up each analysis) is a good test of ComposeUI. What it uses that ComposeUI lacks,
most needed first:

1. **A context menu** on a tree node or a table's rows: its actions with an icon, some
   disabled, separators (Rename, Modify, Convert, Export, Remove; Export, Add row,
   Remove rows).
2. **A plain list to pick from**: strings, one or several selected, e.g. the "Outputs"
   or "Variables" list on the left of every result; a **checkable** variant with a
   check-all box in its header (the variables to keep).
3. **A color legend** beside a table whose cells are colored by range (`CellStyle`), such
   as a correlation matrix's coefficients: each range's color and its bounds.
4. **A wizard**: a dialog of steps with Back, Continue/Finish, Cancel and Help, each
   step a form checked before the next, an image on its side.
5. **Tabs the user adds and closes**: a × on each tab and a + tab after them ("Command 1",
   "Command 2").
6. **A combobox of several values**: check boxes in its list, the picked values shown
   below it ("-- Select outputs --", then "L, b, h").
7. **A button with a menu**: "Add ▾" adding one of several kinds.
8. **An optional field**: a check box enabling the field beside it (each stopping
   criterion of a Monte Carlo); and a **duration field** ("d h m s").
9. **A code editor**: line numbers and Python syntax highlighting (a Python model's
   function, a coupling's post-processing).
10. **A workflow diagram**: boxes joined by arrows, a box enabled or not, clicking one
    starting its step (the "Study workflow" page).
11. **A Python console** (Tools > Python Console), once an app wants to be scripted.

The web versions follow the same rules as the existing ones: the element that sent the
request is never swapped back (the focus rule), changes elsewhere arrive as OOB updates,
`aria-*` links between a field, its label and its log, and a `make css` rebuild when new
classes appear (a test fails otherwise).

### Large tables

A scientific app's results can have millions of rows. `TableView` holds them all as
formatted text, and doesn't scale to that (measured on 1M rows of 10 cells, and on the web
on 100k rows):

- **Memory.** About 800 MB, each cell a Python `str`.
- **Time.** Building the rows takes 12 s. Each sort takes 1.3 s and each search 0.5 s.
- **The web.** It writes a `<tr>` per shown row, and swaps the whole `<tbody>` on a sort
  or a filter: 6 s and 27 MB of HTML for 100k rows.
- **Saved state.** `rows` is saved with the study, so a study would hold the whole
  result as JSON.

Qt already draws only the rows on screen (`QTextTableView` is on a `QAbstractTableModel`).
Textual's `DataTable` draws only the visible lines, but keeps every row.

Add a read-only table backed by a data source, on the three backends. Keep `TableView`
for the small tables that the user edits (an analysis' parameters, a list of load cases).

The design:

- **Everything but the drawing is in `core`.** Sorting, searching, filtering, selection,
  the cache and the cells' formats are computed once, so they behave the same on each
  backend. A renderer only turns its scroll position into a range of rows.
- **The source does the work on the data.** It sorts and filters with SQL or numpy, never
  row by row in Python, and no backend reads every row.
- **The view holds the order, not the data.** For each sort, search and set of filters,
  the view asks the source once for the shown rows' ids, in order, and keeps them in an
  `array` (8 MB for 1M integer ids). A position then gives its row's id at once:
  scrolling to any position, a range selection (Shift+click) and the count need no query.
  The cells are read by id, a window of rows at a time.
- **Rows are selected by id, not by index**, so the selection stays on its rows when the
  data or the order changes. An id that is gone drops from the selection.
- **The filters are those of `TableView`.** The user types the same text, `parse_filter`
  parses it into a `Filter`, and the source turns each `Filter` into its own query (a
  `WHERE` clause, a numpy mask). A source that can't apply an operator says so, and the
  filter bar marks the filter invalid.
- **Saved state** holds the settings (the sort, the search, the filters) and
  `selected_ids`, never the data or the source. The app gives the view its source again
  after loading, as it builds its model.

The steps. Each one is a commit of its own that `make check test` passes, with its tests
and its documentation, and leaves the table usable as far as it goes. The registry test
requires the same renderer keys on every backend
(`test_every_backend_registers_the_same_renderer_keys`), so a step that adds the
renderers adds them on Qt, Textual and the web together. Then each feature lands on the
three backends in one step.

1. **The source protocol and a list source.**
   - Add the module `composeui.core.tablesource` (and its page in `docs/api/`): the
     `TableSource` protocol, with its `columns` (name, header and type),
     `ordered_ids(sort, search, filters)` (the shown rows' ids, in order),
     `cells(ids, columns)` (the rows' values) and a `changed` signal. The filters are
     the `Filter`s that `parse_filter` gives.
   - Add `ListSource`, on a list of `attrs` records, sorted, searched and filtered in
     Python, as `TableView` does.
   - Tests: the order, the search and each filter operator, on a `ListSource`.
   - Done when another source can be written from the protocol alone.
2. **The view, in `core`, with no renderer yet.**
   - Add `DataTableView` (working name) to `core/view.py`, generic over its ids' type,
     with no `_renderer_key` yet: step 3 sets it with the renderers, so the widget
     catalog (`docs/_ext/widgetcatalog.py`) lists the view once it shows.
   - Its attributes: `source` (excluded from the saved state, as a `Signal` is),
     `sort_column`, `sort_descending`, `search`, `filters`, `selected_ids`,
     `selection_mode` and `column_formats` (e.g. `.6g`). Its signals:
     `selection_changed` (the ids) and `row_activated` (an id).
   - What renderers read: `row_count`, and `rows(start, stop)` (the ids and the
     formatted cells). The ids in order are kept in an `array`, and the windows read
     last in a cache (e.g. 4 windows of 200 rows), cleared by a new order or `changed`.
     Selecting a range takes its ids from the `array`; an id that is gone drops from
     the selection.
   - Tests: a source that counts its reads checks that `rows` reads only the windows
     asked, and that a sort or `changed` reads the order again. Saving and loading
     keep the settings and `selected_ids`, without the data.
   - Done when a test drives the whole view with no backend.
3. **Show the rows on the three backends.** The headers and the rows, scrolled, with no
   sort, filters or selection yet. Set `_renderer_key = "data_table"`, and register it in
   the `RENDERERS` of each backend.
   - **Qt.** A `QAbstractTableModel` on `QTableView`: `rowCount` is `row_count`, `data`
     reads `rows` from the cache, and a new order resets the model.
   - **Textual.** A widget on `ScrollView` and `render_line` (Textual's line API), as
     `DataTable` keeps every row: `virtual_size` has a line per row, each drawn line
     reads its row from the view, the header line stays on top, and the arrow keys,
     Page Up and Page Down scroll.
   - **The web.** Pages of rows first, not a scroll: the rows of one page, the count,
     and Previous and Next buttons, through the existing event route. Step 7 adds the
     scroll.
   - Docs: a section in the user guide (what it is for, against `TableView`, and what
     each backend shows), and the widget in "Already there" at the top of this file.
   - Example: an app of generated results (e.g. 1M rows of numbers), with its section
     and screenshots in the examples guide.
   - Tests: on each backend, a source of 1M rows shows its first rows, the count, and
     the rows at another position after a scroll (or on another page).
   - Done when the example shows 1M rows on each backend without reading them all.
4. **Sort.** A header click sets `sort_column` and `sort_descending`, and the header shows
   the order: `sortIndicatorChanged` on Qt, a click on a header line on Textual, a header
   button on the web, as in `TableView`. Tests on each backend: a click sorts, a second
   click reverses, and the selection stays on its rows.
5. **Select.** As `selection_mode` allows: a click, Ctrl+click and Shift+click on Qt (a
   `QItemSelection` of ranges, turned into ids by the view) and on the web; Space and
   Shift with the arrow keys on Textual. A double click or Enter emits `row_activated`.
   Tests on each backend: `selected_ids`, `selection_changed`, a range over rows not
   read yet, and `selected_ids` set by the app shown.
6. **Search and filters.** Reuse the filter bars of `TableView`: `QTableFilterBar` on Qt,
   `ComposeFilterBar` on Textual, the web table's bar. They take the same text and show
   the count ("1,234 of 1,000,000 rows"); a filter that the source can't apply is
   marked invalid, as an unparsable one is. Tests on each backend: a search, a filter,
   its removal, and the count.
7. **The web: a scroll instead of pages.**
   - A window of rows between two filler rows that give the scroll bar its full height,
     each row of the same fixed height. When the scroll pauses, `page.js` asks the
     fragment route (`GET /widget/{id}?start=…`) for the window shown, and drops an
     answer that comes after a newer request (`hx-sync`). A sort or a filter swaps the
     first window and the count.
   - A browser caps an element's height (check it: about 33M px in Chrome, 17M in
     Firefox). Past that, the filler rows keep the cap, and a scroll position maps to a
     row by its ratio.
   - `aria-rowcount` and `aria-rowindex` tell a screen reader where the rows are.
   - Follow the `web-security` skill for the route. The scroll code adds to `page.js`
     (958 lines today): see its type-check entry in "5 — Later, when needed".
   - Tests: `tests/test_webrenderer.py` for the route's answer, and browser tests for
     the scroll, past the cap too, and the keys.
8. **A source on a `SqliteTable`**, which stays as it is: a `SqliteTable` can hold several
   SQL tables, and not each one shows in a table.
   - Add `SqliteSource` to `core/sqlitemodel.py`. It takes the `SqliteTable` (its
     `connection()`, and its `changed` signal), the app's `SELECT`, its id column and
     its columns.
   - `ordered_ids` runs `SELECT id FROM (<query>) WHERE … ORDER BY …`, with the filters'
     values as parameters, and `cells` runs `… WHERE id IN (…)` on a window. A column
     sorts only when the source declares it: SQLite takes no column name as a parameter.
   - A text filter is a `LIKE … ESCAPE`. A `/regex/` filter calls a `regexp` function
     that the source adds to the connection, which scans every row.
   - Docs: the user guide tells the app to index the columns that sort (a sort on a
     column with no index scans the table; measure it on 1M rows). The query blocks the
     main thread while it runs; running it as a job is for later, if an app needs it.
   - Example: `pipesweep.py` shows its runs (`sweep_run`) in a `DataTableView`.
   - Tests: each filter operator against `ListSource`'s answers, a quote or a `%` in a
     search, a column that isn't declared refused, and `changed` after a job's write.
9. **A numpy source**, in an optional extra: columns as arrays, a stable `argsort` for
   the order, a boolean mask per filter, and the row's index as its id. Tests: the same
   cases as `ListSource`, skipped without numpy (`pytest.importorskip`).
10. **Copy.** Ctrl+C copies the selected rows as tab-separated text, read from the source
    a window at a time: the clipboard on Qt and Textual, the page's clipboard on the web.
11. **Export.** Export the shown rows, in their order, as CSV, read a window at a time: to
    a file the user picks on Qt and Textual, a streamed download on the web (the
    `web-security` skill for the route).
12. **Edit**, if an app needs it: `update`, `insert` and `remove` on the source, as
    optional methods, and editable columns. An edit is parsed into the column's type
    with `CONVERTER`, and a `RefusedError` refuses it, as in a `RecordTableView`. A
    `SqliteSource` calls the app's own queries, so that `refusals` gives the user its
    message.
13. **The user moves rows**, in `TableView` and in the large table: move up and move down
    actions on the view on each backend, then drag and drop on Qt.
    - For a `SqliteTable`, keep the order in a table of positions, as
      [composeui-table](https://github.com/ehmoussi/composeui-table) does
      (`core/ordering.py`): a trigger puts each new row last, and one window-function
      query moves the rows. Copy that SQL, run it through `SqliteModel.connection()`
      without its own commits, and make `get_row_ids(positions)` keep the order of the
      positions it gets.
    - Also worth copying: its `ListTableModel.move_rows` (the destination shifted by the
      rows taken from above it), and on Qt, `_pack_positions` and `dropMimeData` (each
      run of rows moved by one `beginMoveRows`).

## 2 — Charts

`ChartView` is in (user guide, "Charts"): line, step, scatter and bar charts, log axes,
reference lines, and report images drawn by matplotlib, on Qt (pyqtgraph), Textual
(textual-plotext) and the web (uPlot); `examples/pipechart.py` shows it. Left:

1. **A date and time x axis**: x values as timestamps, ticks and hovered values as
   dates ("Jun 14 2026", "Oct 18 08:00") in the main view's language.
2. **Timeline (Gantt) chart**: a `ChartKind.TIMELINE` of intervals, a row per category,
   a bar from start to end colored by its series, with a hover text per bar (the
   interval's details); on a date axis.
3. **Web: full resolution on zoom**, once a real app needs it. A thinned curve hides
   detail once zoomed in: on uPlot's `setScale` hook (debounced), the page asks
   `GET /widget/{id}?x_min=…&x_max=…` and the renderer answers that range's points,
   thinned to the same cap (`CHART_MAX_POINTS`), as JSON that the script `setData`s
   without rescaling. Fits the existing fragment route.

What a scientific app's charts need beyond these (see "Missing for a scientific app" in 1):

4. **Axes' ranges** set by the app (`x_min`, `x_max`, …), which a "Graph settings" form
   edits with the title and the axes' titles; a category axis' **labels' orientation**.
5. **Error bars**: an interval per point (a Sobol index's confidence interval, a
   quantile's on a CDF).
6. **Markers and point labels**: a dot's shape (+, square, circle) and a text beside a
   point (the variables' names on a Morris plot).
7. **Dots over categories**: a scatter series on a `BAR` chart's categories, each series
   shifted a little (first order and total indices per input).
8. **A histogram**: bars over numeric bins, with a density curve over them.
9. **Box plots**: a box per variable, its whiskers and outliers.
10. **A pie chart** (importance factors).
11. **Contours and a color bar**: a 2D density's iso-lines colored by a scale, the scale
    beside the chart (a copula's PDF).
12. **Parallel coordinates (cobweb)**: one axis per variable, a line per sample, the
    user brushing an axis' range to highlight the lines through it.
13. **A scatter plot matrix**: a scatter per pair of variables, a histogram on the
    diagonal, a cell's background colored by its correlation, the user zooming on one.
14. **Draggable reference lines**: the user moves a line, its value emitted (Morris'
    "no effect boundary", the points left of it unselected).

## 3 — A SQLite model

`SqliteModel` is in (user guide, "A SQLite model"): the app's tables and SQL, transactions,
typed rows, a `changed` signal per table, and studies saved as a zip of the views' state
and the database, checked before opening and brought up to date by migrations; on the
web, per session; `examples/pipecatalogue.py` shows it. A job writes to it, its `changed`
signals emitted on the main thread (`examples/pipesweep.py`).

## 4 — Adoption

1. **Publish the documentation site** (`make docs`, Sphinx + MyST) on GitHub Pages or Read
   the Docs, and link to it from `README.md`.
2. **Packaging story** for apps built on ComposeUI: PyInstaller or briefcase for Qt, a
   plain `uvicorn` deployment note for the web.
3. **`CHANGELOG.md`, semantic versions and a PyPI release.**

## 5 — Later, when needed

- **Web: keep sessions across restarts.** `--reload` already keeps them, in a scratch
  directory, with a signing key that lives as long as the server. A deployed app needs a
  lasting store (a directory, or Redis) and a fixed signing key from the environment, and
  raises multi-process serving (sessions live in one process's memory today).
- **Web: type-check `static/page.js`.** Add `// @ts-check` and JSDoc types, checked by
  `tsc --noEmit --allowJs` as a CI-only step; start with uPlot's chart options. Only worth
  it once the script passes about 2000 lines (958 today) or several people edit it: it
  brings Node into CI, and it can't check the `data-*` attributes and custom events it
  shares with `webrenderer.py`, which the browser tests cover.

- **Textual: reload in place.** Its `--reload` runs the app again in a new process on
  every change. Run `rerun_program` in the Textual app instead, as `qtcore` does, and
  mount the new main view in the running `App`, so the widgets keep their state (a scroll
  position, the focus) when only the app's code changed.
- **Qt `--reload`: what a reload still loses or keeps.** The widgets' own state, which no
  view holds (a scroll position, a column's width, the focus), is lost. The previous
  classes stay in memory: the `cattrs` converter keeps their hooks, so memory grows a bit
  with every reload. Threads that the app started keep running the previous code.

## Design notes for the web backend

Not tasks: the non-obvious decisions to keep in mind when changing `composeui.webcore`.
The user guide's "Web backend" section covers what users see.

- **htmx request/response**, no websockets or JS framework; Starlette, not FastAPI;
  hand-written HTML per renderer (no Jinja2), built with `markupsafe.Markup`, which escapes
  every value put in it.
- **No code in the markup.** The page's `Content-Security-Policy` (`headers.py`) runs
  script files only, and htmx runs without `allowEval`: no inline handler, `hx-on`, `js:`
  value or trigger filter. A renderer marks its element (`data-post-event`,
  `data-close-dialog`, ...) or triggers on a custom event (`enter-key`, `escape-key`,
  `activate`), and `static/page.js` does the rest.
- **Ids.** A renderer's rendered object is `cui-{id(view)}-{role}`; a hidden fragment's
  root keeps its id (`hidden` attribute) so a later swap has a target.
- **Updates.** Setting a view attribute marks its renderer dirty in a request-scoped set
  (`collect_dirty`, a no-op outside requests); the route then renders every dirty
  fragment as an OOB swap (`render_dirty`). Controls use `hx-swap="none"` and the sender
  is never swapped back, so typing is never interrupted; the one exception is a float
  field left with unparsable text, swapped back to the view's value.
- **A table's parts.** A sort, a search or a filter swaps only what it changes (the
  headers' row, the `<tbody>`, the count, the filter bar), never the search field being
  typed in. The bar goes last in the response: it may hold the element that sent the
  request (the filter editor's form), and htmx swaps no fragment after that one is gone.
  The `<tr>` and `<tbody>` go each in a `<template>` of its own: bare, they switch htmx's
  parsing of the whole answer to a table's rules, mangling the fragments after them.
  An invalid filter value swaps only its message, which `syncInvalidFields` marks the
  field by.
- **Changes from threads.** `call_on_main_thread` runs its callback under the session's
  lock and keeps what it changed in the session's `pending`, sent with the next event's
  response or fetch (a full page drops them). While the main view's jobs run, the page's
  `cui-jobs` poller fetches `/jobs` every `JOBS_POLL_MS`, which brings them: no push, no
  websocket, and an idle page sends nothing. A response whose event starts or ends the
  jobs swaps the poller in, as it does the page's marker.
- **Sessions.** A signed cookie maps to a `WebSession` holding its renderers by id and an
  `RLock` (the status bar timer takes it through `call_on_main_thread`). A request whose
  session is gone answers `HX-Refresh`.
- **Open** applies an upload to a scratch instance first (core's `load_state_data`), so a
  bad file never half-loads. Responses send `Cache-Control: no-store` and controls set
  `autocomplete="off"`, so a reload always shows the server's state.
- **Dialogs** render at the end of the page, outside the pages' slots (a hidden slot
  would hide them). The browser opens a modal `<dialog>` only from a script: `page.js`
  opens each one swapped in shown, once. A button closes its dialog in the browser
  first, so focus returns where it was, then posts its answer; the server swaps it closed.
- **Header.** A web app's header, not a desktop menu bar: File's New, Open and Save are
  buttons of their own (Save As and Exit left out), and any other menu is a dropdown
  under its title, marked with a chevron so it reads apart from the buttons. A
  `ToolBar`'s buttons go before the menus. A dropdown is as wide as its longest item, the
  shortcut a faded hint beside it. On a phone the buttons with an icon keep only their
  icon and the app's title is cut short, so the header holds on one line, the pages'
  toolbar on a row of its own.
- **Icons.** An action's `icon` is a file path, as Qt reads it: `icons.py` serves the
  file at `/icon/<digest><suffix>`, an address naming its content, cached for good. Only
  image files a view has named are served, and `icon` is never loaded from a study, so
  no request can name a file. An SVG is drawn as a CSS mask in the text's color, so it
  follows the theme like the built-in New/Open/Save icons; another image shows as is.
- **By design:** `Menu.is_visible` is ignored (a dropdown is always shown); action `data`
  isn't displayed; Ctrl shortcuts become Alt+Shift; an unknown page address is a 404, not
  a redirect (browsers ask for addresses of their own, like `/favicon.ico`).
- **Tests** drive the examples over HTTP with Starlette's `TestClient`
  (`tests/test_webrenderer.py`); browser-only behaviour (caret, shortcuts, `aria-invalid`
  sync, offline page, history, opening dialogs) is in `tests/test_browser.py`
  (`make browser-test`).
