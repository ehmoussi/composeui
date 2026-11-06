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
- The response time and memory of the data explorer, and of the other reference apps once they
  are measured (see "Reference apps").

## How to read this roadmap

- **This file holds the work that is left.** Delete an entry when it lands. The code, the
  docs, `CHANGELOG.md` and `git log` record what is done.
- **Each entry has an identifier.** N is for data apps, W for widgets, T for tables, C for
  charts, A for adoption, L for later work, and P for known problems. Keep an identifier until
  its work is done or explicitly deferred.
- **Milestones give the order, not dates.** Choose dates only after estimating the work.
- **Each entry says when it is done.** A milestone is done when its acceptance examples work,
  its tests pass, its behavior is documented, and its limitations are recorded.

## Where ComposeUI stands

Release 0.3.0 (2 November 2026) is on PyPI. The README still calls the API pre-alpha: a
stable API is the goal of M5. The [widget catalog](docs/widgets.md) lists every widget and its
backends, and the [user guide](docs/user-guide.md) shows how to use them.

| Area | Already there |
| --- | --- |
| Core | Typed `attrs` views, reactive attributes, reactive methods (`@reactive`), signals, callback injection, lazy backend selection, and the backend's capabilities |
| Backends | Qt, Textual, and the web (Starlette and htmx); maps on Qt and the web only. The web sends only the shown page of a router and the shown tab of a tab view; Qt builds each page and tab the first time it shows |
| Forms and layout | Inputs, validation, buttons, progress, metrics, expanders, trees, Markdown, consoles, pages, tabs, splitters, sidebars, view lists, menus, toolbars, and typed form and content dialogs, with buttons and checks of their own |
| Files and paths | File, folder and save path fields and table cells, files picked on the server (`server_roots`), paths relative to the study (`base_folder`), a path cell by the row's kind (`path_by`), and `MainView.write_file`, which asks before it replaces a file |
| Tables | Editable tables, typed record tables, sorting, filtering, cell widgets and styles, header groups, and row headers |
| Dashboards | `DashboardView`, `bar_chart`, `Task.show_state`, and `CheckBoxMixin.shows` (the first part of N01) |
| Large tables | `SourceTableView` on `ListSource`, `SqliteSource` and `DataFrameSource`: rows read as they show, selection by row ID, and CSV export |
| Dataframes | The `dataframe` extra: pandas, Polars, PyArrow and lazy frames through Narwhals, with `series_of` and `points_of` |
| CSV import | `CSVSqliteTable`: typed columns, column mapping, indexes, dialect detection, batches in a transaction, gzip, and URLs |
| Charts and maps | Line, step, scatter and bar charts, log axes, reference lines, report images, and `MapView` point overlays |
| Models and studies | `SqliteModel`: transactions, typed rows, change signals, study files with migrations, `MainView.state_version` / `migrate_state`, and `MainView.loaded` to give again what a study doesn't hold |
| Background work | Jobs with typed progress and cancellation, and reusable `Task` objects with their result, error, the controls that follow them, and runs that follow the latest input (`start_latest`) |
| Deployment | One Uvicorn process behind nginx: TLS, proxy headers, request limits, and optional HTTP Basic Auth |
| Tooling | Tests on each backend and in a browser, an app-testing guide, several type checkers, CI on Python 3.9 to 3.14 and three OSes, a coding-agent skill, the `composeui run` command, and benchmarks of the Uber examples and of web sessions ([`benchmarks/`](benchmarks/README.md)) |
| Releases | PyPI, a changelog, Semantic Versioning, a public API per module, and automated publishing |

The [Uber pickups example](src/examples/uberpickups.py) and its
[dataframe version](src/examples/uberpickupsframe.py) are the starting point for dashboards.
They load a CSV in a task, and a filter updates a table, a bar chart and a map.

What is missing is mostly the path from analysis to app: short authoring helpers, common
dashboard widgets (an image, a download button, a toggle, a range slider), adapters for plotting
libraries, caches, editable sources, links that keep the app's state, one-command deployment, user
identity, and sessions that survive a restart.

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
7. **Presentation by role, not by style.** An app says what a text or a field is: a title, a
   caption, a short field. Each backend maps the role to its own look. Do not add colors, fonts,
   pixel sizes or CSS classes to the core views.

