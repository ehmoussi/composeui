# Roadmap

## Goal

Make ComposeUI the first choice to turn a Python analysis into an app that people use. A
developer starts with a few lines of code and a dataframe, shares the result in a browser, and
grows it into a structured application without a rewrite. The same app runs on the web, on
the desktop (Qt), and in the terminal (Textual).

An app is ready when a developer can:

1. **Start fast.** Build a dashboard from an existing analysis: filters, a table, charts,
   metrics, uploads and downloads, in a few dozen lines.
2. **Stay responsive.** Recompute only what an input changes, in the background, with
   cached results and shared resources.
3. **Reuse existing code.** Show the dataframes and the Plotly, Matplotlib or Altair figures
   that the analysis already makes.
4. **Grow without a rewrite.** Move a panel into a view class, add pages, dialogs, a SQLite
   model and saved studies, with the same objects.
5. **Share it safely.** Deploy the app with users, access control, sessions that survive a
   restart, and documented operations.

ComposeUI keeps its own model to get there. This model is also what sets it apart:

- **Reactive, not rerun.** An app is built once per session and reacts to events. An input
  updates only the views that depend on it; the script does not run again from the top.
- **Typed.** Views are `attrs` classes, and type checkers see the whole app.
- **Testable without a browser.** Tests drive the app's views and signals directly.
- **One app, three backends.** The same code runs in a browser, as a desktop app, and in a
  terminal.
- **Saved work.** A study saves the views' state and the app's data, and opens it again.

M0 sets measurable targets for the goal, and each milestone reports against them:

- The time from `pip install composeui` to a first app in the browser.
- The lines of the reference dashboard, compared with the same app written as a script.
- The response time and memory of the reference apps (see "Reference apps").

## How to read this roadmap

- **This file holds the work that is left.** Delete an entry when it lands. The code, the
  docs, `CHANGELOG.md` and `git log` record what is done.
- **Each entry has an identifier.** N is for data apps, W for widgets, T for tables, C for
  charts, A for adoption, and L for later work. Keep an identifier until its work is done or
  explicitly deferred.
- **Milestones give the order, not dates.** Choose dates only after estimating the work.
- **Each entry says when it is done.** A milestone is done when its acceptance examples work,
  its tests pass, its behavior is documented, and its limitations are recorded.

## Where ComposeUI stands

Release 0.1.0 (27 October 2026) is on PyPI. The README still calls the API pre-alpha: a
stable API is the goal of M5. The [widget catalog](docs/widgets.md) lists every widget and its
backends, and the [user guide](docs/user-guide.md) shows how to use them.

| Area | Already there |
| --- | --- |
| Core | Typed `attrs` views, reactive attributes, signals, callback injection, and lazy backend selection |
| Backends | Qt, Textual, and the web (Starlette and htmx); maps on Qt and the web only |
| Forms and layout | Inputs, validation, buttons, progress, metrics, expanders, trees, Markdown, pages, tabs, splitters, sidebars, view lists, menus, toolbars, and typed form dialogs |
| Tables | Editable tables, typed record tables, sorting, filtering, cell widgets and styles, header groups, and row headers |
| Large tables | `SourceTableView` on `ListSource`, `SqliteSource` and `DataFrameSource`: rows read as they show, selection by row ID, and CSV export |
| Dataframes | The `dataframe` extra: pandas, Polars, PyArrow and lazy frames through Narwhals, with `series_of` and `points_of` |
| CSV import | `CSVSqliteTable`: typed columns, column mapping, dialect detection, batches in a transaction, gzip, and URLs |
| Charts and maps | Line, step, scatter and bar charts, log axes, reference lines, report images, and `MapView` point overlays |
| Models and studies | `SqliteModel`: transactions, typed rows, change signals, study files with migrations, and `MainView.state_version` / `migrate_state` |
| Background work | Jobs with typed progress and cancellation, and reusable `Task` objects with their result and error |
| Deployment | One Uvicorn process behind nginx: TLS, proxy headers, request limits, and optional HTTP Basic Auth |
| Tooling | Tests on each backend and in a browser, an app-testing guide, several type checkers, CI on Python 3.9 to 3.14 and three OSes, and a coding-agent skill |
| Releases | PyPI, a changelog, Semantic Versioning, a public API per module, and automated publishing |

