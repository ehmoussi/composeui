# Roadmap

## Goal

Make ComposeUI the first choice to turn a Python analysis into an app that people use. A
developer starts with a few lines of code and a dataframe, shares the result, and grows it into
a structured application without a rewrite. The same app runs on the web, on the desktop (Qt),
and in the terminal (Textual).

An app is ready when a developer can:

1. **Start fast.** Build a dashboard from an analysis in a few dozen lines: filters, a table,
   charts, metrics, uploads and downloads.
2. **Stay responsive.** Recompute only what an input changes, in the background, with shared
   data and cached results.
3. **Reuse existing code.** Show the analysis' dataframes, NumPy arrays and Matplotlib figures.
4. **Grow without a rewrite.** Move a panel into a view class, add pages, dialogs, a SQLite
   model and saved studies, with the same objects.
5. **Share it safely.** Deploy the app in a container, with users, access control, and sessions
   that survive a restart.

What sets ComposeUI apart:

- **Reactive, not rerun.** An app is built once per session. An input updates only the views
  that depend on it.
- **Typed.** Views are `attrs` classes, and type checkers see the whole app.
- **Testable without a browser.** Tests drive the app's views and signals directly.
- **One app, three backends.** The same code runs in a browser, as a desktop app, and in a
  terminal.
- **Saved work.** A study saves the views' state and the app's data, and opens it again.

ComposeUI 0.3.0 is pre-alpha. The [user guide](docs/user-guide.md), the
[widget catalog](docs/widgets.md) and the [technical guide](docs/technical-guide.md) describe
what exists. This file holds only the work that is left.

## Principles

1. **One application model.** A helper builds ordinary views and signals. Do not add a second
   state store or execution engine.
2. **Built once, then reactive.** A short API must not hide a rerun of the whole script.
3. **Optional dependencies.** Integrations go in extras. `composeui.core` imports no backend.
   Dataframes go through Narwhals, so the app chooses its dataframe library.
4. **The same widgets on each backend.** A core widget has a renderer and tests on Qt, Textual
   and the web. The exceptions are maps (not on Textual) and the Python console (never on the
   web). A backend that cannot show a view says so, and never drops it silently.
5. **The core computes, the backends draw.** Bins, quartiles, stacks, layouts and colors are
   computed once in the core. Each backend draws simple shapes: bars, lines, points, text.
6. **Clear data ownership.** Keep view state, session data, shared data and lasting records
   apart. A signed session cookie is not a user identity.
7. **Presentation by role, not by style.** An app says what a text or a field is: a title, a
   caption, a short field. Each backend maps the role to its own look. A color that encodes data,
   such as a color scale, is data, not style.
8. **Add from real needs.** Add a helper when two apps repeat the same code, and an
   integration when a real user needs it.
9. **Measure before claiming speed.** Compare equivalent workloads, with the other frameworks'
   caching on.

## How to read this roadmap

- **Each item says what, not how.** Design it when the work starts.
- **Each item has a horizon:**
  - **Now:** the dashboards slice, from an analysis to a shared dashboard.
  - **Next:** scientific and desktop apps.
  - **Later:** apps for a team, and a stable API.
  - **When needed:** waits for an app or a user that asks for it.
  - **To research:** no design is agreed yet.
- **Delete an item when it lands.** The code, the docs, `CHANGELOG.md` and `git log` record
  what is done.
- **Each horizon ships as 0.x releases.** A release's changelog says what users can now build.

The order of the work for **Now**:

1. The charts: check the HTML, then the new charts.
2. Deployment in a container.

## Data and dashboards

- **Cached query results** (Now). Results kept by their parameters, with an expiry, a size limit
  and a refresh. A recipe in the user guide reads a SQL query into a table and a chart, and keeps
  the user's work when the query fails.
- **Checks on whole columns** (Next). `fill_from_frame` and the CSV import check the common
  validators of a row class, such as `ge`, `le` and `in_`, and its dates, in the frame's library,
  not in Python for each row. Done when the Uber CSV imports in about 2 s, against 8.5 s.
