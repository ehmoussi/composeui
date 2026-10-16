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

Charts have a section of their own (2).

The web versions follow the same rules as the existing ones: the element that sent the
request is never swapped back (the focus rule), changes elsewhere arrive as OOB updates,
`aria-*` links between a field, its label and its log, and a `make css` rebuild when new
classes appear (a test fails otherwise).

## 2 — Charts

A `ChartView` for engineering results: a quantity against time or a swept dimension,
measurements against a model, values per case. Users explore these curves (zoom into a
transient, read an exact value, switch to a log axis), so each backend gives what its
toolkit offers of that, and the web, where it costs a library, gets one small and fast
enough for long series. Report images are drawn apart, by matplotlib, the same on every
backend (see "Report images").

### The view (`core/view.py`)

```python
@attrs.define
class Series:
    name: str                       # legend entry
    x: list[float]
    y: list[float]                  # same length as x (validator); NaN leaves a gap

class ChartKind(enum.Enum):
    LINE = enum.auto()
    SCATTER = enum.auto()
    BAR = enum.auto()

@attrs.define(eq=False)
class ChartView(View):
    _renderer_key = "chart"
    title: str = attrs.field(default="", metadata={UI_TEXT: True})
    x_title: str = attrs.field(default="", metadata={UI_TEXT: True})
    y_title: str = attrs.field(default="", metadata={UI_TEXT: True})
    x_unit: str = ""                # shown as "Time (s)", and with hover values
    y_unit: str = ""
    kind: ChartKind = ChartKind.LINE
    series: list[Series] = attrs.field(factory=list)
    categories: list[str] = attrs.field(factory=list)  # BAR: x is the category index
    x_log: bool = False
    y_log: bool = False
```

Data and labels only: no colors, fonts or sizes, which each backend takes from its theme.
Like a table's rows, assigning `series` (a new list) redraws the chart; a job adding points
assigns a new list too. `Series` serializes with `cattrs` as is, so a study saves its
charts like its tables. A log axis refuses values <= 0 by leaving them out (each backend
alike, tested), rather than raising mid-job.

### Steps

Each step on Qt, Textual and the web, with tests, before the next:

1. **Line charts**: `ChartView` with `LINE`, title, axis titles and units, legend, several
   series (each with its own x), NaN gaps; an example plotting a swept result
   (`examples/` app, also used by the tests).
2. **Scatter** (`SCATTER`), e.g. measurements over a model curve: needs one chart with a
   line series and a scatter series, so `kind` may then move to `Series`; decide at this
   step, not before.
3. **Bars** (`BAR` with `categories`): one bar group per category, one bar per series.
4. **Log axes** (`x_log`, `y_log`).
5. **Report images** (see below): `chart_figure`/`save_chart_image`, then the "Save
   image" action on each backend.
6. **Web: full resolution on zoom** (see below), once a real app needs it.

### Qt: pyqtgraph

