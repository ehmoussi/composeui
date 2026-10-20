# User guide

This guide shows how to build an app with ComposeUI. It explains each view and feature,
and what each backend shows. To install ComposeUI and write a first window, read the
[README](../README.md) first. To see the features in complete apps, read the
[examples guide](examples-guide.md). To change ComposeUI itself, read the
[technical guide](technical-guide.md).

## Contents

- [Core concepts](#core-concepts)
- [Backends](#backends)
- [Web backend](#web-backend)
- [Widgets](#widgets)
- [Pages](#pages)
- [Tabs](#tabs)
- [Resizable panes](#resizable-panes)
- [Toolbars](#toolbars)
- [Sidebar](#sidebar)
- [Dialogs](#dialogs)
- [A table of records](#a-table-of-records)
- [A list of views](#a-list-of-views)
- [Charts](#charts)
- [Running work in threads](#running-work-in-threads)
- [Saving and loading state](#saving-and-loading-state)
- [A SQLite model](#a-sqlite-model)
- [Translating the app](#translating-the-app)

## Core concepts

| Concept | Role |
| --- | --- |
| `View` (`composeui.core.view`) | A typed `attrs` data class that describes UI state (`MainView`, `InputView`, `FormView`, `ActionView`, and others). You compose views by nesting view fields inside other views. |
| `Signal` (`composeui.core.signal`) | A typed event emitter. `signal.connect(callback)` accepts callbacks that take `view`, `main_view`, or `model` keyword arguments. The signal injects them automatically, on the views' signals and on the model's signals. |
| `Renderer` / `RendererContainer` (`composeui.core.renderer`) | Binds a `View` to a concrete toolkit widget, and keeps the two in sync in both directions (`refresh_attribute` / `update_state`). |
| `Application` / `ModelApplication` (`composeui.core.application`) | Owns the `MainView`, and optionally a `Model`. Parses the command line (`--debug`, `--log`, `--log-signals`, `-f FILE`) and drives rendering. |
| `Model` (`composeui.core.model`) | Base class for the app's data, meant to be subclassed. `SqliteModel` keeps the data in a [SQLite database](#a-sqlite-model). |
| `Jobs` (`composeui.core.jobs`) | `main_view.jobs`: functions that [run in threads](#running-work-in-threads). Their results are emitted on the main thread. |

### Views are reactive

When code sets an attribute of a view (`view.text = "..."`), the view pushes the change to
its renderer. You do not call `update()` or `refresh()` for normal state changes.

### Signals inject arguments

`Signal.connect` and `Application.connect` read the callback's parameter names. When a
callback asks for `view`, `main_view`, or `model`, it gets them:

```python
# `main_view` is injected automatically because it's a requested parameter.
def _on_name_changed(self, text: str, *, main_view: MainView) -> None:
    main_view.status_bar.show_message(f"Hello, {text}!" if text else "")
```

A callback can take fewer of the signal's arguments than the signal emits. It then gets the
first ones, or none. `connect(callback, now=True)` also calls the callback once, right away.

### Command-line options of your own

A `MainView` adds command-line options with its `add_arguments` classmethod. It gets their
values in `apply_arguments`, once it is wired. On the web, this happens for every session.

### Compose views from mixins

You can compose a view by mixing traits. For example, `LabelRowFloatInputView` combines
`FormLabelRowView` and `FloatInputMixin`. The mixins in `composeui/core/view.py` are the
available building blocks: `InputMixin`, `FloatInputMixin`, `IntInputMixin`,
`DateInputMixin`, `FilePathInputMixin`, `SliderMixin`, `CheckBoxMixin`, `ValuesGroupMixin`,
`TableMixin`, `LogMixin`, `LabelMixin`, and `MarkdownMixin`.

Larger views have sections of their own:

- `PageView` and `Router` for an app split into [pages](#pages).
- `TabView` for [tabs](#tabs).
- `SplitterView` for [resizable panes](#resizable-panes).
- `ToolBar` for a [toolbar](#toolbars).
- `DialogView` for [dialogs](#dialogs).
- `SidebarView` for a [sidebar](#sidebar).

## Backends

`run(MainViewClass)` starts the app with the backend that `--backend` names: `qt`,
`textual`, or `web`. The web is the default. Each backend needs its extra:

| `--backend` | Extra | Shows the app |
| --- | --- | --- |
| `qt` | `pyside6` | In a window |
| `textual` | `tui` | In a terminal |
| `web` | `web` | In a web page |

Without `--backend`, the `COMPOSEUI_BACKEND` environment variable picks the backend. An
app can change its default with `run(MainViewClass, default_backend=RendererType.QT)`.

`run` imports only the backend that you choose. It leaves the rest of the command line to
the app (`--help` lists it). To always start one backend, build its application yourself,
for example `QtApplication(build_main_view=HelloMainView).run()`.

Every application takes a function that builds the main view, because on the web every
browser gets its own copy of it.

## Web backend

The web backend serves the views as a web page instead of a window.
`run(HelloMainView)` serves http://127.0.0.1:8000. Use `--host` and `--port` to change
the address. `WebApplication(build_main_view=HelloMainView).run()` does the same.

The server renders the pages and updates them with [htmx](https://htmx.org/). When the user
edits a field, the page posts it. The response swaps in every part of the page that changed,
such as the status bar. It never swaps the field that the user types in.

The app itself serves the styles ([daisyUI](https://daisyui.com/) on Tailwind), htmx, and
the scripts of charts and calendars. So the app also works offline.

For a fuller example, see [`src/examples/webhello.py`](../src/examples/webhello.py)
(`uv run python -m examples.webhello`), and `pipeform.py` with `--backend web`.

How it differs from a desktop window:

- **One app state per browser.** A signed session cookie gives each browser its own main
  view. The tabs of one browser share it. Sessions live in the server's memory: a restart
  starts them all over. The server drops a session after an hour without use
  (`session_ttl`).
- **Wire behavior inside the views,** as in the quickstart, with `app.connect`, or in
  `WebApplication.setup_session`. `setup_session` runs for the main view of each new session.
  The app replays `app.connect(view=app.main_view...)` on every new session. The callback
  gets the `view` and `main_view` of that session, never the template that no browser shows.
- **Models are per session too.** `run(..., build_model=..., setup_model=...)` builds one
  model per session. `WebModelApplication` takes the same arguments. `setup_model` wires the
  model to its main view, and callbacks that ask for `model` get the model of their session.
  Do not share a model between browsers. Each browser sees only what its own requests
  return, so the other browsers would show stale views.
- **Save and Open** download the state as a file and upload a file. The File menu is in the
  page header. Its shortcuts use Alt+Shift (Alt+Shift+S saves), because browsers keep the
  Ctrl shortcuts for themselves.
- **`--reload` restarts the server when a Python file under the current directory
  changes.** Use it for development. The new server process runs the program again (the
  script, or the `-m` module) with the same command line, to build its app again. Every
  restart drops the sessions.
- **Pages have their own address.** With a router (see [Pages](#pages)), each page is at
  `/<route>`, and `/` sends the browser to the first page. The toolbar of the pages is in the
  header. When the user changes pages, the browser's history gets the new address. So back,
  forward, bookmarks, and reloads land on that page. A route can't be `icon`, `jobs`,
  `state`, `static`, or `widget`, because the backend uses these addresses.
- **Icons** are the image files that actions name (`action.icon = "icons/run.svg"`, the
  path that Qt reads). The backend serves them. An SVG icon is drawn in the color of the
  text, so it follows the light and dark themes: only its shape counts, as with a Lucide or
  Material icon. PNG, JPEG, GIF, WebP, and ICO files show as they are.
- **Single process only, and no push from the server.** The page changes in response to the
  user's own actions, with two exceptions. A status bar message clears itself after its
  timeout. While [jobs](#running-work-in-threads) run, the page asks every second for the
  changes from their results.

## Widgets

### Buttons

A `ButtonView` is a button that the user clicks (`clicked`), for example under a form to
submit it. Its `variant` (`ButtonVariant`: primary, secondary, danger) tells the main
action from the other actions, and from an action that destroys something.

### Help on a form row

The `help` of a labelled row says what to enter. A "?" button beside the label shows it.
A click, a tap, or the keyboard opens it. Textual shows the help as a hint under the label.

### Integer input

An `IntInputView` takes a whole number between its `minimum` and `maximum`, for example
an hour of the day.

- Qt shows a spin box, which keeps the number in range.
- The other backends show a text field for digits. They do not refuse a number out of
  range (Textual marks it), so validate the number.

### Date input

A `DateInputView` takes a `datetime.date`, for example the first day of a booking, or no
date (`None`).

The user types the date in the format that `date_format` gives (`dd`, `MM`, `yyyy`).
ISO 8601 is always understood. The catalogs translate `date_format` as text, so the format
follows the main view's language: "MM/dd/yyyy" in English, "dd/MM/yyyy" in French.

The user can also pick the date from a calendar beside the field:

- Qt shows its own calendar. It names the months and days in the system's language.
- The web shows [Cally](https://wicky.nillia.ms/cally/), in the colors of the theme and in
  the page's language.
- Textual shows ComposeUI's own calendar. It names the months and days with the view's
  `month_names` and `day_names`.

The calendar offers only the dates from `minimum` to `maximum`. But not every backend
refuses a typed date out of range, so validate the date. `value_changed` reports the dates
that the user enters.

### File path input

A `FilePathInputView` takes the path of a file, for example a data file or a template file
for the app to read. The user types the path, or picks the file with the "…" button beside
the field.

```python
from composeui.core.view import FormView, LabelRowFilePathInputView, child, define_view


@define_view
class DataForm(FormView):
    measurements: LabelRowFilePathInputView = child(
        LabelRowFilePathInputView,
        label="Measurements",
        extensions={"CSV": (".csv",)},
        has_reload=True,
    )
```

- `text` holds the path as the user typed it. `path` reads it as a `Path`, or `None` while
  the field is empty.
- `extensions` names the file types that the "…" button offers. On the web, the backend
  refuses a file of another type.
- `path_picked` emits the path of a file that the user picks with the "…" button. A typed
  path comes through the signals of any text field: `text_edited` and `editing_finished`.
- With `has_reload`, a reload button shows beside the "…" button. It emits
  `reload_clicked`, for example to read the file again after it changed.
- `browse_text` and `reload_text` name the two buttons in a tooltip and for a screen
  reader. The catalogs translate them.

The state saves `text` and `has_reload`, but not `extensions`, which the app sets.

What the "…" button opens:

- Qt shows its file dialog, in the directory of the field's path.
- Textual shows the file picker of textual-fspicker, in the directory of the field's path.
- The web shows the browser's file picker. The browser cannot give the page a path, so it
  uploads the file. The session keeps a copy, and the field shows the path of that copy. The
  session deletes the copy when the field gets its next upload, or when the session ends.

[`src/examples/markdownviewer.py`](../src/examples/markdownviewer.py) opens a Markdown file
with a file path input, and reads the file again when the user presses reload.

### Slider

A `SliderView` picks a whole number when the user drags a handle, for example a number of
workers. The number goes from `minimum` to `maximum` by `step`. The handle stops only on a
step. The value shows beside the track, so the row is no taller than the other rows.
`value_changed` reports the user's moves.

### Progress bar

A `ProgressBarView` shows how far a long task has gone: `value` steps out of `maximum`.
While `maximum` is `None`, the bar shows only that the task runs.

[`src/examples/taskview.py`](../src/examples/taskview.py) follows tasks that run in
[threads](#running-work-in-threads) with a progress bar
(`uv run python -m examples.taskview`, or `--backend qt`, or `textual`).

### Metric

A `MetricView` shows a figure to read at a glance, for example the number of jobs running.
It shows its `label` and its `value` in large type. A badge shows the change since some
point: `delta` is the change, and `delta_text` says the point, for example "since
yesterday". The sign of the change sets the color of the badge. To show a row of metrics,
put them in a `HorizontalView`.

### Expander

An `ExpanderView` is a collapsible section, for example the details of a record with its
Edit and Delete buttons. The view fields of a subclass are its content, one above the
other. They show only while `is_expanded` is true. The user clicks the `title` to expand
or collapse the section (`toggled`).

### Tree

A `TreeView` shows `nodes` in a tree, for example the buildings, floors, and rooms of a site.
Each node is a `TreeNode` with its `label` and `children`.

A path identifies a node: the `key`s from its top-level node down to it, for example
`("Building A", "Floor 1")`. The key of a node is its label, unless you give one.

The user expands and collapses the nodes (`expanded`, `toggled`), and selects one node
(`selected`, `selection_changed`). When code sets new `nodes`, the tree keeps the expanded
and selected paths that are still in them.

A node can also show the kind and the state of what it stands for, as a study tree does:

```python
from composeui.core.view import NodeMark, TreeNode

TreeNode(
    "Study 1",
    [TreeNode("Monte Carlo", mark=NodeMark.DONE), TreeNode("Sobol", mark=NodeMark.ERROR)],
    icon="icons/study.svg",
    is_bold=True,
)
```

- **`icon`** is the path of an image file before the label, as the `icon` of an action is
  (see [Toolbars](#toolbars)). Qt and the web show it, a terminal does
  not. The app's code sets it, so it is never saved or loaded: build the nodes again from
  the model after a load.
- **`mark`** is a `NodeMark` after the label: `DONE` (a green check), `WARNING` (an orange
  "!") or `ERROR` (a red cross). The tree's `done_text`, `warning_text` and `error_text`
  name the marks: Qt shows the name as the mark's tooltip, and the web gives it to screen
  readers as the node's description.
- **`is_bold`** and **`is_underlined`** style the label.

Qt shows the marks in a second column of the `QTreeWidget`, Textual as a colored glyph
(✓, !, ✗), and the web as an icon in the node's button.

On the web, a label that is too long for the tree ends in an ellipsis.

[`src/examples/pipecatalogue.py`](../src/examples/pipecatalogue.py) shows its pipes in a
tree, under their material. It builds the tree again from the database whenever the pipes
change.

### Markdown

A `MarkdownView` shows read-only Markdown `text`, for example a help page or the summary of
a report. Its links open in the browser. On the web, the view leaves out raw HTML, so the
text can't inject markup.

[`src/examples/pipeform.py`](../src/examples/pipeform.py) has a help page.
[`src/examples/markdownviewer.py`](../src/examples/markdownviewer.py) shows a Markdown file
(`uv run python -m examples.markdownviewer --markdown README.md --backend qt`).

### The File menu and picking a file

The File menu has New, Open, Save, Save As, and Exit. An app without studies sets
`has_file_menu = False` on its `MainView` to leave out the File menu.

A `PickFileAction` is a menu or toolbar action that picks a file for the app to read (not a
study). `extensions` names the types that it offers, for example
`{"Markdown": (".md",)}`. `file_picked` emits the path of the file. On the web, the browser
uploads the file. The path is then a copy, which is deleted once the callbacks have run.

[`src/examples/markdownviewer.py`](../src/examples/markdownviewer.py) has no File menu. It
opens Markdown files with a [file path input](#file-path-input) instead of a
`PickFileAction`.

## Pages

A `Router` shows one page at a time. It adds a toolbar with an entry per page. Each page is
a `PageView` with:

- a `route`: a unique name made of letters, digits, `_`, and `-`;
- a `page_title`: its entry in the toolbar.

The view fields of a page are its content, laid out in a column:

```python
from attrs import Factory

from composeui.core.view import MainView, PageView, Router, TableView, child, define_view


@define_view
class ResultsPage(PageView):
    route = "results"
    page_title = "Results"

    summary: TableView = child(TableView, headers=["Pipe", "Radius"])


@define_view
class Pages(Router):
    form: FormPage = Factory(FormPage)  # another PageView; the first one shows at first
    results: ResultsPage = Factory(ResultsPage)


@define_view
class AppMainView(MainView):
    pages: Pages = Factory(Pages)
```

A click on a toolbar entry triggers the page's `action`, which shows the page. Code does the
same with `pages.navigate("results")`, and reacts to it through `pages.route_changed`.

The page shown is navigation, not study data: saving, opening, and New leave it alone.

Qt docks the toolbar as a `QToolBar`. Textual shows a row of buttons at the top. The web
puts the toolbar in the page header, with a web address per page.
[`src/examples/pipeform.py`](../src/examples/pipeform.py) is an app with three pages: Inputs, Results, and Help.

## Tabs

A `TabView` shows its views one tab at a time. The user picks a tab from a row of tabs, for
example the details of a record and its history. Its `TabPage` fields are the tabs, in
order. Each tab shows its `title` and has its view fields as its content, in a column:

```python
from composeui.core.view import LabelView, TabPage, TabView, child, define_view


@define_view
class DetailsTab(TabPage):
    length: LabelView = child(LabelView, text="Length: 12 m")


@define_view
class PipeTabs(TabView):
    details: DetailsTab = child(DetailsTab, title="Details")
    history: HistoryTab = child(HistoryTab, title="History")  # another TabPage
```

The view starts on the first tab. Code shows another tab with `current_index`, counted from
0. `current_tab` is the tab shown. `current_changed` reports the user's picks.

- The tab shown is navigation, not study data, as for pages.
- A hidden tab page hides its tab. The user can't pick a disabled tab page.
- Tabs are not [pages](#pages): tabs live inside a page or a form, and have no address of
  their own.

Qt shows a `QTabWidget`, Textual a `TabbedContent`, and the web a row of tabs. On the web,
the arrow keys move between the tabs.
[`src/examples/pipechart.py`](../src/examples/pipechart.py) shows its chart on one tab, and
the measurements plotted on it, as a table, on another tab.

## Resizable panes

A `SplitterView` lays out its view fields side by side, as panes. The user drags the border
between two panes to resize them, for example a study tree beside its result. Each pane
starts with its share of the width. The `STRETCH` metadata of its field sets the share, as in
a `HorizontalView`:

```python
import attrs

from composeui.core.view import STRETCH, SplitterView, define_view


@define_view
class StudySplitter(SplitterView):
    study: StudyTree = attrs.Factory(StudyTree)  # a TreeView
    result: ResultTabs = attrs.field(factory=ResultTabs, metadata={STRETCH: 3})
```

`sizes` holds the shares of the panes (here `[1, 3]`). To share the width differently, code
sets `sizes`.

The user drags a border, or moves it with the arrow keys once the border has the focus.
After that, `sizes` holds the panes shown, in percent of their width. `resized` reports
them once the user drops the border. It never reports them when code sets `sizes`.

- A pane never shrinks to nothing. A hidden pane leaves its width to the other panes.
- The width of the panes is layout, not study data: it is never saved, loaded, or reset.

Qt shows a `QSplitter`. Textual shows a row of panes with a `│` border between two panes.
The web shows an ARIA window splitter. Side by side, each pane is at least 12rem wide, so
that its text stays readable: the border stops there. When a splitter is narrower than 42rem,
the web stacks its panes without borders. It stacks the views of a row in the same way.
[`src/examples/pipecatalogue.py`](../src/examples/pipecatalogue.py) shows its tree of pipes
by material in a splitter, beside the expanders of the pipes.

### Panes one above the other

A subclass that sets `orientation` to `Orientation.VERTICAL` lays out its panes one above
the other instead. The panes then share its height, for example a chart above its table:

```python
from composeui.core.view import Orientation


@define_view
class ResultSplitter(SplitterView):
    orientation = Orientation.VERTICAL

    chart: CurveChart = attrs.field(factory=CurveChart, metadata={STRETCH: 2})  # a ChartView
    measurements: Measurements = attrs.Factory(Measurements)  # a TableView
```

Its `sizes` are then shares of its height. The user drags a horizontal border, or moves it
with the up and down keys.

- Qt shares the spare height of the window.
- Textual shares a height of 24 rows, and the web a height of 32rem. Each pane scrolls
  within its share.

The web never stacks the panes of a vertical splitter any other way: it keeps their borders
on a narrow screen.

## Toolbars

A `ToolBar` is a row of the actions that the user runs most, docked at the top of the window.
Its `ActionView` and `SeparatorAction` fields are its entries, in order. Make the toolbar a
field of the main view:

```python
from attrs import Factory

from composeui.core.view import ActionView, MainView, ToolBar, define_view


@define_view
class RunToolBar(ToolBar):
    run: ActionView = Factory(ActionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Run"  # names it, e.g. for a screen reader
        self.run.text = "Run"
        self.run.shortcut = "Ctrl+r"


@define_view
class AppMainView(MainView):
    toolbar: RunToolBar = Factory(RunToolBar)
```

- A click on an entry triggers its action.
- A checkable entry shows as pressed while it is checked.
- When code disables the toolbar, its entries are disabled too.

Qt docks the toolbar as a `QToolBar`. Textual shows a row of buttons at the top, above the
buttons of a router. The web puts its buttons in the page header, before the menus.

The `icon` of an action is the path of an image file. Qt and the web show it (see
[Web backend](#web-backend)). A terminal shows the text. The app's code sets an icon, so an
icon is not study data: it is never saved, loaded, or reset.

## Sidebar

A `SidebarView` is a column of views beside the pages. It shows on every page, for example
a form that creates a record. Its view fields are its content, under its `title`. Make it a
field of the main view, not of its router:

```python
from attrs import Factory

from composeui.core.view import ButtonView, MainView, SidebarView, child, define_view


@define_view
class NewRecordSidebar(SidebarView):
    form: NewRecordForm = Factory(NewRecordForm)  # a FormView
    create: ButtonView = child(ButtonView, text="Create")


@define_view
class AppMainView(MainView):
    sidebar: NewRecordSidebar = child(NewRecordSidebar, title="New record")
    pages: Pages = Factory(Pages)
```

Qt docks the sidebar on the left of the window, where the user can't close or move it.
Textual shows it on the left of the content, and the web as a column on the left of the
pages.

The user retracts the sidebar and expands it again with a button that `toggle_text` names:

- On Qt and Textual, the button is an arrow in the header of the sidebar. A retracted
  sidebar leaves a narrow strip.
- On the web, the button is in the page header.

Code does the same with `is_expanded`, and reacts to the user's toggles through `toggled`.
Whether the sidebar is retracted is layout, not study data.

On a phone, the web shows the sidebar as a drawer over the page. The button in the header
opens it. A tap beside it, or Escape, closes it.

In [`src/examples/pipecatalogue.py`](../src/examples/pipecatalogue.py), the form of the
sidebar adds pipes to the catalogue beside it.

## Dialogs

A `DialogView` is a modal message, or a confirmation with an accept button and a reject
button (`kind=DialogKind.CONFIRM`). It starts closed, and `open()` shows it.

Nothing waits for the answer, because a web request can't wait. Connect to `accepted` and
`rejected` instead. They fire once the dialog is closed.

```python
from attrs import Factory

from composeui.core.view import DialogKind, DialogView, MainView, define_view


@define_view
class ClearDialog(DialogView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.kind = DialogKind.CONFIRM
        self.title = "Clear the form"
        self.text = "Every field will be emptied."
        self.accept_text = "Clear"  # "OK" otherwise; the other button is `reject_text`


@define_view
class AppMainView(MainView):
    confirm_clear: ClearDialog = Factory(ClearDialog)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.confirm_clear.accepted.connect(self.reset_state)
        # ... and something calls `self.confirm_clear.open()`, e.g. an action
```

Escape, or closing the window of the dialog, rejects a confirmation. It accepts a message,
which has only one answer.

A dialog is not study data: saving, opening, and New leave it alone.

Qt shows a `QMessageBox`, Textual a modal screen, and the web a modal `<dialog>`, wherever
the view is in the tree. In [`src/examples/pipeform.py`](../src/examples/pipeform.py), Reset
Dimensions in the Pipe menu asks for a confirmation first.

### Form dialogs

A `FormDialogView` holds a form with OK and Cancel, for example to edit a record from its
Edit button. A subclass gives its form as its `form` field. Its `text` shows above the form:

```python
@define_view
class EditPipeDialog(FormDialogView):
    form: PipeForm = Factory(PipeForm)  # a FormView, with its checks
```

- The user can't press OK while a check of the form fails. `is_accept_enabled` follows the
  checks as they run.
- Accepting runs every check first, even a check that the user hasn't triggered yet. The
  dialog stays open while a check fails. `FormView.check` runs all the checks, and
  `is_valid` tells whether they pass.
- The answer comes through `accepted` or `rejected`.
- The form keeps its values. The app reads them once the user accepts, or fills them before
  `open()`.

In [`src/examples/pipecatalogue.py`](../src/examples/pipecatalogue.py), the Edit button of
each pipe changes the pipe in a form dialog.

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

- a search over the text of the filterable columns;
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

[`pipechart.py`](../src/examples/pipechart.py) shows or hides each curve with a check box,
and picks how to draw it with a combobox. [`taskview.py`](../src/examples/taskview.py) runs
a task again from its Retry button, and opens the error of a failed task from a link.

What each backend shows:

- **Qt** draws a checkable cell, a combobox frame, a push button, or underlined link text.
  A double click or F2 on a combobox cell opens a `QComboBox`. Space toggles the current
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

## A list of views
## A list of views

A `ListView` shows a view per record, one above the other. For example, it shows an
expander per record, with the details of the record and its Delete button. A subclass
builds the view of a record. Set `items` to the records, for example the model's, to show
them:

```python
from composeui.core.view import ExpanderView, LabelView, ListView, View, child, define_view


@define_view
class PipeExpander(ExpanderView):
    length: LabelView = child(LabelView)


@define_view
class PipeList(ListView[Pipe]):  # Pipe: an attrs record
    def build_item(self, item: Pipe) -> View:
        view = PipeExpander(title=item.name)
        self.update_item(view, item)
        return view

    def item_key(self, item: Pipe) -> str:
        return item.name

    def update_item(self, view: View, item: Pipe) -> bool:
        view.length.text = f"Length: {item.length:g} m"
        return True
```

`item_key` tells the records apart. By default, the key is the record itself.

- A new record gets a view of its own.
- A record that is gone takes its view along.
- A record that is still there keeps its view.
- A changed record keeps its view if `update_item` shows the change in the view and returns
  True. The view then keeps what the user did to it: an expander stays expanded. Otherwise,
  the record gets a new view.

A view built later is set up like the other views. Its signals pass `main_view` and `model`
to the callbacks that ask for them, and it shows the main view's language.

The records and their views belong to the model. They are not study data: saving, opening,
and New leave them alone.

On the web, a change swaps only the views of the records that it adds or removes, never the
other views, unless it reorders them.

The list stays compact, however many records there are. On Qt, it scrolls within itself and
takes the spare height of the page. Expanders in a list join in one box on the web, and are
a line apart on Textual.

[`src/examples/pipecatalogue.py`](../src/examples/pipecatalogue.py) lists its pipes this
way, each with a Delete button.

## Charts

A `ChartView` plots results, for example a quantity against time or a swept dimension. Its
`series` is a list of `Series`. Each series is a curve with its own `x` and `y` (as many of
each) and a `name` for the legend. A NaN leaves a gap in its curve.

```python
from composeui.core.view import ChartView, LineStyle, ReferenceLine, Series, child

chart: ChartView = child(
    ChartView, title="Pressure Drop", x_title="Flow Rate", x_unit="L/s", y_unit="kPa"
)

chart.series = [*chart.series, Series(name="D = 50 mm", x=flows, y=drops)]
```

As for the rows of a table, assign a new `series` list to draw the chart again. A job that
adds points does the same. The study saves the series.

### Kinds of chart

The `kind` of the chart (`ChartKind`) draws the series as lines (`LINE`, the default) or
dots (`SCATTER`). The `kind` of a series overrides it, for example measurements as dots over
the curve of a model.

A `BAR` chart draws values per case: a group of bars for each of its `categories`, one bar
per series. The x of a series names a category by its index, and its y is the height of the
bar:

```python
energy: ChartView = child(
    ChartView,
    kind=ChartKind.BAR,
    y_unit="kWh",
    categories=["Kitchen", "Bedroom", "Office"],
    series=[Series(name="Heating", x=[0, 1, 2], y=[120, 80, 95])],
)
```

### Log axes

`x_log` and `y_log` make an axis a log axis. A log axis leaves out what it can't show: the
chart doesn't draw a point at an x of 0 or less, and a y of 0 or less leaves a gap.

### Reference lines

`reference_lines` draws lines across the chart at values. Each line is a `ReferenceLine`:

- A horizontal line at a y, for example a capacity.
- With `vertical=True`, a vertical line at an x, for example now. On a bar chart, the x is
  the index of a category.

```python
chart.reference_lines = [
    ReferenceLine(40, "Max: 40", style=LineStyle.SOLID),
    ReferenceLine(now, "Now", vertical=True),
]
```

- Its `label` ("Max: 40") shows beside the line, not in the legend.
- Its `color` (`"#rrggbb"`) defaults to the color of the theme's text.
- Its `style` (`LineStyle`) defaults to `DASHED`. The other styles are `SOLID`, `DOTTED`,
  and `DASH_DOT`.

The range of the chart includes the lines, so a line past the data still shows. On a log
axis, the chart doesn't draw a line at 0 or less. Textual draws each line solid, because a
terminal has no dashes.

### Colors, fill, steps, and height

The view holds data and labels. Each backend draws the chart in the colors of its theme,
with these exceptions:

- A series can have a `color` of its own (`"#rrggbb"`), the same in every theme, for
  example the color of a logo.
- `fill=True` fills the area between the line of the series and 0, in its color.
- A series with `step=True` holds each value until its next point, for example the number of
  jobs running over time. With `fill`, it draws a step area. When the user hovers over the
  series, the chart shows the value held at the cursor.
  [`src/examples/taskview.py`](../src/examples/taskview.py) charts its running tasks this
  way.

`height` sets the height of the chart on screen, in pixels, for example to keep the
proportions of a shape. A terminal row is about 16 pixels. `None`, the default, leaves the
height to the backend.

### What each backend draws

- Qt draws the chart with [pyqtgraph](https://www.pyqtgraph.org/) (in the `pyside6` extra).
  The mouse zooms and pans. When the user hovers over the chart, it shows the value of each
  series at the cursor.
- The web draws the chart with [uPlot](https://github.com/leeoniya/uPlot). The page loads
  uPlot once it shows a chart. A drag across the chart zooms, and a double click zooms back
  out. The legend shows the values at the cursor. Before the server sends a long series, it
  thins the series to the extremes of each bucket of its points.
- Textual draws the chart with `textual-plotext` (in the `tui` extra), without zoom or hover.

A new `series` list keeps the user's zoom.

[`src/examples/pipechart.py`](../src/examples/pipechart.py) plots the pressure drop of a
pipe against its flow rate, with measurements over it, and the pressure of the pump as a
reference line (`uv run python -m examples.pipechart --backend qt`, or `textual`, or `web`).

### Clicks on a chart

A click on the chart emits its point from `clicked`, in the values of the axes (`x`, then
`y`). Clicks work in Qt, and on the web, where a drag still zooms. A terminal has no pointer
to click with.

[`src/examples/batman.py`](../src/examples/batman.py) draws the Batman logo, in its own
yellow and black, and says whether a click was on the bat
(`uv run python -m examples.batman --backend web`, or `qt`).

### Report images

A chart on screen follows its window and its theme. The figure of a report has the size and
fonts of the page, and a light background. `composeui.core.chartimage` draws such a figure
from the data of the chart with matplotlib (the `report` extra). The figure is the same
whatever the backend, and needs no UI, for example in a batch run that writes the figures of
a report:

```python
from composeui.core.chartimage import ImageOptions, chart_figure, save_chart_image

save_chart_image(chart, Path("drop.pdf"), ImageOptions(width_mm=80, font_size=8))
figure = chart_figure(chart)  # a matplotlib `Figure`, to annotate before saving it
```

- The suffix of the file picks the format. PDF, SVG, and EPS keep their text as text. PNG is
  drawn at `dpi`.
- `x_range` and `y_range` show a region of the data.

Each backend offers this as Save Image. Its text is translated like the other built-in text.

- Qt offers it in the context menu of the chart, at the region shown.
- The web offers it in the corner of the figure, with a format to pick, at the user's zoom.
- Textual offers it with the `s` key on a chart.

Without the `report` extra, Qt keeps the Export of pyqtgraph, and the web page draws a PNG
of the chart itself.

## Running work in threads

A long computation would freeze the app while it runs. `main_view.jobs.start(work, *args)`
runs `work(job, *args)` in a thread of its own instead.

The function must not touch a view, because the widgets of a toolkit belong to the main
thread. The function returns its result. The `finished` signal of its job emits the result
on the main thread, where the callbacks update the views:

```python
def simulate(job: Job[float], radius: float) -> float:  # in its thread
    for step in range(100):
        if job.is_canceled:
            return float("nan")
        ...  # a step of the computation
    return stress


@define_view
class PipeMainView(MainView):
    ...
    def _run(self) -> None:
        job = self.jobs.start(simulate, self.form.radius.value)
        job.finished.connect(self._show_stress)  # on the main thread

    def _show_stress(self, stress: float) -> None:
        self.results.stress.text = f"{stress:g} MPa"
```

- **Failures.** The job logs what the function raises, and its `failed` signal emits it.
- **Canceling.** `job.cancel()`, or `jobs.cancel()` for all the jobs, asks the functions to
  stop. Python can't stop a thread, so each function checks `job.is_canceled`, or waits with
  `job.sleep(seconds)`, which returns False once the job is canceled. The function still
  finishes, and `finished` emits what it returned.
- **On the main thread only.** Call `jobs.start`, `jobs.cancel`, and `jobs.drop` from a
  callback, never from the function of a job. The jobs aren't locked, because only the main
  thread changes them (`job.cancel()` works from any thread). Called from the function of a
  job, they raise `CalledInJobError`. To start another job, return what it needs, and start
  it from the callback that gets it.
- **Running or not.** `jobs.is_running` tells whether any job runs. `jobs.running_changed`
  emits it when it changes, for example to disable a Run button.
- **New, Open, and closing the app** cancel the running jobs and drop their results,
  because the results belong to the study replaced. Closing doesn't wait for the jobs either.
- **Callbacks** connected to the signals of a job get the `main_view` and `model` that they
  ask for, as for any signal.
- **On the web,** while any job runs, the page asks the server every second for the changes
  of the jobs. It stops once they are over.
- **Tests.** When no toolkit shows a main view, its jobs emit their results when the test
  calls `main_view.jobs.wait()`, on the thread of the test.

[`src/examples/taskview.py`](../src/examples/taskview.py) runs 25 jobs at once, and cancels
them.

## Saving and loading state

`MainView.save_state(path)` and `MainView.load_state(path)` serialize and deserialize the
full view tree to JSON with `cattrs`. They skip the `Signal` and `Renderer` fields
automatically. On load, they update the live view tree in place, so the renderer bindings
and signal connections survive the load.

The text that the user reads rather than enters (labels, titles, headers, button and menu
text) is tagged `UI_TEXT`, and is skipped too. This text comes from the app's code, in its
language, not from a study. Tag a text field of your own views the same way:
`attrs.field(default="", metadata={UI_TEXT: True})`.

## A SQLite model

Views hold what is shown. Some data has many rows, relations between them, and queries over
them, for example runs and their results, or a catalogue of parts. This data belongs in a
`SqliteModel`: a SQLite database of the app's own, with its own schema and SQL. The study
saves and opens it.

```python
import attrs

from composeui.core.sqlitemodel import SqliteModel, SqliteTable, table


@attrs.define
class Run:
    id: int
    radius: float


class Runs(SqliteTable):
    create = "CREATE TABLE run(id INTEGER PRIMARY KEY, radius REAL NOT NULL);"

    def add(self, radius: float) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO run(radius) VALUES (?)", (radius,))

    def above(self, radius: float) -> list[Run]:
        return self.fetch(Run, "SELECT * FROM run WHERE radius > ?", (radius,))


class PipeModel(SqliteModel):
    runs = table(Runs)
```

Give the model to the app:
`run(PipeMainView, build_model=PipeModel, setup_model=PipeMainView.connect_model)`.
A `ModelApplication` (`QtModelApplication`, `TextualModelApplication`,
`WebModelApplication`) takes the same arguments. Callbacks that ask for `model` reach the
tables (`model.runs.add(...)`).

- **Transactions.** `with self.connection() as db:` commits once the block ends, and rolls
  back if the block raises. A block inside another block joins it.
- **Settings.** `pragmas` is set on the connection of every study, because SQLite keeps
  these settings per connection, not in the file. Foreign keys and recursive triggers are
  on. `synchronous` is off, because the model's database is a scratch copy and the study file
  is written separately. Override `pragmas` to change them
  (`pragmas = {**SqliteModel.pragmas, "cache_size": -64000}`).
- **Typed rows.** `fetch` and `fetch_one` turn rows into `attrs` instances through the
  `cattrs` converter of the views. `fetch_column` gives the first column of a query, for
  example a list of names. `as_parameters(row)` gives the fields of an instance as the named
  parameters of a query.
- **New names.** `unique_name(db, "run", "name", "Run")` gives "Run", or else "Run 2",
  "Run 3", and so on: the first name that the column doesn't hold, whatever its case. Use it
  for a row that the user adds, then renames.
- **Refusals.** When a constraint fails, the transaction is refused: `connection()` raises a
  `RefusedError` (`composeui.core.model`). Its message is the table's message for the
  constraint, from `refusals`, else the message of SQLite. `refusals` maps a part of the
  SQLite message to a message, for example
  `{"thin_wall": "its wall must be thinner than its radius"}`.
  A view shows the refusal in the status bar with
  `with self.refusing(self.tr("Can't add the pipe: {error}")):`. The message is translated
  too: the catalog check finds the `refusals` of a table in the module of a view. In a
  `cell_edited` or `record_edited` callback, the edit is refused as well.
- **Refreshing views.** The `changed` signal of a table is emitted after a commit that
  changed rows through the table, and after New and Open, once the views are loaded. So the
  views that show the rows can follow. Connect it in `setup_model(main_view, model)`. The
  app calls `setup_model` once the main view and the model are built, and on the web for
  each session. A method of the main view keeps the connection beside the views that it
  refreshes. A view's method that asks for `model` gets it, and `now=True` shows the rows
  right away:

  ```python
  def connect_model(self, model: PipeModel) -> None:  # PipeMainView's
      model.runs.changed.connect(self.show_runs, now=True)
  ```

- **Studies.** New starts an empty database. Save and Open (and `-f`) save and open the
  state of the views and the database together, as a zip archive with the app's `extension`.
  The model works on a scratch copy in a temporary file. So the user's file changes only
  when the user saves it, and a failed save leaves the file whole. Opening checks everything
  first. When a file doesn't fit, the study stays as it was, and the status bar says why.
- **Versions.** Raise `schema_version` with every change to the tables. Add the step from
  the previous version to `migrations` (`{1: add_stress_column}`). When the user opens a
  study saved by an older version, the model brings it up to date. A study saved by a newer
  version is refused.
- **On the web,** the database of each session is deleted with the session.

[`src/examples/pipecatalogue.py`](../src/examples/pipecatalogue.py) puts it together, on
every backend (`uv run python -m examples.pipecatalogue --backend qt`):

- The database checks the pipes of a catalogue as a form in a [sidebar](#sidebar) adds them.
- A [list of views](#a-list-of-views) shows an expander per pipe, beside a tree of the pipes
  by material.
- A filtered query lists the pipes, with their mass from a SQL view that joins them to their
  material.
- Each pipe has an installation date, picked with a `DateInputView`, which the list can
  filter by. Studies saved before the date column existed get the column when they open,
  through a migration.

## Translating the app

Write the app's text in one language in the code, and translate it from JSON catalogs. Each
language has one `<language>.json` file, which maps each text to its translation:

```json
{"Radius": "Rayon", "Main Pipe": "Conduite principale"}
```

Declare the text that a view shows with `T`, where the class of the view declares it. Or
set the text through the `tr` of a view once the view is built. Point the main view at the
directory of the catalogs:

```python
@define_view
class PipeDimensionView(GroupFormView):
    # `child` builds a view field's view with these fields, one per view
    radius: DimensionInputView = child(DimensionInputView, label=T("Radius"))

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Main Pipe")


@define_view
class PipeMainView(MainView):
    app_title = T("Pipe Form")
    translations_dir = Path(__file__).parent / "locales"
```

`tr` returns the translation as a `str` that remembers the text as written. `T` is the
same, but the text is translated once a view keeps it and the main view sets a language.

`main_view.set_language("fr")`, or `--language fr` on the command line, changes the
language. Every view field that keeps such text is then translated again: a label or a
title, a status or validator message, the headers and rows of a table, the labels of a
choice (the keys of `values`). Because the views are reactive, every backend shows the new
text at once. On the web, each session has its own language, and the `<html lang>` of the
page follows it.

Until the language changes, `language` is the app's `source_language` (`"en"`, unless a
main view says otherwise). A regional language (`fr-CA`) falls back on the catalog of its
base language (`fr.json`). Text that no catalog translates shows as written.

- **Formatted text follows too.** `self.tr("Picked {color}").format(color=self.tr("Red"))`
  is formatted again in the new language, and its translated arguments are translated too.
- **Text set without `tr` stays as it is,** and so does text made from a translation
  (`self.tr("Name") + ":"`, an f-string). For text that a view builds from other text,
  override `retranslate`. It runs once when the view is built, then on each change of
  language, once the text is translated.
- **A choice keeps its value.** The value stays selected when its labels change. A study
  saves it by a key that no language changes: the name of an enum member, a string value
  itself, else its position.
- **The titles follow too.** The `title` of the main view, from the `app_title` of its
  class, follows the language when it is declared with `T`. It is the title of the window
  on Qt, of the app in Textual, and the header and `<title>` of the page on the web. The
  `page_title` of a page follows the language too.
- **ComposeUI translates its own text** (the File menu, the OK and Cancel of a dialog) from
  its own catalogs. The app's catalog wins over them.
- **A `LanguageMenu` field of the main view lets the user switch:**
  `language_menu: LanguageMenu = Factory(LanguageMenu)`. It offers `source_language` and a
  language per catalog in `translations_dir`, each named in itself ("Français"). It keeps
  the language shown checked, and it is not study data. A language that it can't name shows
  its code. Name it in a subclass: `names = {**LanguageMenu.names, "eo": "Esperanto"}`.

[`src/examples/pipeform.py`](../src/examples/pipeform.py) is translated into French. Start
it with `uv run python -m examples.pipeform --backend qt --language fr`, or switch from its
Language menu.

### Checking the catalogs

Check the app's catalogs against its code, for example in CI:

```bash
uv run python -m composeui.core.translationcheck examples.pipeform:PipeMainView
```

The check fails:

- on text that a catalog misses, because the text would show as written;
- on a translation whose `{placeholders}` differ from those of the text, because formatting
  it would fail.

It also lists the entries that no code uses any more.

The text that it checks is the literals passed to `tr` or `T` in the source of the views,
plus the text that the views translate as they are built. The second part finds the text
that `tr` gets from a variable, for example the values of an enum.

To start or complete a catalog, `--write fr` first adds the text that `fr.json` misses to the
catalog, translated as `""` for a translator to fill. It creates the file if needed:

```bash
uv run python -m composeui.core.translationcheck examples.pipeform:PipeMainView --write fr
```

- The existing entries are kept.
- A translation left empty counts as missing, and the text shows as written.
- `--write` doesn't add text that the catalog of ComposeUI translates in that language (the
  File menu, OK, and so on).
- A new regional catalog (`fr-CA`) starts from the catalog of its base language.