- **Matplotlib figures** (Now). A figure view that redraws when the app changes the figure: an
  interactive canvas on Qt, an image on the web and Textual.
- **A NumPy table source** (Next). Arrays sorted and filtered with NumPy alone, tested against
  the other sources.
- **NumPy arrays in SQLite** (Next). A column that stores an array with its type and shape.
- **Undo and redo** (Next). Undo the model's changes, one step per transaction, as commands.
- **Full-text search in large tables** (When needed). SQLite's FTS5 as an option per table, if a
  measure shows that the current search is too slow.
- **A source that queries a database server** (When needed). Sorting and filtering on the server,
  for a table too large to load. DuckDB is a candidate.

The SQLite model is complete otherwise: do not rebuild it.

## Long computations

What an app needs to follow work that runs outside it, such as a solver or a cluster's job.

- **Services of the app** (Next). Work for the whole process, started with the app and stopped
  at its shutdown, shared by every web session, such as one poller or one connection. Today
  `shared_data` loads once, but has no end.
- **Following a log file** (Next). A file that another program writes, read as it grows into a
  `ConsoleView`, with bounded memory. For a solver that writes its own log, not its output.
- **Programs that outlive the app** (To research). A `Job.run_process` variant whose program
  keeps running after the app closes, found again by its stored identity when the study opens.
  Only if a local-solver app, such as Code_Aster Studio, needs it.

## Widgets

- **Interactive drawings** (When needed). Picking, dragging and editing the shapes of a
  `DrawingView`.
- **Saving a drawing as an image** (When needed). A report's image of a `DrawingView`, with a
  title that names the file and shows in the image, as a chart's does.
- **A table's category column filtered as a choice of its values** (Now). A check list of the
  column's values in the filter bar, on `MultiValuesMixin`.
- **A searchable picker** (Now). A combobox that filters its values as the user types, searched
  on the server for long lists.
- **Switches and busy indicators** (Now). A switch look for `CheckBoxView`, and a progress bar
  without a maximum.
- **Highlighted code in Markdown** (Now). Code blocks of a `MarkdownView` highlighted by
  Pygments, on the web and Qt.
- **Context menus** (Next). On tree nodes and table rows, built from `Menu`, with keyboard
  access, and a "⋮" button on the web.
- **Commands** (Next). One action, with its text, shortcut and enabled state, shared by a
  button, a menu entry and a toolbar entry.
- **A wizard** (Next). Steps with Back, Continue, Finish, Cancel and Help, each step checked
  before the next, steps skipped by the answers.
- **Tabs that the user adds and closes** (Next). A tab per record, the app deciding what a close
  means.
- **Entries** (Next). A row with a title, a description, an icon, a badge and its actions, alone
  or in a list, such as recent files.
- **Optional fields and durations** (Next). A field enabled by a check box beside it, whose value
  is `None` while unchecked, and a duration field that reads "1d 2h 30m".
- **Field widths and a compact density** (Next). Widths that follow a field's kind, and a
  compact look for apps with many fields.
- **Navigation in a side list** (Next). The router's pages in a side list, grouped in sections,
  with badges.
- **Nested routes** (Next). A router inside a page, with addresses such as `/results/42/tables`.
- **A Python console** (Next). For apps that offer scripting. It runs on Qt and Textual only,
  never on the web.
- **An app's own renderers** (Next). A public way to register a renderer, and a placeholder when
  a backend cannot show a view.
- **Catalogs of a library** (Next). A package of views adds its translation catalogs, after the
  app's and before ComposeUI's, so that the app's own translation wins. `composeui translations`
  checks the library's text too.
- **A folder browser** (Next). The files of a folder, with their size and date, that the user
  opens or downloads. For a run's results.
- **A workflow diagram** (When needed). Steps joined by arrows, a click starting a step.
- **Scripts and tests of a package's widget** (When needed). A package's web renderer adds its
  own scripts and stylesheets to the page, and its tests use the drivers of `tests/contracts/`.