[pyqtgraph](https://www.pyqtgraph.org/) (MIT; pure Python over numpy), added to the
`pyside6` extra. Built for live scientific data: fast with long series (it downsamples
and clips to the view itself), mouse zoom and pan, and images and heatmaps for later.
It picks its Qt binding from `QT_API`, like `qtpy`, so the app's binding is the one used.
0.14 needs Python 3.10, so the extra asks `pyqtgraph>=0.13.7`, which resolves to 0.13.7
on 3.9; CI checks that one against PySide6 6.10 too. numpy comes with it; nothing in
`core` uses it.

A `pg.PlotWidget` per chart; each series a `PlotDataItem` filled at once with
`setData(x, y)` (numpy arrays: NaN leaves a gap with `connect="finite"`), drawn with
`setDownsampling(auto=True, mode="peak")` and `setClipToView(True)`, so 1M points stay
fluid. Scatter: `symbol` on, `pen=None`; bars: one `pg.BarGraphItem` per series, offset
in each category, the categories as the x axis' ticks (`AxisItem.setTicks`). Log axes:
`setLogMode(x, y)`; titles and units: `setLabel("bottom", title, units=unit)`, which also
gives SI prefixes (ms, kPa). Legend: `addLegend()`, clicking an entry hides its series.
- Zoom and pan: pyqtgraph's own (wheel zooms, drag pans, right drag zooms per axis, the
  "A" button and the context menu's "View All" reset), nothing to add. Its context menu's
  own Export stays for CSV; images come from "Save image…" (see "Report images"), which
  the renderer adds to that menu.
- Hover values: a `SignalProxy` on the scene's `sigMouseMoved` (rate-limited) finds the
  nearest point of each series at the cursor's x and shows them, with units, in a
  `pg.TextItem` by the cursor, with a vertical line (`InfiniteLine`) as a crosshair;
  as uPlot's legend does on the web.
- Updates: a new `series` list calls `setData` on the existing items (items added or
  removed when the count changes), so the user's zoom stays, as on the web.
- Theme: background, axes, grid and text from the application palette (`Window`,
  `WindowText`), series colors from a fixed palette readable on both; reapplied on
  `QEvent.PaletteChange` (the color scheme changing at runtime).
- Typing: pyqtgraph ships no type hints, so a `[[tool.mypy.overrides]]` with
  `ignore_missing_imports` for it, the renderer typed at its edges.
- Tests (`qtbot`): the axes' labels, units and log modes, the items' data (point counts,
  NaN gaps), the legend's names, a new `series` list keeping the view range, the hover
  text for a mouse move over a known point.

Matplotlib was the alternative for the live widget: better figures and every chart type,
but slow to redraw for live results, no hover values or Qt theme without extra work. It
draws the report images instead, where those don't matter.

### Textual: `textual-plotext`

`textual-plotext` 1.0 (Textualize; `plotext` underneath), added to the `tui` extra.
`PlotextPlot` widget: `plt.plot`, `plt.scatter`, `plt.multiple_bar`, `plt.xscale("log")`,
title, axis labels and legend; it follows the Textual theme. No zoom or hover in a
terminal: none planned. Tests (`run_test`): the widget is there and its `plt` got the
series, axis titles and scales.

### Report images: matplotlib

A screen chart is not a report figure: its size, fonts and colors follow the window and
the theme (a dark one prints badly), and pyqtgraph's, uPlot's or plotext's exports differ
from each other. So a report image is drawn from the `ChartView`'s data by matplotlib, on
the server or the desktop alike: one look whatever the backend, vector formats, and the
figure an engineer already knows how to adjust.

**Dependency.** A `report` extra, `matplotlib>=3.9` (3.9 still supports Python 3.9). Only
the Agg and vector backends, through `matplotlib.figure.Figure`, never `pyplot`: no GUI
backend, no global state, so it runs beside Qt and in a web request's thread alike.
Imported inside the functions, so `core` still imports nothing at import time.
`is_available()` (`importlib.util.find_spec("matplotlib")`) tells the renderers whether
the extra is there; without it, calling the functions raises an `ImportError` naming the
extra, Qt keeps pyqtgraph's own Export (PNG, SVG), the web falls back to a PNG drawn in
the browser (below), and Textual offers no image.

**API** (`composeui.core.chartimage`), usable without any UI, e.g. a batch run writing a
report's figures:

```python
@attrs.frozen
class ImageOptions:
    width_mm: float = 160           # an A4 page's text width
    height_mm: float = 100
    dpi: int = 300                  # PNG only
    font_size: float = 9            # points, as the report's body text
    show_title: bool = False        # reports usually caption a figure themselves
    x_range: Optional[tuple[float, float]] = None   # None: all the data
    y_range: Optional[tuple[float, float]] = None

def chart_figure(chart: ChartView, options: ImageOptions = ImageOptions()) -> Figure: ...
def save_chart_image(chart: ChartView, path: Path, options: ImageOptions = ...) -> None: ...
def chart_image_bytes(chart: ChartView, image_format: str, options: ...) -> bytes: ...
```

- `chart_figure` gives the matplotlib `Figure`, so app code can add annotations, a
  reference line or a second axis before saving it (`fig.savefig`).
- Formats by the path's suffix: PDF and SVG (vector, for LaTeX and Word), PNG (raster at
  `dpi`), also EPS. Text stays text: `pdf.fonttype = 42` (TrueType embedded, not
  outlines), `svg.fonttype = "none"`, so a figure's labels can still be edited or searched.
  Settings through `matplotlib.rc_context`, never the global `rcParams`.
