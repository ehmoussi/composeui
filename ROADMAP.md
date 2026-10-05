# Roadmap

What's left to do on ComposeUI. It merges the earlier plans and the library review
(`NEXT_PLAN.md`, `PAGES_PLAN.md`, `WEB_BACKEND_PLAN.md`, `REVIEW.md`); everything they
listed as done is gone from here, and lives in the code, the README and `git log`. Build
and test each step before moving on, and delete a step's entry once it lands.

## 1 — Widgets

One widget at a time, each on Qt, Textual and the web with tests (the registry consistency
test requires all three backends to register the same keys). Already there: input, float
input, label, log, checkbox, radio group, combobox, read-only table, forms, pages, message
and confirm dialogs.

1. **Tabs** (`TabView`). Distinct from pages: tabs live inside a page or form, and aren't
   routes.
2. **Progress bar** (`ProgressBarView`).
3. **Tree view** (`TreeView`), and editable table cells if an app needs them.
4. **Charts** (`ChartView`): curves first (one or more series of x/y points, e.g. a
   result against a swept dimension), then scatter and bar charts. The view holds data
   and labels only (title, axis titles and units, a legend name per series), no toolkit
   styling; like a table, assigning new series updates it. Interaction (zoom, hover
   values) only where a backend gives it for free. Candidates: QtCharts (part of PySide6,
   reached through `qtpy`) on Qt, `textual-plotext` on Textual.

   On the web, [ECharts](https://echarts.apache.org/) (Apache 2.0): line, scatter and bar
   charts with zoom (`dataZoom`), hover values (`tooltip`) and a legend as options, an
   SVG renderer, point sampling for long curves, and an `aria` text description. Its full
   build is about 1 MB minified, so vendor a custom one into `static/` (only those charts
   and components, the SVG renderer; no CDN, the page works offline), and load it only on
   a page with a chart. The glue, in the dialogs' manner:
   - the renderer puts the series in a `data-` attribute of a `<div>` as JSON, through
     `html.escape` like any view text;
   - `page.py` starts a chart on each such `<div>` swapped in, and disposes of the chart
     of one swapped out (`echarts.dispose`), which would leak otherwise;
   - two themes matching the daisyUI ones, the chart redrawn when the Theme menu or the
     browser's preference changes, and resized with the window.

   A chart is drawn in the browser: `tests/test_webrenderer.py` checks the JSON it gets,
   `tests/test_browser.py` that it draws, follows the theme and survives a swap.

The web versions follow the same rules as the existing ones: the element that sent the
request is never swapped back (the focus rule), changes elsewhere arrive as OOB updates,
`aria-*` links between a field, its label and its log, and a `make css` rebuild when new
classes appear (a test fails otherwise).

## 2 — A SQLite model

`SqliteModel` is in (README, "A SQLite model"): the app's tables and SQL, transactions,
typed rows, a `changed` signal per table, and studies saved as a zip of the views' state
and the database, checked before opening and brought up to date by migrations; on the
web, per session. Left:

1. **An example:** `pipeform` keeping each pipe the user records as a row, listed on its
   Results page by the read-only table and filtered by a query, with a `changed`
   connection refreshing the list.
2. **A worker thread writing results** (once there is a progress bar): the model's lock
   already lets one share the connection; an example should show the views updated
   through `call_on_main_thread`, not from the worker.

## 3 — Adoption

1. **API reference docs** (mkdocs + mkdocstrings; the code is fully typed), with a widget
   catalog and a short architecture page (views, signals, renderers, the registry).
2. **Packaging story** for apps built on ComposeUI: PyInstaller or briefcase for Qt, a
   plain `uvicorn` deployment note for the web.
3. **`CHANGELOG.md`, semantic versions and a PyPI release.**

## 4 — Later, when needed

- **Web: keep sessions across restarts.** Persist each session's `save_state` JSON (a
  directory, or Redis) and reload it when a cookie for an unknown session arrives; needs a
  fixed signing key from the environment. Only worth it for a deployed app, which also
  raises multi-process serving (sessions live in one process's memory today).
- **A generic `ToolBar` view.** Toolbar entries are per page today (`PageView.action`);
  a toolbar of arbitrary actions can come when an app wants one.

## Design notes for the web backend

Not tasks: the non-obvious decisions to keep in mind when changing `composeui.webcore`.
The README's "Web backend" section covers what users see.

- **htmx request/response**, no websockets or JS framework; Starlette, not FastAPI;
  hand-written HTML per renderer (no Jinja2), all view text through `html.escape`.
- **Ids.** A renderer's rendered object is `cui-{id(view)}-{role}`; a hidden fragment's
  root keeps its id (`hidden` attribute) so a later swap has a target.
- **Updates.** Setting a view attribute marks its renderer dirty in a request-scoped set
  (`collect_dirty`, a no-op outside requests); the route then renders every dirty
  fragment as an OOB swap (`render_dirty`). Controls use `hx-swap="none"` and the sender
  is never swapped back, so typing is never interrupted; the one exception is a float
  field left with unparsable text, swapped back to the view's value.
- **Sessions.** A signed cookie maps to a `WebSession` holding its renderers by id and an
  `RLock` (the status bar timer takes it through `call_on_main_thread`). A request whose
  session is gone answers `HX-Refresh`.
- **Open** applies an upload to a scratch instance first (core's `load_state_data`), so a
  bad file never half-loads. Responses send `Cache-Control: no-store` and controls set
  `autocomplete="off"`, so a reload always shows the server's state.
- **Dialogs** render at the end of the page, outside the pages' slots (a hidden slot
  would hide them). The browser opens a modal `<dialog>` only from a script: `page.py`
  opens each one swapped in shown, once. A button closes its dialog in the browser
  first, so focus returns where it was, then posts its answer; the server swaps it closed.
- **Header.** A web app's header, not a desktop menu bar: File's New, Open and Save are
  buttons of their own (Save As and Exit left out), and any other menu is a dropdown
  under its title, marked with a chevron so it reads apart from the buttons. A dropdown
  is as wide as its longest item, the shortcut a faded hint beside it. On a phone the
  buttons keep only their icon and the app's title is cut short, so the header holds on
  one line, the pages' toolbar on a row of its own.
- **By design:** `Menu.is_visible` is ignored (a dropdown is always shown); action `data`
  isn't displayed; Ctrl shortcuts become Alt+Shift; an unknown page address is a 404, not
  a redirect (browsers ask for addresses of their own, like `/favicon.ico`).
- **Tests** drive the examples over HTTP with Starlette's `TestClient`
  (`tests/test_webrenderer.py`); browser-only behaviour (caret, shortcuts, `aria-invalid`
  sync, offline page, history, opening dialogs) is in `tests/test_browser.py`
  (`make browser-test`).