The [Uber pickups example](src/examples/uberpickups.py) and its
[dataframe version](src/examples/uberpickupsframe.py) are the starting point for dashboards.
They load a CSV in a task, and a filter updates a table, a bar chart and a map.

What is missing is mostly the path from analysis to app: a one-command start, short authoring
helpers, computed values, common dashboard widgets (an image, a download button, a toggle, a
range slider), adapters for plotting libraries, caches, editable sources, links that keep the
app's state, one-command deployment, user identity, and sessions that survive a restart.

## Principles

1. **One application model.** A dashboard helper builds ordinary views and signals. An app can
   mix helpers and view classes. Do not add a second state store or execution engine.
2. **Built once, then reactive.** Define when an app's factory runs, where its state lives, and
   how derived values update. A short API must not hide a rerun of the whole script.
3. **Optional dependencies.** Dataframe and plotting integrations go in extras or separate
   packages. `composeui.core` imports no backend.
4. **The same widgets on each backend.** A core widget has a renderer and tests on Qt, Textual
   and the web. The only exception is maps, which Textual omits. An extension declares the
   backends it supports and what the others show.
5. **Clear data ownership.** Keep view state, session data, shared resources, and durable
   records apart. A signed session cookie is not a user identity.
6. **Measure before claiming speed.** Reactive updates are a design choice, not proof of speed.
   Compare equivalent workloads with other Python dashboard frameworks, with their caching on.

The registry lets a backend leave out a renderer: the view then renders as `None`.
`tests/test_renderer_registry.py` requires the same keys on the three backends, maps aside.
Change that contract, and its tests, explicitly for extensions.

## Milestones

| Milestone | The developer can | Main work | Done when |
| --- | --- | --- | --- |
| M0 — Baseline | Compare future work with 0.1.0 | Benchmark the Uber examples; prototype reactive methods (N02) and helpers; specify capabilities and data ownership | Three reference apps are specified, measured, and used to review the proposed APIs |
| M1 — First dashboard | Build a dashboard in minutes from a CSV or a dataframe | N01, N02, N04 (Plotly), N05 (caches), N07 (uploads), N13, W06, T02 and N03 (an editable grid), N11 (`composeui run`) | The CSV dashboard uses ordinary ComposeUI objects, stays responsive during queries, and meets the M0 targets |
| M2 — Shared dashboards | Share a dashboard and reuse more existing code | N14, N15, N04 (Matplotlib), N06, N16, C01, C04 | A dashboard deploys in one command, its links keep its state, and it reads a SQL database |
| M3 — Scientific workflows | Configure, compute, inspect and export a study | W01–W05, W07–W11, T03, the other C items, N04 (Altair) | The scientific workbench covers each W, T and C item, or records why it waits |
| M4 — Shared apps | Deploy an app for a team | L01, N08, N09, end of N05 and N07 | Restart, isolation, access control and worker-topology tests pass |
| M5 — Stable release | Depend on the API and extend it | A02, N10, N11, L04, L05, the stability contract | A stable API with deprecations, compatibility fixtures, clean installs, and an extension packaged on its own |
| M6 — Community | Find a working example for their case | N12: gallery, recipes, more adapters, hosting | Outside developers ship apps and extensions without changes to ComposeUI's internals |

M1 and M2 come first: they give the shortest path from analysis to a shared app. M3 and M4 can
then progress in parallel. Each milestone ships as a 0.x release that users can try, and its
changelog says what they can now build. A conditional item blocks no milestone until its
condition is met.

## Next step

Build one thin slice from end to end before the full catalog:

1. **Measure.** Benchmark the two Uber examples: loading, filtering, row-ID memory, chart and
   map updates, and cleanup. Specify the scientific and shared-tool workflows.
2. **Prototype.** Build `@reactive` and `Task.start_latest` on the Uber examples (N02).
3. **Decide.** Check the prototype against the adoption criteria of N02: keep it, fall back
   to explicit inputs, or keep only `Task.start_latest`.
4. **Shorten.** Add a Plotly adapter with its backend capabilities (N04), then dashboard
   helpers that build the existing views, sources and tasks (N01).
5. **Load and export.** Add configurable uploads and filtered export to the data explorer
   (N07), and the dashboard widgets that it needs (N13).
6. **Start in one command.** Add `composeui run app.py`, with reload on (N11).
7. **Release.** Publish the slice as a 0.x version. Compare authoring effort, response time,
   memory and cleanup with the baseline before the API grows.