- Drawing: the same mapping as the screen (titles with units as "Time (s)", log axes via
  `set_xscale("log")`, NaN gaps as matplotlib draws them, bars grouped by category,
  values <= 0 left out of a log axis), light background, a light grid, the legend
  outside the data when there are more than a few series, `constrained_layout` so labels
  never get cut. Series colors and line styles from a colorblind-safe palette
  (Okabe-Ito) with a dash pattern per series beyond it, so a figure printed in black and
  white still tells the series apart. Long series need no thinning: matplotlib's path
  simplification keeps what shows at the figure's resolution.
- `x_range`/`y_range`: the region the user zoomed into, so the saved image is what they
  look at, not the whole run.

**"Save image…" per backend**, its text translated like the other built-in texts:
- Qt: an action in the plot's context menu; a `QFileDialog` (PDF, SVG, PNG filters, PDF
  first) picks the file; the image gets the plot's current view range.
- Web: a download button in the figure's corner, an `<a download>` to
  `GET /widget/{id}/image?format=pdf&x_min=…` (the format from a small dropdown: PDF,
  SVG, PNG). The page's script updates its address from uPlot's `setScale` hook, so it
  carries the zoom; the route answers `chart_image_bytes`, with the content type and a
  `Content-Disposition: attachment` named after the chart's title, under the session's
  lock like any request. No JavaScript drawing, so the same file as from Qt.