- **Help pages in Markdown** (To research). Folding sections, notes and keys that work on the
  three backends.

## Tables

- **Color scales** (Now). A scale that maps values to colors, a table column colored by it, and a
  legend.
- **Editing a record of a large table** (Now). A recipe: select the row, edit it in a form
  dialog, write it with the app's own query.
- **Moving rows** (Next). Move up and Move down in small tables, by keys or commands, and by drag
  and drop on Qt.
- **Editing cells of a large table** (When needed).
- **A lasting row order in a large table** (When needed). Reuse
  [composeui-table](https://github.com/ehmoussi/composeui-table) after checking it.

## Charts

- **Evaluate [`textual-plot`](https://github.com/davidfokkema/textual-plot)** (Now). Zoom and pan
  on Textual, if it matches `textual-plotext`'s charts and keeps Python 3.9 support.
- **Histograms** (Now). Bins computed in the core, by count, percent or density.
- **Range selection** (Now). Selecting an x range emits it, for example to filter a table. Not
  on Textual.
- **Pie charts** (Now). A view of its own, with a slice for the rest and an optional hole.
- **Heatmaps** (Now). A grid of values colored by a color scale, with its legend.
- **Error bars and bands** (Next). Bounds for each point, as bars or as a band.
- **Marker shapes and point labels** (Next). Shapes so that charts read without color, and
  labels taken from the data.
- **Points over categories** (Next). Point series beside bars, shifted as bars are.
- **Box plots** (Next). Statistics computed in the core or given by the app.
- **Movable and slanted reference lines** (Next). A line the user drags, kept in step with a
  field, and fixed lines through the origin, such as the Morris method's.
- **Contours** (Next). Lines of equal value over a heatmap.
- **Parallel coordinates** (Next). Ranges on each axis that pick the samples shown.
- **Linked charts and a scatter plot matrix** (Next). Charts that zoom together, and a helper
  that builds a matrix of them.
- **Timelines** (Next). Intervals on a time axis, one row per category.
- **Points added to a series** (Next). New points sent alone to the backend, not the whole
  series again, for live data such as a solver's residual.
- **Full resolution on zoom** (Next). The web fetches the points of the range shown, for long
  series.

## 3D and geometry

- **Geometry files** (Next). A CAD file, such as STEP or IGES, with a tree of its parts, picked
  faces and measurements. [cad-3d-viewer](https://github.com/tegos/cad-3d-viewer) is the model.
- **Meshes and 3D results** (Next). A mesh from a file, with its groups and the fields on it, in
  a VTK view. How the web draws it is to research.

## The web page

- **Check the HTML** (Now, with the charts). The rendered HTML checked against the scripts and
  the page's policy, as `make js-check` checks the scripts' types.
- **Links that keep the state** (Now). The fields that an app names go in the page's address, so
  a copied link opens the same view.
- **A session per tab** (Now). An option, so that two tabs of a browser do not share their
  state. Links that keep the state need it.
- **A warning when the tab closes** (Next). The browser's "Leave site?" prompt while the study
  has unsaved changes, but not on Save or the app's own reloads. After a session per tab, so that
  closing one of two tabs doesn't warn. First measure what the flag costs per request.
- **Push from the server** (When needed). Server-Sent Events or websockets, if polling
  `/_composeui/jobs` is not enough.

## Deployment and users

- **A container** (Now). A Dockerfile, the port from `PORT`, a `/health` route, settings from
  environment variables, documented logs, and a clean shutdown on SIGTERM. The docs list what
  any platform must give the app.
- **Idle sessions that wake without a reload** (Next). A session that `session_idle` saved comes
  back as it was: the page's next click works, and the text being typed is kept. A session that
  can't be kept this way, or that a restart woke, reloads its page as today.
- **Sessions that survive a crash** (Later). `session_folder` keeps them across a restart, and
  the idle ones across a crash: a copy of each session in memory at intervals, with its uploads
  kept while a copy names them and one writer for its last use.
- **Formulas in CSV exports** (Now: a `shared` database holds what other users wrote). A table's
  Export CSV and `frame_content` escape a text cell that a spreadsheet would run as a formula,
  with a way to keep the exact values.
- **Users** (Later). The user read from a login proxy's headers, for OIDC, SAML2 or Basic Auth,
  with recipes for the proxies.
- **Access control** (Later). An authorization hook that the server enforces for pages, actions
  and downloads.
- **Several processes** (Later). Sticky sessions in nginx.
- **Framing and per-user limits** (Later). The sites allowed to frame the app, and a share of
  the disk per user.

## Desktop

- **Packaged apps** (Next). A tested PyInstaller recipe for Qt, built and started in CI on
  Linux, Windows and macOS, and a section on Textual apps installed as commands.
- **A desktop web backend** (Next). The web renderers in a native window through pywebview,
  with a local server that only the window can reach.
- **The browser's fake paths** (Next). Refuse the browser's `C:\fakepath` in a path typed on
  the web.
- **Recent folders** (Next). The picker of the server's files opens at the last folder, with a
  short history inside the allowed roots.
- **Save in the unsaved-changes question** (Next). Save, Discard and Cancel before New, Open
  and Exit, on Qt and Textual. Save goes through the file picker when the study has no file, and
  the action goes on only once the file is written: a canceled picker cancels the action.
- **Save in the web's unsaved-changes question** (When needed). The page downloads the study,
  then runs New or Open: the dialog's htmx answer can't start a download.
- **Reload keeps the widgets' state** (Next). Scroll positions, column widths and focus survive
  a reload on Qt. First, measure the memory that each reload keeps.
- **Textual reload in place** (When needed). After the Qt reload keeps its widgets' state.
- **Stopping a program's children on Windows** (Later). `Job.run_process` stops only the
  program that it started: the programs that this one started go on. A Windows job object stops
  them all.
- **PyQt6** (When needed). When an existing PyQt6 app wants to use ComposeUI.

## Testing

- **Testing an app as it renders** (Next). Helpers that find a control by role and name, check
  that it is shown and enabled, and act on it, on each backend.

## Examples

- **Rework the examples** (Now, then Next). Believable apps on one realistic dataset, in the order
  of the goal:
  1. A first dashboard from a CSV (exists).
  2. The data explorer, a user's own file (exists).
  3. The same dashboard, grown into view classes, pages and a saved study (Now).
  4. A scientific workbench: parameters, a background computation, results and a report (Next).
  5. A shared internal tool: login, records, permissions (Later).
- **A widget gallery** (Now). One app that shows every widget, and makes the catalog's
  screenshots.
- **Notebooks** (When needed). Start with launching an app from a notebook cell.

These apps are also the reference apps: the work of each horizon is checked against them.

## Budgets

Measured by [`benchmarks/`](benchmarks/README.md), on native Linux:

- An hour move in the SQLite Uber example: less than 500 ms on the web.
- The Uber CSV loads in less than 10 s.

Add regression thresholds to CI only once there are real users, and only where results are
reproducible.

## Known problems

- **SQLite moves miss the budget with 4 sessions at once.** In the SQLite Uber example on the
  web, a move takes 0.40 s with one session and 0.53 s with 4 at once, at the median. Loads no
  longer slow down: the sessions share one database, and 4 load in 9.6 s, as one does
  ([a shared database](benchmarks/README.md#a-shared-database)).
- **A tab of an older version stops answering.** After an upgrade that changes the backend's
  addresses, a tab left open sends its posts to addresses that the server no longer serves.
  They get a 404, which htmx doesn't show: a click does nothing until the user reloads the
  page. A fix reloads the tab once, only when its page names another version, so that a page
  of this version can never reload in a loop.

## Stable release (Later)

A stable API, with a deprecation policy, maintained packaging recipes, and fixtures that open
studies and sessions from older versions through `state_version` and `migrate_state`. Clean
installs are checked on each supported Python and extra.