Continue the scientific backlog alongside, as capacity allows.

## Data apps

These entries make an analysis quicker to turn into an app. Optional integrations can ship on
their own, outside the core.

### N01 — Short dashboard code

Add constructors and helpers for common pages: a sidebar of filters, a table, charts, metrics,
uploads, and downloads. An app needs a view class only for reusable behavior.

The helpers return the existing view objects, give access to them, and work in a custom
`MainView`. Define when they are built for a session, how connections close, how state
restores, and how errors show. Prototype in M0; deliver in M1.

**Done when:** a CSV dashboard takes a few dozen clear lines, and one panel moves into its own
view class without other changes. Count meaningful code, not compressed formatting.

The first helpers are in place, and the Uber examples use them: `DashboardView` and
`bar_chart` in `composeui.core.dashboard`, `Task.show_state`, and `CheckBoxMixin.shows`.
The work left:

- **Uploads and downloads,** once N13 has their widgets.
- **More helpers from a second dashboard,** not by symmetry: a preset that only renames
  `child(...)` saves no code. Keep a helper when two dashboards repeat the same code.
- **The wiring of filters** to the views that they update: N02 decides it.

### N02 — Reactive methods

Today, a view field pushes its changes to the UI, and a signal such as `value_changed` reports
the user's changes to the code. To update a table when a filter changes, the app connects a
callback to each signal by hand. A field set by code emits nothing, and a plain field such as a
loaded frame has no signal at all.

The proposed design is a `@reactive` method on a view. ComposeUI runs it once, and records each
view field that it reads. When one of those fields changes, by the user or by code, the method
runs again. Its body is ordinary ComposeUI code: it reads fields and sets fields.

```python
@reactive
def show_base(self) -> None:
    frame = of_base(self.pickups, self.base.value)  # reads pickups and base.value
    self.table.source = DataFrameSource(frame)
    self.chart.series = pickups_by_hour(frame)
```

- **No declared inputs.** The reads are the inputs, so no field is named by a string, and type
  checkers see plain attribute access. Each run records its reads again, so a branch that is
  not taken is not an input.
- **Slow work stays in jobs.** A reactive method reads its inputs on the main thread, then calls
  a new `Task.start_latest(...)` with them. It takes the task's typed arguments, as `start`
  does, waits a debounce delay, and drops a result whose inputs are out of date. Today `start`
  returns `False` while a task runs, and nothing replaces obsolete work.
- **Batches and loops.** One event that changes several fields runs each method once, after
  the event. A method that sets a field that it reads is refused.
- **No leaks.** The table of readers holds views by weak key and methods by `weakref.WeakMethod`,
  as `Signal` holds its callbacks. A `ContextVar` marks the method being tracked, because web
  sessions and jobs run concurrently. A web session clears its readers when it ends; weak
  references are the safety net, not the mechanism.
- **Nothing to save.** Reactive methods are code. A study saves the fields; opening it runs the
  methods that read them.
- **Visible inputs.** A debug helper lists the fields that each method read in its last run.

The fallback, if tracking reads proves too slow or too surprising, is explicit inputs: typed
signals passed to a `react(method, *signals)` call. It lists each input twice and needs a
change signal for each field, so it is the second choice.

**Adopt it only if it really improves ComposeUI.** Prototype it in M0 on the Uber pickups
examples, beside the hand-written version, and add it to the public API only when:

1. The app is clearly shorter and easier to follow: fewer callbacks and no wiring code.
2. Every type checker of the repository passes on the app, without `Any` or strings.
3. Field reads and writes stay within a budget measured against 0.1.0.
4. A test proves that a slow, obsolete query never overwrites the latest result.
5. A test ends a web session, collects garbage, and finds no reader left for its views.
6. A developer who did not write it can predict when each method runs.

If the prototype fails these, keep the existing signals and `Task`, add only
`Task.start_latest`, and drop `@reactive`. Deliver the adopted part in M1.

**Done when:** one filter updates a table and a chart, other panels stay unchanged, and a slow,
obsolete query cannot overwrite the latest result. Dashboard helpers (N01) and view classes use
the same mechanism.

### N03 — Dataframe types and editing

`DataFrameSource`, `series_of` and `points_of` give a read-only path through Narwhals. In
M1, define the behavior for nulls, dates and time zones, categorical and numeric types,
and column metadata. Test it on each supported dataframe library, lazy frames included.

