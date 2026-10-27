# Roadmap

What's left to do on ComposeUI. What is done is gone from here, and lives in the code, the
docs and `git log`. Build and test each step before moving on, and delete a step's entry
once it lands.

## 1 — Widgets

One widget at a time, with tests on each backend. Only maps may leave out a backend
(Textual), which the registry test checks. Already there: horizontal, vertical and grid
layouts, a status bar, menus, toolbars, input, float
input, integer input, date input, file path input (a "…" button and a reload button),
slider, label, log, button, progress bar, metric, expander, checkbox, radio group,
combobox, table (editable cells, sorting and filtering, widgets in cells, cell colors,
marks, disabled cells, row spans, header groups and row headers included),
tree (its nodes with an icon, a mark and a style), Markdown, forms, pages, tabs, resizable
panes (a splitter), sidebar, a list of views from data, message, confirm and form dialogs
(including typed form dialogs),
a large table (rows read from a source as they show; see "Large tables" below), and
street maps with point overlays (Qt Location on Qt, deck.gl on the web).

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

`DataTableView` is in (user guide, "A large table"): a read-only table that reads only the
rows it shows from a `TableSource` (`ListSource`, `SqliteSource`, `DataFrameSource`), on
Qt, Textual and the web. The view holds the order (the shown rows' ids, in an `array`), the
selection by id, and the settings that the study saves, never the data. `largetable.py`
shows it on SQLite, and `uberpickupsframe.py` on a Polars frame. A numpy source of numeric
columns alone could come back if an app has arrays and no dataframe library. Left, each
step on the three backends together (the registry test compares their renderer keys):

1. **Edit**, if an app needs it: `update`, `insert` and `remove` on the source, as
   optional methods, and editable columns. An edit is parsed into the column's type
   with `CONVERTER`, and a `RefusedError` refuses it, as in a `RecordTableView`. A
   `SqliteSource` calls the app's own queries, so that `refusals` gives the user its
   message.
2. **The user moves rows**, in `TableView` and in the large table: move up and move down
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

1. **Packaging story** for apps built on ComposeUI: PyInstaller or briefcase for Qt, a
   plain `uvicorn` deployment note for the web. Document it as a "Deploy the app" section
   of the user guide's "Running the app", once each recipe has been tried:
   - **The web:** one process (the sessions live in its memory) behind a reverse proxy,
     with an nginx or Caddy example that keeps `Host`, `Origin`, `Referer` and
     `Sec-Fetch-Site` as the browser sent them (the origin check needs them), and what a
     restart loses.
   - **Qt:** a PyInstaller build, with what a map needs (`map.qml`, the Qt Location and
     Qt Positioning QML modules, the location plugins; now in the user guide's "Maps").
   - **Textual:** the app as a script or a console entry point.
2. **A PyPI release**, with the version tag and the date of its entry in `CHANGELOG.md`.
   Then give the agent skill (`docs/_site/skills/composeui/SKILL.md`) the version it
   describes, checked by a test against the package's version, so an agent can tell that
   its copy is old.

## 5 — Later, when needed

- **Web: keep sessions across restarts.** `--reload` already keeps them, in a scratch
  directory, with a signing key that lives as long as the server. A deployed app needs a
  lasting store (a directory, or Redis) and a fixed signing key from the environment, and
  raises multi-process serving (sessions live in one process's memory today).
- **Web: type-check `static/page.js`.** Add `// @ts-check` and JSDoc types, checked by
  `tsc --noEmit --allowJs` as a CI-only step; start with uPlot's chart options. Only worth
  it once the script passes about 2000 lines (1175 today) or several people edit it: it
  brings Node into CI, and it can't check the `data-*` attributes and custom events it
  shares with `webrenderer.py`, which the browser tests cover.
- **Web: raw HTML in Markdown.** The web shows raw HTML in a `MarkdownView` as text
  (`{"html": False}`), so a help page can't use `<details>` or `<kbd>`. To allow it, clean
  markdown-it's output with `nh3` (add it to the `web` extra) and an allowlist of tags. Not
  needed today: no view shows HTML that it doesn't escape.

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
- **A large table's frame.** `WebDataTableRenderer` draws a window of rows between two
  filler rows (`style` heights, which the policy allows) that give the scroll bar every
  row's height. `page.js` posts the first row shown once the scroll stops outside the
  window, and only the `<tbody>` comes back (in a `<template>`, as a table's parts), so
  the scroll position stays. Browsers cap an element's height: past
  `DATA_TABLE_SCROLLED_ROWS`, a filler's row height stands for more than one row. The
  page maps the scroll position through the fillers as drawn, and posts the row under the
  headers with its offset; the server sizes the filler above the new window so that row
  stays there, the frame's height kept. A new order swaps the whole frame, back at the
  top.
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
