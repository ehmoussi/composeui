# Roadmap

What's left to do on ComposeUI. It merges the earlier plans and the library review
(`NEXT_PLAN.md`, `PAGES_PLAN.md`, `WEB_BACKEND_PLAN.md`, `REVIEW.md`); everything they
listed as done is gone from here, and lives in the code, the README and `git log`. Build
and test each step before moving on, and delete a step's entry once it lands.

## 1 — Widgets

One widget at a time, each on Qt, Textual and the web with tests (the registry consistency
test requires all three backends to register the same keys). Already there: input, float
input, label, log, button, progress bar, checkbox, radio group, combobox, table (editable cells, sorting and filtering included), forms, pages, message
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

Charts (2) have a section of their own.

The web versions follow the same rules as the existing ones: the element that sent the
request is never swapped back (the focus rule), changes elsewhere arrive as OOB updates,
`aria-*` links between a field, its label and its log, and a `make css` rebuild when new
classes appear (a test fails otherwise).

## 2 — Charts

`ChartView` is in (README, "Charts"): line, scatter and bar charts, log axes, and report
images drawn by matplotlib, on Qt (pyqtgraph), Textual (textual-plotext) and the web
(uPlot); `examples/pipechart.py` shows it. Left:

1. **Web: full resolution on zoom**, once a real app needs it. A thinned curve hides
   detail once zoomed in: on uPlot's `setScale` hook (debounced), the page asks
   `GET /widget/{id}?x_min=…&x_max=…` and the renderer answers that range's points,
   thinned to the same cap (`CHART_MAX_POINTS`), as JSON that the script `setData`s
   without rescaling. Fits the existing fragment route.

## 3 — A SQLite model

`SqliteModel` is in (README, "A SQLite model"): the app's tables and SQL, transactions,
typed rows, a `changed` signal per table, and studies saved as a zip of the views' state
and the database, checked before opening and brought up to date by migrations; on the
web, per session; `examples/pipecatalogue.py` shows it. Left:

1. **A worker thread writing results** (once there is a progress bar): the model's lock
   already lets one share the connection; an example should show the views updated
   through `call_on_main_thread`, not from the worker.

## 4 — Adoption

1. **API reference docs** (mkdocs + mkdocstrings; the code is fully typed), with a widget
   catalog and a short architecture page (views, signals, renderers, the registry).
2. **Packaging story** for apps built on ComposeUI: PyInstaller or briefcase for Qt, a
   plain `uvicorn` deployment note for the web.
3. **`CHANGELOG.md`, semantic versions and a PyPI release.**

## 5 — Later, when needed

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