`DataFrameSource` stays read-only until T02. A lazy frame needs an `id_column`; an eager frame
can use row positions. Specify row identity when a frame is replaced, filtered or edited.
Refuse ambiguous IDs, or document that they must be unique. Add typed edits through T02, and
say which operations change, copy or load the data, and how the app saves the result. Keep the
library-dependent search and regex behavior documented.

Sorting and filtering stay in the dataframe library, but the view still holds every selected
row ID. Reading cells in windows does not bound that memory. Measure this index, and the
collection done by the chart and map helpers, on large and lazy inputs. Then decide if a paged
ordering protocol is needed. Do not promise out-of-core or zero-copy behavior only because a
frame is lazy.

**Done when:** fixtures cover the supported types and libraries, selection and edits keep each
record's identity, and memory budgets cover both the visible cells and the order.

### N04 — Existing figures

Show Plotly figures in M1, Matplotlib figures in M2, and Altair (Vega-Lite) in M3, so an app
reuses the analysis's own code. `ChartView`, `Series.bars` and `series_of` already work, and
Matplotlib draws report images, but no adapter takes an existing figure yet. Send the supported
clicks and selections as typed signals. Define updates, export, and themes.

Publish what each adapter supports on each backend. The web can be richer than the terminal.
The desktop can use a native renderer, an image, or an optional web view. Each choice states
its dependency and its fallback. Package the assets, and keep within the web backend's
content security policy.

An adapter does not complete a `ChartView` entry (C items): that entry still needs its own
API and backend behavior.

**Done when:** a dataframe filter updates an existing figure, and a selection in a chart
filters a linked table where the backend supports it.

### N05 — Caches and shared resources

A `Task` keeps its own last result; it is not a shared cache. Add caches for expensive
calculations and queries, with explicit keys, expiry, invalidation, a size limit, and a scope
(session or app). Define if a cached mutable result is shared or copied. Private data must not
enter a cache that other sessions share.

Add managed resources for connection pools, read-only datasets, and ML models. Keep them apart
from each session's model. Define thread safety, cleanup, and what happens on reload and
shutdown. Start in M1; finish the deployment behavior in M4.

**Done when:** sessions share a resource on purpose while their views and private results stay
apart, and tests cover the cleanup.

### N06 — Data connections and secrets

Start from the SQLite model and the CSV import from URLs. Add recipes or adapters for
SQLAlchemy databases and HTTP APIs, starting with a small maintained set. Read secrets from the
environment or from a local development file. Handle timeouts, cleanup, and clear query errors.

Document transactions and writes that the app owns. Use N02 and N05 so that a slow connection
needs no hand-written thread code. Deliver in M2.

**Done when:** a documented example reads a SQL query into a table and a chart, refreshes it,
and handles a failed query without losing the user's work.

### N07 — Uploads and exports

CSV import, jobs with progress and cancellation, and streamed CSV export of a table already
exist. Build on them.

Add configurable upload limits, the lifecycle of temporary files, Parquet import, and tested
cancellation of long imports and exports. Keep study files, data uploads, and exported results
apart in the UI and the API. An app that accepts URLs from users defines the allowed schemes,
hosts, and redirects before it passes them to the import.

The web's 5 MiB limit (`MAX_FILE_SIZE`) is a default, not a requirement for data apps. Make it
configurable and test apps near it. Deliver the API in M1 and the deployment settings in M4.

**Done when:** a user imports a realistic dataset, inspects it, and exports filtered results,
without needless copies of the file or files shared across sessions.

### N08 — Users and access

The nginx recipe offers HTTP Basic Auth for the whole app. Add login through an identity
provider, such as OIDC, and an authorization hook for pages, data operations, downloads, and
actions. Authentication says who the user is; the app decides what that user can access.

Decide if state belongs to a browser, a tab, a user, or a named workspace. A browser cookie
suits some apps; apps that open independent tabs need another option. Specify login, logout,
expiry and restoration. Deliver in M4 with L01.

The page forbids framing (`frame-ancestors 'none'`), so no app shows inside a wiki or a portal.
Keep that default, and add an explicit setting that names the sites allowed to frame the app.

**Done when:** the server's endpoints, not only the navigation, enforce access; two users
cannot read each other's private state; and tests cover tabs for each supported mode.