The registry lets a backend leave out a renderer: the view then renders as `None`.
`tests/test_renderer_registry.py` requires the same keys on the three backends, maps aside.
Change that contract, and its tests, explicitly for extensions.

## Milestones

| Milestone | The developer can | Main work | Done when |
| --- | --- | --- | --- |
| M0 — Baseline | Compare future work with 0.3.0 | Specify the other two reference apps; prototype helpers; specify capabilities and data ownership | Three reference apps are specified and used to review the proposed APIs, and the data explorer is measured |
| M1 — First dashboard | Build a dashboard in minutes from a CSV or a dataframe | N01, N04 (Plotly), N05 (caches), N07 (uploads), N13, W06, T02 and N03 (an editable grid) | The CSV dashboard uses ordinary ComposeUI objects, stays responsive during queries, and meets the M0 targets |
| M2 — Shared dashboards | Share a dashboard and reuse more existing code | N14, N15, N04 (Matplotlib), N06, N16, C01, C04 | A dashboard deploys in one command, its links keep its state, and it reads a SQL database |
| M3 — Scientific workflows | Configure, compute, inspect and export a study | W01–W05, W07–W15, T03, the other C items, N04 (Altair) | The scientific workbench covers each W, T and C item, or records why it waits |
| M4 — Shared apps | Deploy an app for a team | L01, N08, N09, end of N05 and N07 | Restart, isolation, access control and worker-topology tests pass |
| M5 — Stable release | Depend on the API and extend it | A02, N10, N11, L04, L05, the stability contract | A stable API with deprecations, compatibility fixtures, clean installs, and an extension packaged on its own |
| M6 — Community | Find a working example for their case | N12: gallery, recipes, more adapters, hosting | Outside developers ship apps and extensions without changes to ComposeUI's internals |

M1 and M2 come first: they give the shortest path from analysis to a shared app. M3 and M4 can
then progress in parallel. Each milestone ships as a 0.x release that users can try, and its
changelog says what they can now build. Between two milestones, a 0.x release ships the
finished entries of the backlog and the fixes, and its changelog does not claim a milestone. A
conditional item blocks no milestone until its condition is met.

## Next step

Build one thin slice from end to end before the full catalog:

