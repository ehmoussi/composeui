# Roadmap

What's left to do on ComposeUI. It merges the earlier plans and the library review
(`NEXT_PLAN.md`, `PAGES_PLAN.md`, `WEB_BACKEND_PLAN.md`, `REVIEW.md`); everything they
listed as done is gone from here, and lives in the code, the README and `git log`. Build
and test each step before moving on, and delete a step's entry once it lands.

## 1 — Widgets

One widget at a time, each on Qt, Textual and the web with tests (the registry consistency
test requires all three backends to register the same keys). Already there: input, float
input, label, log, button, progress bar, checkbox, radio group, combobox, table (editable cells included), forms, pages, message
and confirm dialogs.

1. **Tabs** (`TabView`). Distinct from pages: tabs live inside a page or form, and aren't
   routes.
2. **Tree view** (`TreeView`).
3. **Markdown** (`MarkdownView`): read-only Markdown text, e.g. a help page or a report's
   summary. Steps:
   - **View** (`core/view.py`): a `MarkdownMixin` with
     `text: str = attrs.field(default="", metadata={UI_TEXT: True})`, as `LabelMixin`
     (the app's text, set through `self.tr`, never saved in a study), and
     `MarkdownView(MarkdownMixin, View)` with `_renderer_key = "markdown"`.
   - **Qt** (`qtcore/qtrenderer.py`): `QtMarkdownRenderer` on a read-only `QTextBrowser`
     with `setOpenExternalLinks(True)`; the `text` handler calls `setMarkdown`;
     `_update_state` does nothing (the user can't edit it). `"markdown"` in `RENDERERS`.
   - **Textual** (`textualcore/textualrenderer.py`): `TextualMarkdownRenderer` on
     `textual.widgets.Markdown`; the `text` handler calls its `update` (it returns an
     awaitable: check it applies without being awaited, as the other handlers aren't);
     links open in the browser (`Markdown.LinkClicked` → `app.open_url`).
   - **Web** (`webcore/webrenderer.py`): `WebMarkdownRenderer`, role `"markdown"`, the
     `text` handler `_mark_dirty`; `to_html` renders `<div class="cui-markdown">` around
     `MarkdownIt("commonmark", {"html": False}).render(text)`: raw HTML off, so the text
     can't inject markup (markdown-it already refuses `javascript:` links). Add
     `markdown-it-py` to the `web` extra (Textual already pulls it in) and `uv lock`.
     Tailwind's preflight strips headings, lists and code of their look, so style
     `.cui-markdown h1…h3, p, ul, ol, code, pre, a, table` in `css/app.css` with the
     theme's colors, then `make css`.
   - **Tests**, per backend: a heading and a list are shown, setting `text` replaces
     them, and on the web a `<script>` in the text comes out escaped and a link is an
     `<a href>`. The registry test checks all three register `"markdown"`.
   - **Docs and example**: the README's widget list, and a help page in
     `examples/pipeform.py` (its text through the translation catalogs, `make translations`).

Sorting and filtering tables (2) and charts (3) have sections of their own.

The web versions follow the same rules as the existing ones: the element that sent the
request is never swapped back (the focus rule), changes elsewhere arrive as OOB updates,
`aria-*` links between a field, its label and its log, and a `make css` rebuild when new
classes appear (a test fails otherwise).

## 2 — Table: sort and filter

The user orders a table's rows by a column and filters them by the columns' values, on
`TableView` and `RecordTableView`, on Qt, Textual and the web. Today the table shows
`rows` as they are; the app sorts or filters them itself, if at all.

**What the user does.**

- **Sort:** clicking a sortable column's header sorts by it, ascending; a second click
  descending; a third puts the rows back in the app's order. One column at a time. The
  header shows the order (▲/▼).
- **Filter:** a filter bar above the table, one line, shown only when a column is
  filterable. Not a row of fields under the headers: that costs a row on every table,
  cramps narrow columns, and on Textual has to be kept aligned with the columns by hand.
  The bar reads, left to right:

  ```
  [🔍 Search          ] [+ Filter]  (Temperature min (°C) >=20 ×) (Room bed ×)   12 of 40
  ```

  - **Search:** a field over every filterable column's text (the cells containing it,
    ignoring case), applied as the user types. Most short tables need nothing more.
  - **+ Filter** opens, in the bar itself (no popup, so it works the same everywhere), a
    column picker (the filterable columns' headers), a value field and an Add button.
    Enter or Add adds the filter and closes the editor; Escape closes it without adding.
    A value that doesn't parse isn't added: the field is marked invalid, saying why, and
    the editor stays open.
  - **Chips:** each filter added shows as a chip, its column's header then the text typed
    (`Temperature min (°C) >=20`), so what's filtered is always in view. × removes it;
    clicking the chip reopens the editor on it. One filter per column: adding one to a
    column that has one replaces it (a range covers "between"). The chips wrap onto a
    second line when the bar is too narrow, e.g. on a phone. A Clear button removes
    them all once there are two or more.
  - **Count:** "12 of 40" while a search or a filter hides rows; when none match, the
    table's body says so ("No rows match the filters") rather than being empty.
  - A row is shown when it passes the search and every filter.
- **What a filter's value means**, by the column:
  - text (any `TableView` column, a `str` or enum field): the cells containing it,
    ignoring case;
  - a number (`int`, `float`, `Decimal` field) or a date (`date`, `datetime`, written as
    a study saves it): a comparison, `>20`, `>=20`, `<20`, `<=20`, `!=20`, a range
    `18..24` (both ends included), or a bare value meaning `=`;
  - a boolean: `true` or `false`, parsed as an edit is (`_parse_bool`);
  - `=` alone: the empty cells (None fields).

  Values parse with `_CELL_CONVERTER`, as edits do. The value field's placeholder hints
  at the syntax for the column picked (`>=20, 18..24` for a number, `contains…` for
  text).

**View** (`core/view.py`, on `TableMixin`, so both tables have it):

- `sortable_columns: list[int]` and `filterable_columns: list[int]`, empty by default, as
  `editable_columns`: an existing table doesn't change, and has no filter bar unless a
  column is filterable. `Column` gets `sortable` and `filterable` (False by default),
  which `RecordTableView._reconcile_columns` turns into those lists.
- The state: `sort_column: Optional[int]`, `sort_descending: bool`, `search: str` and
  `filters: dict[int, str]` (column → the value typed), saved in a study with the view,
  so a study reopens sorted and filtered as it was left. A validator rejects a column
  out of `headers` or not sortable/filterable, and a filter that doesn't parse; loading a
  study whose columns changed drops those entries rather than failing.
- The app sets them too (e.g. a table opening sorted by name, or filtered on a room),
  and reads them. The bar's editor (open or not, its column and text) is the renderer's,
  not view state: only added filters count.
- `shown_rows: list[int]`, computed in core, never set: the indexes into `rows` of the
  rows shown, in their shown order. Renderers display `[rows[i] for i in shown_rows]` and
  map their display rows back through it, so every backend sorts and filters the same
  way, and a backend's own sorting (Qt's `setSortingEnabled`, `QSortFilterProxyModel`,
  `DataTable.sort`) is never used. Parsing a filter is core's too (`parse_filter`), so
  each backend's editor asks it whether a value is valid, and why not.
- **Indexes stay in `rows`.** `selected_rows`, `selection_changed` and `cell_edited`'s
  row keep meaning indexes into `rows`, whatever the order: the app's code doesn't change,
  and a selection or an edit lands on its row.
- A search or a filter hiding a selected row deselects it (`selection_changed` emits):
  the app never acts on a selection the user can't see, e.g. deleting the selected rooms.
- New `rows` (or `records`) keep the sort, the search and the filters: an edit that
  changes a sorted cell moves its row, which stays selected as `TableMixin` already says.
  An edited row that no longer passes the filters disappears, as in a spreadsheet.

**Order.** A stable sort, so rows equal in the column keep the app's order. A
`RecordTableView` sorts by the fields' values, so numbers and dates order as such, not
as text; text by `str.casefold`; None last, ascending or descending. A plain `TableView`
only has text, sorted by `casefold`: a table with numbers to sort should be a
`RecordTableView`.

**Qt** (`qtcore/widgets/`, `QtTableRenderer`):

- The header's `sectionClicked` on a sortable column sets the view's sort; the header's
  sort indicator (`setSortIndicatorShown`, `setSortIndicator`) shows it, without
  `setSortingEnabled`, which would sort the model itself.
- The bar: a `QTableFilterBar` widget above the `QTextTableView`, the renderer's widget
  becoming a container of both. A `QLineEdit` with a clear button and a search icon; a
  `QToolButton` "+ Filter"; the editor a `QComboBox`, a `QLineEdit` and an Add button,
  hidden until opened; the chips flat `QToolButton`s with a × in a small flow layout
  (Qt has none built in: the Qt docs' `FlowLayout` example, typed), so they wrap; the
  count a `QLabel`. The invalid value: the line edit's invalid style and its tooltip, as
  a form's float field.
- `QTextTableModel` holds the shown rows; the renderer maps its row indexes through
  `shown_rows` for the selection and `cell_edited`.

**Textual** (`textualcore/textualrenderer.py`, `ComposeTable`):

- `DataTable.HeaderSelected` on a sortable column sets the sort; the column's label gets
  ▲/▼.
- The bar: a `Horizontal` above the `DataTable`, of an `Input` (search), a `Button`
  (+ Filter), the editor (`Select`, `Input`, `Button`, hidden until opened), the chips as
  `Button`s and the count as a `Static`. The widgets `compact=True` (Textual ≥ 2.0;
  the project pins 8), so the bar is one line, not the three of a bordered `Input`. The
  invalid value: the `Input`'s `-invalid` class and the reason in its tooltip.
- The rows added in `shown_rows` order, the row keys still `rows`' indexes, so the
  selection and edits map back by key.

**Web** (`webcore/webrenderer.py`, `WebTableRenderer`):

- A sortable header holds a `<button>` posting `{"event": "sort", "column": …}`, the
  `<th>` carrying `aria-sort="ascending|descending|none"`.
- The bar: a `<div role="search">` above the table, `flex flex-wrap` so the chips wrap.
  The search an `<input type="search">` posting `{"event": "search"}` on
  `input changed delay:300ms`; "+ Filter" a button; the editor a `<form>` of a
  `<select>`, an `<input>` and an Add submit, posting `{"event": "add_filter"}`; the
  chips daisyUI badges, each with a remove `<button>` labelled "Remove the filter on
  <header>"; the count an `aria-live="polite"` `<span>`, so a screen reader hears it.
- The focus rule: the field the user types in is never swapped back. A search, a filter
  or a sort swaps only the `<tbody>` (an id of its own, `cui-{id}-table-body`), the
  count, the chips and the `<th>`s' sort state, as OOB updates, so typing in the search
  isn't interrupted. Adding a filter closes the editor, the focus going to "+ Filter";
  an invalid value keeps the editor and sets its field's `aria-invalid` and
  `aria-describedby` message by an OOB swap, not by replacing the field.
- Rows keep their ids from `rows`' indexes (`-row-{index}`), so focus follows a row
  that moved.
- New classes → `make css`.

**Tests**, per backend, on real widgets: a header click sorts ascending, a second click
descending, a third restores the order; numbers sort as numbers on a `RecordTableView`
(`9 < 10`) and None comes last; the search hides the rows that don't match; adding a
filter through the editor hides rows and shows its chip, removing the chip shows them
again, a second filter on the same column replaces the first, two columns' filters
combine; `>`, `..` and `=` work on a number column; an invalid value isn't added and is
marked invalid; the count, and the "no rows match" body; a selection and an edit on a
sorted, filtered table reach the right row of `rows`; a filter hiding a selected row
deselects it; new `rows` keep the order and the filters; a table without filterable
columns has no bar. In core: `shown_rows`, `parse_filter`, and a study saving and
reloading a sorted, filtered table. On the web, browser tests that typing in the search
keeps the caret and focus while the body updates, and that adding a filter gives the
focus to "+ Filter".

**Docs and example:** the README's table section; in `examples/indoorenvironments.py`,
the rooms table sortable and filterable on every column (e.g. `Temperature min >=20`);
the new UI text ("Search", "+ Filter", "Add", "Clear", "12 of 40", "No rows match the
filters", the invalid-value messages, the placeholders) through the translation catalogs
(`make translations`).

## 3 — Charts

`ChartView` is in (README, "Charts"): line, scatter and bar charts, log axes, and report
images drawn by matplotlib, on Qt (pyqtgraph), Textual (textual-plotext) and the web
(uPlot); `examples/pipechart.py` shows it. Left:

1. **Web: full resolution on zoom**, once a real app needs it. A thinned curve hides
   detail once zoomed in: on uPlot's `setScale` hook (debounced), the page asks
   `GET /widget/{id}?x_min=…&x_max=…` and the renderer answers that range's points,
   thinned to the same cap (`CHART_MAX_POINTS`), as JSON that the script `setData`s
   without rescaling. Fits the existing fragment route.

## 4 — A SQLite model

`SqliteModel` is in (README, "A SQLite model"): the app's tables and SQL, transactions,
typed rows, a `changed` signal per table, and studies saved as a zip of the views' state
and the database, checked before opening and brought up to date by migrations; on the
web, per session; `examples/pipecatalogue.py` shows it. Left:

1. **A worker thread writing results** (once there is a progress bar): the model's lock
   already lets one share the connection; an example should show the views updated
   through `call_on_main_thread`, not from the worker.

## 5 — Adoption

1. **API reference docs** (mkdocs + mkdocstrings; the code is fully typed), with a widget
   catalog and a short architecture page (views, signals, renderers, the registry).
2. **Packaging story** for apps built on ComposeUI: PyInstaller or briefcase for Qt, a
   plain `uvicorn` deployment note for the web.
3. **`CHANGELOG.md`, semantic versions and a PyPI release.**

## 6 — Later, when needed

- **Web: keep sessions across restarts.** Persist each session's `save_state` JSON (a
  directory, or Redis) and reload it when a cookie for an unknown session arrives; needs a
  fixed signing key from the environment. Only worth it for a deployed app, which also
  raises multi-process serving (sessions live in one process's memory today).

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
  would hide them). The browser opens a modal `<dialog>` only from a script: `page.py`
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