### N09 — Deployment and operations

The deployment guide covers one Uvicorn process behind nginx, TLS, proxy headers, request
limits, and Basic Auth. Add a maintained container example, health checks, structured logs,
and startup and shutdown procedures. Do this with L01, N05, N07 and N08, and test a fresh
deployment and its recovery in M4.

`--reload` already keeps sessions in a scratch directory during development. A deployed app
still loses them on restart: they live in one process's memory, signed by a key that lasts as
long as the server.

For L01, save each session's app and study state, and rebuild its views, signals and renderers
on restore. Do not store live renderers or locks in Redis. Define the supported worker
topology: sticky sessions with durable recovery, or an explicit distributed design. A shared
store alone does not make concurrent workers safe. Widget IDs come from `id(view)`, so a
restore must also refresh the page and refuse events for widgets that no longer exist.

**Done when:** the reference app survives its documented restart, the worker topology passes
consistency tests, storage failures can be recovered, and operators can diagnose failed
requests and jobs. Document what happens to running jobs on a restart; do not imply that they
resume.

### N10 — Extensions

Turn the renderer and backend extension points into a public contract: registration and
discovery, package names, compatibility, optional dependencies, capabilities, assets, event
serialization, cleanup, and test fixtures.

Keep the core widgets' parity apart from what an extension supports. Show a missing capability
clearly; never drop an essential control silently. Design the contract in M0, use it for N04,
and make it stable in M5.

**Done when:** a separate package adds a widget or an adapter, declares its backends, and passes
the contract tests without patching ComposeUI.

### N11 — Getting started and testing

Build on the PyPI install, the widget catalog and API reference, the coding-agent skill, and
the [app-testing guide](docs/user-guide/testing.md). The guide already tests apps without a
window: `Application`, `ModelApplication`, signals, jobs, models, and saving and opening a
study.

Add a `composeui run app.py` command in M1, with reload on: the first thing a new user types.
It runs a file that builds a main view, without a `run(...)` call or `python -m`. Add an app
template, and a quick-dashboard tutorial beside the structured-app path. Add examples that
debug signals and reactive methods, and fixtures where tests repeat their setup. List the
optional adapters and their backends in the catalog. Cover keyboard navigation, focus, labels
and errors in the reference apps. Work on it from M1 to M5; keep the public imports and the
checks that run the docs' examples.

**Done when:** a new developer builds, tests and packages a documented example with the public
API, and the docs say which features differ between backends.

### N12 — Examples and adoption

In M0, grow three reference apps from the existing examples, and add a repeatable benchmark.
Publish each result with its versions, hardware, data and settings. By M5 and M6, turn the
examples guide into a gallery, with how to contribute and what each example supports. Keep the
changelog and releases current as features land.

Choose new integrations from what real users need. N15 gives one-command deployment to
existing platforms early. Consider a managed hosting service, or a hosting partner, in M6 only
once self-hosting and upgrades are reliable. Its cost and its owner
need an explicit decision.

**Done when:** outside developers reproduce the examples, publish apps, and contribute an
extension without private APIs or maintainer-only instructions.

### N13 — Dashboard widgets

The widget backlog (W items) comes from a scientific desktop app. Dashboards need other common
widgets first:

- **An image**, from a file, bytes, or a Matplotlib figure.
- **A text area** of several lines.
- **A download button** for any file or bytes that the app makes. Today only chart images and
  table CSV exports download.
- **A toggle**, a **range slider**, and a **date range** input.
- **A toast** and a **spinner** for short feedback.
- **JSON and code display**, read-only.

W06 (a combobox of several values) belongs to this group too. Deliver in M1, with the same rules
as the W items.

**Done when:** the data explorer uses only built-in widgets, on the three backends.

### N14 — Links that keep the state

A page has an address, but the view state is not in it. Let an app mark the fields that a link
keeps, such as filters and a selected tab. The web writes them in the query string as they
change, and reads them when a page opens. A link holds no private data and no study data:
document what an app may put in it. Deliver in M2.

**Done when:** a user copies the link of a filtered dashboard, and another user opens the same
view.

### N15 — One-command deployment

N09 covers operations for a team. Before that, give each app a short path to a public or
internal URL: a maintained Dockerfile, and tested recipes for common platforms, such as Hugging
Face Spaces, Render and Fly.io. Each recipe states its limits: one process, sessions in memory,
and the upload limit. Deliver in M2.