- Web without the `report` extra: a "Save image (PNG)" button instead, no format
  dropdown, and the image route answers 404. Nothing on the server and no library in the
  page: the script draws the PNG itself, so a deployment that doesn't need report
  figures stays without matplotlib (~41 MB with numpy). On a click it:
  - builds a second uPlot off-screen from the chart's JSON at 1600 × 1000 px, with the
    light theme's colors whatever the page's theme (the code that rebuilds a chart on a
    theme change, given the light colors), at the chart's current zoom;
  - draws onto a canvas of its own a white background, the title, that chart's canvas
    and the legend (series' colors and names: uPlot's title and legend are HTML, not on
    its canvas), with `fillText`;
  - destroys the off-screen chart, and downloads the canvas (`toBlob`, an object URL on an
    `<a download>` named after the chart's title, then revoked).

  Screen quality only: a raster at a fixed size, the thinned points the page has, the
  browser's fonts; no PDF or SVG. Enough for a quick look or a slide, not for a printed
  report, which is what the `report` extra is for.
- Textual: a key binding on the chart (`s`) opens `textual-fspicker`'s save dialog (as the
  File menu's Save does) and writes the whole chart (no zoom in a terminal).

**Tests.** `tests/test_chartimage.py` (`pytest.importorskip("matplotlib")`): the figure's
axes (labels with units, scales, limits from `x_range`, one line per series, NaN gaps,
legend names), a PNG's pixel size from millimetres and dpi, an SVG holding the labels as
`<text>`, a PDF starting `%PDF`, the global `rcParams` untouched afterwards. Per backend:
Qt, the action saving through a monkeypatched `QFileDialog` with the view range; web,
the route's content type, attachment name and the range from the query, and in
`tests/test_browser.py` the link's address following a zoom; web without the extra
(`is_available` monkeypatched), the figure's PNG button without the dropdown and the
image route's 404, and in `tests/test_browser.py` the button downloading a PNG
(Playwright's `expect_download`) of 1600 × 1000 px with a light background under the dark
theme, leaving no off-screen chart behind; Textual, the binding saving the file through
the dialog.

### Web: uPlot

[uPlot](https://github.com/leeoniya/uPlot) 1.6 (MIT): line, scatter (`mode: 2`) and bars
(`uPlot.paths.bars`), drag to zoom, double click to reset, a cursor showing every series'
value at the hovered x in the legend, log scales, a toggle per series in the legend;
canvas, built for long time series. 50 KB minified, 22 KB gzipped, against ~150 KB
gzipped for a custom ECharts build of the same charts.

**Files.** `uPlot.iife.min.js` vendored into `webcore/static/` (no CDN: the page works
offline), its version noted in a comment of `page.py`; `uPlot.min.css` (2 KB) imported
by `css/app.css`, so `make css` folds it into `app.css`, no second stylesheet. Add
Starlette's `GZipMiddleware` (`minimum_size=1024`) in `create_starlette_app` in the same
step: nothing is compressed today, and series JSON compresses about 5×.

**Loaded only when needed.** The page doesn't reference uPlot; it knows its address
(`_static_url`, so a new version is a new address, cached for good). `page.py`'s script,
in the `MutationObserver` that already opens dialogs, adds the `<script>` once the first
`[data-chart]` element is in the page (from the first load or a swap: a page switch can
bring the first chart), then draws the waiting charts from its `onload`. A page without
charts never loads it.

**The renderer** (`WebChartRenderer`) renders:

```html
<figure id="cui-…-chart" class="…">
  <figcaption>Title</figcaption>
  <div data-chart="{…json…}" role="img" aria-label="Title: Pressure, Temperature
       against Time (s)" class="h-72 w-full"></div>
</figure>
```

- The JSON (through `html.escape`, like any view text): kind, axis titles with units,
  log flags, category labels, series names, and data in uPlot's columnar form:
  `[[x…], [y1…], [y2…]]` when all series share x, else one `[x, y]` pair per series
  (joined in the browser with `uPlot.join`, gaps as `null`). NaN and infinities become
  `null` (JSON has neither; `json.dumps(allow_nan=False)` catches any left), which uPlot
  draws as a gap.
- **Thinning.** A series longer than `CHART_MAX_POINTS` (about 4000: twice a wide plot's
  pixels) is reduced to the min and max of each x bucket, so peaks stay; done in the web
  renderer only: Qt (which downsamples on screen itself) and Textual get every point. 100k points × 2 series would be ~3 MB of
  attribute; thinned, ~100 KB before gzip.
- The figure is the swapped fragment: a new `series` list marks it dirty and it arrives
  as an OOB swap like a table.

**The page's script** (a few dozen lines in `page.py`, in the dialogs' manner):
- *Start*: for each `[data-chart]` without a chart, `new uPlot(options, data, div)`, kept
  in a `Map` by the element; options built from the JSON (scales, axes with
  `label` = title and unit, series with names, `paths.bars` for bars, `mode: 2` for
  scatter, `distr: 3` for a log scale; `spanGaps: false`).
- *Swapped out*: the same observer's removed nodes destroy their charts (`chart.destroy()`),
  which would leak otherwise. Removals are handled before additions, and a chart whose
  user had zoomed leaves its x range keyed by the element's id: the chart swapped in with
  that id (a job adding points) starts at the same range, so new data doesn't throw the
  user out of the region they are looking at.
- *Size*: a `ResizeObserver` per chart calls `setSize` with the div's width and height.
  A chart on a hidden page (all pages' slots are in the document) has no width: it is
  drawn when its observer first sees one, not before.
- *Theme*: colors read from daisyUI's CSS variables (`--color-base-content` for axes,
  grid and text, `--color-primary`, `--color-secondary`, `--color-accent`, `--color-info`,
  `--color-success`, `--color-warning`, `--color-error` for series, in that order, then
  around again dashed). uPlot can't recolor a chart, so `applyTheme` and the browser's
  `prefers-color-scheme` change (`matchMedia(...).addEventListener("change")`) rebuild
  each chart from its JSON, keeping its zoom. Canvas takes the `oklch()` colors daisyUI
  gives in every browser the page supports.
- *Hover values*: uPlot's legend, under the chart, shows the values at the cursor with the
  axis units (`value` formatters); no tooltip of our own.

**Web: full resolution on zoom** (step 5). A thinned curve hides detail once zoomed in:
on uPlot's `setScale` hook (debounced), the page asks `GET /widget/{id}?x_min=…&x_max=…`
and the renderer answers that range's points, thinned to the same cap, as JSON that the
script `setData`s without rescaling. Fits the existing fragment route; deferred until a
real app has curves long enough to need it.

**Tests.** `tests/test_webrenderer.py` (TestClient): the JSON in `data-chart` (columnar
form, NaN as `null`, thinning keeping each bucket's extremes, units in axis labels,
`aria-label`), a page without a chart not mentioning uPlot, a new `series` list arriving
as an OOB swap of the figure, `GZipMiddleware` compressing `app.css`. `tests/test_browser.py`:
uPlot loads only once a chart is in the page, a chart draws (canvas present, legend shows
the series), it follows the Theme menu (a pixel of the axis color changes), a swap
destroys the old chart (no leftover uPlot root) and keeps the zoom, a chart on a hidden
page draws when the page is shown, and resizing the window resizes the canvas.

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