1. **Measure.** The [Uber benchmark](benchmarks/README.md) measures 0.3.0 and main: loading,
   hour moves, sorting and filtering, row-ID memory, web responses, and cleanup on the core. The
   [web sessions benchmark](benchmarks/README.md#the-web-sessions-benchmark) measures the memory
   and the cleanup of each session, and concurrent sessions. Next, specify the scientific and
   shared-tool workflows.
2. **Shorten.** Add a Plotly adapter with its backend capabilities (N04), then dashboard
   helpers that build the existing views, sources and tasks (N01).
3. **Load and export.** Add configurable uploads and filtered export to the data explorer
   (N07), and the dashboard widgets that it needs (N13).
4. **Release.** Publish the slice as a 0.x version. Compare authoring effort, response time,
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
  `child(...)` saves no code. Keep a helper when two dashboards repeat the same code. Build
  them on reactive methods, as `shows` and `show_state` are.

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

Document transactions and writes that the app owns. Use reactive methods, `start_latest` and
N05 so that a slow connection needs no hand-written thread code. Deliver in M2.

**Done when:** a documented example reads a SQL query into a table and a chart, refreshes it,
and handles a failed query without losing the user's work.

### N07 — Uploads and exports

CSV import, jobs with progress and cancellation, and streamed CSV export of a table already
exist. Build on them.

Add configurable upload limits, the lifecycle of temporary files, Parquet import, and tested
cancellation of long imports and exports. Keep study files, data uploads, and exported results
apart in the UI and the API. An app that accepts URLs from users defines the allowed schemes,
hosts, and redirects before it passes them to the import.

On the web, a file path field without `server_roots` uploads the file, and gives the path of a
copy in the session. Give an uploaded file instead: its name, its size, its type, and a
temporary file whose lifecycle the API states. A file picked on the server (`server_roots`) is
not an upload: it stays where it is.

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

Add an app template, and a quick-dashboard tutorial beside the structured-app path. Add examples
that debug signals and reactive methods, and fixtures where tests repeat their setup. List the
optional adapters and their backends in the catalog. Cover keyboard navigation, focus, labels and
errors in the reference apps. Work on it from M1 to M5; keep the public imports and the checks that
run the docs' examples.

Add helpers for testing an app as it renders, not only its views. A scientific app's dialog
had a table with its rows in Python, but the rendered dialog did not show the table: a test of
the views passed. The helpers:

- find a control by its role and its accessible name;
- check that a control is rendered, visible, and enabled in effect, also under a disabled
  parent;
- select rows, open pickers, and accept or cancel dialogs;
- run one test case on Qt, Textual and the web.

Add tests of real interaction with the backend for focus and the keyboard, where practical.

**Done when:** a new developer builds, tests and packages a documented example with the public
API, and the docs say which features differ between backends. A test fails when a table with
rows is missing from its rendered dialog, and finds a control under a disabled parent not
interactive.

### N12 — Examples and adoption

In M0, grow three reference apps from the existing examples. `benchmarks/uber.py` measures the Uber
examples, the start of the data explorer. Add a benchmark for another reference app when work on its
speed needs one. Publish each result with its versions, hardware, data and settings, as
`benchmarks/README.md` does. By M5 and M6, turn the examples guide into a gallery, with how to
contribute and what each example supports. Keep the changelog and releases current as features land.

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
| W12 | Text roles for `LabelView`: title, subtitle, body, caption and muted text, so that a page has headings and descriptions without a `MarkdownView` | M3 |
| W13 | Sizes in forms: a field's width (short, medium, the whole row), and a compact density for the main view that reduces the gaps and the padding | M3 |
| W14 | The router's navigation: in a toolbar or in a list on the window's side, pages grouped in sections, and a count or a badge on a page's entry | M3 |
| W15 | A list row: a primary and a secondary text, an icon, a badge, actions at its end, and a signal when the user activates it, such as a list of recent files | M3, with W01 and W02 |
| W16 | A command that a button, a menu entry and a toolbar entry share: its text, its enabled state, and what it runs. `Task.cancel_with` does it only to cancel a task | M3 |

**Done when:** each widget has typed state and signals, validation where needed, keyboard
behavior, translations, documentation, and tests of the real widget on the three backends. On
the web, the element that sent a request is never swapped back, changes elsewhere arrive as
OOB updates, and fields keep their `aria-*` links to their label and error. New CSS classes
need `make css`, which a test checks. A saved state keeps the user's choices, never renderers
or callbacks.

W12 to W15 are presentation work. They follow principle 7: the core view holds a role or a
size from an enum, and each backend maps it. Qt uses fonts, size policies and margins, Textual
bold and dim text and widths in cells, and the web daisyUI classes. A backend that cannot show a
role shows the default look. For W14, keep the toolbar as the default, and keep `Router`'s
signals and routes: a side list changes only how the entries show. Build W15 on `ListView`, so
that a row keeps its view while its record stays.

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

## Known problems

### P05 — SQLite sessions slow down when they overlap

In the SQLite Uber example on the web, a load takes 9.5 s with one session, 206 s with 4 sessions
at once, and 1,083 s with 8. An hour move takes 0.37 s, 3.9 s and 38 s. Moves stay slow after the
loads are over. Each client moves the hour without a pause, so this is a worst case.

The cause is the hand-over of the GIL between CPUs, for nearly each row
([the checks](benchmarks/README.md#why-sqlite-sessions-slow-down)). Four threads take 58 s for a
load of 300,000 rows on all CPUs, 10.4 s on one CPU, and four processes take 3.0 s. These results
come from WSL2: measure a native Linux server first, as it can pay less for each hand-over.

The options, from the largest gain for this example to the largest change:

- **Share the data.** With N05, sessions that read the same file load it once.
- **Insert many rows per statement.** `CSVSqliteTable` would need fewer hand-overs per row. This
  is not measured, and it does not help queries.
- **Run several processes.** L01 and N09 remove the contention between sessions in different
  processes.
- **Keep the server on one CPU.** `taskset` works today, and gives 36 s and 0.67 s with 4 sessions.
  It also limits the threads of Polars. Document it only after a measure on native Linux.

**Done when:** a budget for concurrent sessions is set, and `benchmarks/sessions.py` shows that 4
SQLite sessions meet it.

### P06 — A process that exits during a write may crash

`SqliteModel.close` leaves the connection open until a write ends, so a session's end is safe. The
model's finalizer still closes the connection when the process exits, while a job's daemon thread
can be writing. The exit can then crash, and leave the temporary database behind. This case is not
tested: it comes from reading the code. It would lose no other session, as the process is already
ending.

**Done when:** a test exits a process during a write, on Qt and on the web server, and the exit is
clean and leaves no file.

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
| L07 | Optional filesystem adapters: paths between Windows and WSL, and opening a folder on the app's host | When an app asks for it |
| L08 | Recent folders in the picker of the server's files (`server_roots`) | When an app asks for it |
| L09 | Import a CSV file into SQLite through Polars or PyArrow, which read the Uber CSV in 0.15 to 0.4 s; the typed import takes about 10 s, with its row checks in Python | When a data app needs a faster import, with its own rules for checks and error messages |

For A02, test the Qt package on a clean machine. An app with a map needs `map.qml`, the Qt
Location and Qt Positioning QML modules, and the location plugins. Document each recipe in
"Running the app" once it works. The web recipe exists; its remaining work is N09.

For L02, `page.js` has 1,345 lines today. The check brings Node into CI, and it cannot check
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

For L07, a scientific app that runs in WSL does this work itself today:

- it converts a Windows drive path with `wslpath`, and handles WSL UNC paths and the
  distribution's name;
- it refuses the `C:\fakepath\...` value that a browser gives for a file;
- it opens a result folder in the Windows Explorer.

An optional location service would share this work, with handlers that an app plugs in to
convert a path and to open a folder. It tells the app's host from the browser's computer, and
assumes no mount layout, such as `/mnt/c`. Opening a folder on the host is not opening it on a
remote user's computer: give a remote web user another way, such as copying the server's path,
or downloading the results that the user may read. Converting a path transfers no file, and
gives no access to another computer's files. Done when an adapter converts a supported Windows
path in WSL and opens a folder on the host, and a remote web user gets the other way.

For L08, the web's picker of the server's files has no recent folders, so a user goes to the
same study folder again and again. Keep a short history, within the current `server_roots`,
and state who owns it: the web session, or the local user. A folder outside the current roots
never shows, even if a root that held it was allowed before. Done when a test changes the roots
and finds that the history shows no folder outside them.

## Reference apps

Three apps test each milestone against real use.

| App | Workflow | It tests |
| --- | --- | --- |
| Data explorer | The Uber examples, plus uploads, Parquet, an editable grid, existing figures, export, shareable links, and a one-command deployment | Authoring effort, reactive methods, adapters, dashboard widgets, charts, caches, files, maps, and deployment |
| Scientific workbench | A study tree, a wizard, editable parameters, a background analysis, result tables and charts, save and open, a report | W, T and C items, jobs, the model, and the three backends |
| Shared internal tool | Login, permitted data, record editing, a job, pages, recovery after a restart | Identity, authorization, isolation, sessions, and deployment |

Start the workbench and the shared tool from `pipecatalogue.py` and `pipesweep.py`. Test maps
on Qt and the web, and the rest also on Textual.

When an app is measured, measure cold start, first useful render, filter and sort latency, chart
update latency, response size, memory per session and for shared resources, throughput with
concurrent sessions, and cleanup after a session closes. Use a small dataset, the million-row SQLite
table of `largetable.py`, and an uploaded dataset within the limits.

Set numeric budgets after the M0 baseline, before judging the work against them. The first
budget: an hour move in the SQLite Uber example takes less than 500 ms on the web, as
`benchmarks/uber.py` measures it, with the 200 ms debounce of the map's job. A browser can get
the map's points up to 300 ms later, at its next poll of `/jobs`. The second budget: the Uber
CSV loads in less than 10 s, as `benchmarks/uber.py` measures it. Add
regression thresholds to CI only once there are real users, or a release that makes speed claims,
and only where results are reproducible. Report differences in workloads
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
- **Pages and tabs.** The router sends only the shown page. A change on another page isn't
  sent: the page brings it once shown, as navigating swaps the router. Tabs send only the
  shown tab's views, the other panels left empty. The browser shows the tab picked at once,
  then the answer to its post fills the tab picked and empties the tab left.
- **Dialogs** render at the end of the page, outside the shown page's slot (a page not shown
  isn't sent, and would take them with it). The browser opens a modal `<dialog>` only from a script: `page.js`
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