**Done when:** the reference dashboard deploys from its repository with one documented command
or button per platform, and CI builds the container.

### N16 — Notebooks

Many analyses start in Jupyter. Show a view, or a small app, in a notebook cell, so the
analysis and the app share their code from the first day. Define how a cell's view connects to
the kernel, what the backends show, and what state a notebook keeps. Start with a prototype in
M2; keep it only if it stays small.

**Done when:** a notebook shows a filter, a table and a chart that update together, and the same
code runs as an app with `composeui run`.

## Widgets, tables and charts

These entries come from a scientific app's GUI: a study tree beside a result's tabs of tables
and charts, and wizards to set up each analysis. N13 lists the widgets that dashboards need
first.

### Widgets

| ID | Deliverable | Milestone |
| --- | --- | --- |
| W01 | Context menus on tree nodes and table rows: icons, disabled actions, separators (Rename, Export, Remove; Add row, Remove rows) | M3 |
| W02 | A plain list to pick one or several strings, such as a result's "Outputs"; a checkable variant with a check-all box in its header | M3 |
| W03 | A color legend beside a table whose cells are colored by range (`CellStyle`), such as a correlation matrix: each range's color and bounds | M3 |
| W04 | A wizard: steps with Back, Continue/Finish, Cancel and Help, each step validated before the next, an optional image | M3 |
| W05 | Tabs that the user adds and closes: a × on each tab and a + tab after them | M3 |
| W06 | A combobox of several values: checkboxes in its list, the selected values shown below it | M1, with N13 |
| W07 | A button with a menu ("Add ▾", adding one of several kinds) | M3 |
| W08 | An optional field enabled by a checkbox beside it (a Monte Carlo stopping criterion); a duration field in days, hours, minutes and seconds | M3 |
| W09 | A code editor with line numbers and Python syntax highlighting | M3 |
| W10 | A workflow diagram: boxes joined by arrows, enabled or not, a click starting a step | M3 |
| W11 | A Python console, for apps that offer scripting | M3, enabled by the app only |

**Done when:** each widget has typed state and signals, validation where needed, keyboard
behavior, translations, documentation, and tests of the real widget on the three backends. On
the web, the element that sent a request is never swapped back, changes elsewhere arrive as
OOB updates, and fields keep their `aria-*` links to their label and error. New CSS classes
need `make css`, which a test checks. A saved state keeps the user's choices, never renderers
or callbacks.

Editing code (W09) and running it (W11) are separate. For W11, document which process runs
the code and what it can access. An unrestricted console belongs only in a trusted context.
Running code on a public web app needs its own isolation design, and is never on by default.

### Tables

| ID | Deliverable | Milestone |
| --- | --- | --- |
| T01 | A NumPy source with vectorized sorting and filtering, and row identity | When an app has arrays and no dataframe library; reuse the source contract tests |
| T02 | Editing a source: optional `update`, `insert` and `remove`, typed edits, refusal messages, and writes owned by the app | M1, as an editable grid in the data explorer |
| T03 | The user moves rows up and down in `TableView` and `SourceTableView` on each backend; drag and drop on Qt; a lasting order in SQLite | M3 |

Sorting and filtering stay in the source, never in a renderer. The view holds the ordered row
IDs, the selection, and the format settings, and reads cells in windows. A study saves the sort,
the filters and the selected IDs, and reconnects the source when it opens. `DataFrameSource`
covers pandas, Polars and Arrow: add a library-specific source only with evidence that it is
needed.

For T02, parse an edit into the column's type with `CONVERTER`, and refuse it with
`RefusedError`, as `RecordTableView` does. A `SqliteSource` calls the app's own queries, so
that `refusals` gives the user its message.

For T03, reuse [composeui-table](https://github.com/ehmoussi/composeui-table) after checking
it:

- `core/ordering.py`: a table of positions, a trigger that puts each new row last, and one
  window-function query that moves rows. Run it through `SqliteModel.connection()` without its
  own commits, and make `get_row_ids(positions)` keep the order of the positions it gets.
- `ListTableModel.move_rows`: the destination shifts by the rows taken from above it.
- On Qt, `_pack_positions` and `dropMimeData`: each run of rows moves with one `beginMoveRows`.

**Done when:** sorting and filtering keep the selection, an edit reaches the right record after
a move, an unsupported operation fails clearly, and large exports stay chunked. NumPy row
indices can be IDs for immutable arrays, but edits and moves must not change a record's
identity.

### Charts

| ID | Deliverable | Milestone |
| --- | --- | --- |
| C01 | A date and time x axis: ticks and hovered values as dates in the main view's language | M2 |
| C02 | A timeline (Gantt) chart, `ChartKind.TIMELINE`: a row per category, a bar per interval colored by series, hover details | M3, after C01 |
| C03 | Web: full resolution on zoom | M3, when a reference app needs it |
| C04 | Axis ranges set by the app (`x_min`, `x_max`, …), and the orientation of category labels | M2 |
| C05 | Error bars, such as a Sobol index's confidence interval or a quantile's on a CDF | M3 |
| C06 | Marker shapes (+, square, circle) and point labels, such as variable names on a Morris plot | M3 |
| C07 | Scatter points over bar categories, each series shifted (first-order and total indices per input) | M3 |
| C08 | Histograms over numeric bins, with an optional density curve | M3 |
| C09 | Box plots with whiskers and outliers | M3 |
| C10 | Pie charts (importance factors) | M3 |
| C11 | Contours with a color scale and a color bar, such as a copula's density | M3 |
| C12 | Parallel coordinates: an axis per variable, a line per sample, brushing an axis' range highlights its lines | M3 |
| C13 | A scatter plot matrix: histograms on the diagonal, cells colored by correlation, zoom on a cell | M3 |
| C14 | Draggable reference lines that emit their new value, such as Morris' "no effect boundary" | M3 |

**Done when:** each chart specifies its data, selection events, zoom, theme and report export.
Document what the terminal cannot do instead of promising pointer interactions there. Share the
data processing between backends where possible.

For C03, uPlot's `setScale` hook (debounced) requests `GET /widget/{id}?x_min=…&x_max=…`. The
renderer answers that range's points as JSON, thinned to `CHART_MAX_POINTS`, and the page sets
them without rescaling. This fits the existing fragment route. Measure the response size and the
detail recovered after a zoom.

### The SQLite model

`SqliteModel` is complete for now: tables and SQL, transactions, typed rows, change signals,
study files with migrations, a model per web session, and writes from jobs whose signals reach
the main thread. Do not rebuild it. New work comes from T02, T03, N06 and L01.

## Later and conditional

| ID | Deliverable | When |
| --- | --- | --- |
| A02 | A tested packaging recipe for Qt (PyInstaller or briefcase) and for Textual (a script or a console entry point) | M5 |
| L01 | Web sessions that survive a restart: a lasting store, a fixed signing key, and a multi-process design (see N09) | M4 |
| L02 | Type-check `static/page.js` with JSDoc, `// @ts-check` and `tsc --noEmit --allowJs` in CI | When the file passes about 2,000 lines, or several people edit it |
| L03 | Raw HTML in Markdown, cleaned by `nh3` and an allowlist of tags | When a real document needs it |
| L04 | Textual: reload in place, keeping scroll and focus | M5 |
| L05 | Qt: a reload that keeps the widgets' own state, frees old classes, and defines what running threads do | M5 |
| L06 | PyQt6 as a second Qt binding, with a `pyqt6` extra | When an app asks for it |

For A02, test the Qt package on a clean machine. An app with a map needs `map.qml`, the Qt
Location and Qt Positioning QML modules, and the location plugins. Document each recipe in
"Running the app" once it works. The web recipe exists; its remaining work is N09.

For L02, `page.js` has 1,175 lines today. The check brings Node into CI, and it cannot check
the `data-*` attributes and custom events that `page.js` shares with `webrenderer.py`; the
browser tests cover those. Start with uPlot's chart options.

For L03, the web shows raw HTML in a `MarkdownView` as text (`{"html": False}`), so a help page
cannot use `<details>` or `<kbd>`. Clean markdown-it's output with `nh3`, added to the `web`
extra. No view shows unescaped HTML today.

For L04, run `rerun_program` in the Textual app, as `qtcore` does, and mount the new main view
in the running `App`.

For L05, a reload loses the widgets' own state (a scroll position, a column's width, the
focus). The `cattrs` converter keeps the old classes' hooks, so memory grows with each reload.
Threads that the app started keep running the old code. Test repeated reloads, and define if
old work is cancelled, completed or ignored.

For L06, `qtpy` already accepts `QT_API=pyqt6`. With PyQt6 6.11, the Qt tests show:

- Maps cannot load: PyQt6's wheels lack Qt Location, so maps stay PySide6-only, and "Maps"
  must say so.
- The message, confirmation and form dialogs, and a dialog shown again at once, time out or
  answer wrongly.
- A click on a radio button does not reach its view.

Then run the Qt tests on PyQt6 in CI, and mypy on both bindings (`always_true` selects PySide6
today). The extra states that PyQt6 is GPL or commercial, where PySide6 is LGPL. Do not add Qt 5
bindings (PyQt5, PySide2): Qt 5 is past its end of life.

## Reference apps

Three apps test each milestone against real use.

| App | Workflow | It tests |
| --- | --- | --- |
| Data explorer | The Uber examples, plus uploads, Parquet, an editable grid, existing figures, export, shareable links, and a one-command deployment | Authoring effort, reactive methods, adapters, dashboard widgets, charts, caches, files, maps, and deployment |
| Scientific workbench | A study tree, a wizard, editable parameters, a background analysis, result tables and charts, save and open, a report | W, T and C items, jobs, the model, and the three backends |
| Shared internal tool | Login, permitted data, record editing, a job, pages, recovery after a restart | Identity, authorization, isolation, sessions, and deployment |

Start the workbench and the shared tool from `pipecatalogue.py` and `pipesweep.py`. Test maps
on Qt and the web, and the rest also on Textual.

Measure cold start, first useful render, filter and sort latency, chart update latency,
response size, memory per session and for shared resources, throughput with concurrent
sessions, and cleanup after a session closes. Use a small dataset, the million-row SQLite table
of `largetable.py`, and an uploaded dataset within the limits.

Set numeric budgets after the M0 baseline, before judging the work against them. Keep
regression thresholds in CI where results are reproducible. Report differences in workloads
when comparing with other frameworks, rather than crediting every gap to the execution model.

The stable release (M5) builds on the public API, the changelog, Semantic Versioning and the
release workflow. It adds a deprecation policy, maintained packaging recipes, and fixtures that
open studies and sessions from older versions through `state_version` and `migrate_state`, not
a second migration mechanism. Check clean installs on each supported Python and extra. Release
an adapter on its own when its dependencies call for it.

## Related documentation

- [Project overview and installation](README.md)
- [Widget catalog](docs/widgets.md)
- [Core concepts](docs/user-guide/core-concepts.md)
- [Tables](docs/user-guide/tables.md)
- [Charts](docs/user-guide/charts.md)
- [Maps](docs/user-guide/maps.md)
- [CSV imports](docs/user-guide/csv-import.md)
- [A SQLite model](docs/user-guide/sqlite-model.md)
- [Background jobs and tasks](docs/user-guide/threads.md)
- [Testing applications](docs/user-guide/testing.md)
- [Running apps and serving the web backend](docs/user-guide/running-the-app.md)
- [Release history](CHANGELOG.md)
- [Architecture and development](docs/technical-guide.md)

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
- **A large table's frame.** `WebSourceTableRenderer` draws a window of rows between two
  filler rows (`style` heights, which the policy allows) that give the scroll bar every
  row's height. `page.js` posts the first row shown once the scroll stops outside the
  window, and only the `<tbody>` comes back (in a `<template>`, as a table's parts), so
  the scroll position stays. Browsers cap an element's height: past
  `SOURCE_TABLE_SCROLLED_ROWS`, a filler's row height stands for more than one row. The
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
- **Order.** The server handles a page's posts in the order the page sends them
  (`order.py`): a field's value, posted as a click on a button blurs the field, can else
  reach it after the click. `page.js` sets a page id and a number on each post in
  `htmx:beforeSend`, and the routes await its turn on the event loop, no thread held, at
  most `ORDER_TIMEOUT` (2 s) for a post that never comes. Scroll windows
  (`hx-sync="this:replace"`) carry none: one replaced may never be sent. A session keeps
  the order of `MAX_PAGES` (32) pages. Save's form (`cui-save`), submitted without htmx,
  carries no header: `page.js` sets its hidden `page` and `post` fields as it is
  submitted. Holding the posts back in `page.js` fails instead:
  htmx drops a held request whose element a swap has since replaced, and gives no promise
  to wait on for a trigger's request.
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
