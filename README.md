# ComposeUI

A small, framework-agnostic MVVM layer for building desktop UIs in Python. Views are
declared as typed [`attrs`](https://www.attrs.org/) classes; a `Renderer` binds each view to
a concrete toolkit widget ([Qt](https://pypi.org/project/QtPy/) via `qtpy`,
[Textual](https://textual.textualize.io/) in a terminal, or a web page served with
[Starlette](https://www.starlette.io/) and [htmx](https://htmx.org/)); `Signal` objects
carry events between view, model and application code.

> **Status:** early-stage / pre-alpha. The API is small and still moving.

## Why

- **Declarative views.** A view is an `attrs` class with typed fields, no manual widget
  construction or signal wiring.
- **Reactive by construction.** Setting any attribute on a view (`view.text = "..."`)
  automatically pushes the change to its bound renderer. No `update()`/`refresh()` calls
  needed for normal state changes.
- **Toolkit-agnostic core.** `composeui.core` has no import-time dependency on Qt; the Qt
  binding lives entirely in `composeui.qtcore` and is only imported when a view actually
  renders with `RendererType.QT`.
- **Typed callback injection.** `Signal.connect` and `Application.connect` inspect a
  callback's parameter names and inject `view`/`main_view`/`model` automatically when
  requested, so callbacks stay short and don't need manual lookups.

## Installation

Not yet published to PyPI. Clone the repository and install with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/ehmoussi/composeui3
cd composeui3
uv sync                     # core dependencies
uv sync --extra pyside6     # + PySide6, needed to actually render a window
uv sync --extra tui         # + Textual, for the terminal backend
uv sync --extra web         # + Starlette/uvicorn, for the web backend
uv sync --extra report      # + matplotlib, for charts' report images
```

Requires Python >= 3.9.

## Quickstart

A minimal window with a text input that greets you in the status bar as you type:

```python
from attrs import Factory

from composeui.core.application import run
from composeui.core.view import InputView, MainView, define_view


@define_view
class GreetingInputView(InputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.placeholder = "Type your name..."
        self.text_edited.connect(self._on_name_changed)

    # `main_view` is injected automatically because it's a requested parameter.
    def _on_name_changed(self, text: str, *, main_view: MainView) -> None:
        main_view.status_bar.show_message(f"Hello, {text}!" if text else "")


@define_view
class HelloMainView(MainView):
    app_title = "Hello ComposeUI"
    extension = ".hello"  # of its study files

    greeting: GreetingInputView = Factory(GreetingInputView)


if __name__ == "__main__":
    run(HelloMainView)
```

Run it with `uv run python hello.py --backend qt` (requires the `pyside6` extra installed),
`--backend textual` (the `tui` extra) or `--backend web`, the default (the `web` extra).
`run` imports only the backend chosen, and leaves the rest of the command line to its app
(`--help` lists it). To always start one backend, build its application yourself:
`QtApplication(build_main_view=HelloMainView).run()`.

For a larger, real-world-shaped example with forms, radio groups, a checkbox, a read-only
table, validation, and a file menu with save/load, see [`src/examples/pipeform.py`](src/examples/pipeform.py) (`uv run python -m
examples.pipeform --backend qt`, or `textual`, or `web`).

## Web backend

The same views can be served as a web page instead of a window: `run(HelloMainView)`
serves http://127.0.0.1:8000 (`--host`/`--port` to change), as does
`WebApplication(build_main_view=HelloMainView).run()`. Every application takes a function
building the main view, because on the web every browser gets its own copy of it.

Run it with `uv run python hello.py` (requires the `web` extra). Pages are rendered on the
server and updated with [htmx](https://htmx.org/): editing a field posts it, and the
response swaps in every part of the page that changed (here, the status bar), never the
field being typed in. Styles ([daisyUI](https://daisyui.com/) on Tailwind) and htmx are
served by the app itself, so it also works offline. For a fuller example, see
[`src/examples/webhello.py`](src/examples/webhello.py) (`uv run python -m
examples.webhello`), and `pipeform.py` with `--backend web`.

How it differs from a desktop window:

- **One app state per browser.** A signed session cookie gives each browser its own main
  view; tabs of the same browser share it. Sessions live in the server's memory: a restart
  starts them all over, and idle ones are dropped after an hour (`session_ttl`).
- **Wire behavior inside the views,** as above, with `app.connect`, or in
  `WebApplication.setup_session`, which runs for each new session's main view.
  `app.connect(view=app.main_view...)` is replayed on every new session: the callback gets
  that session's own `view` and `main_view`, never the template no browser displays.
- **Models are per session too:** `run(..., build_model=..., setup_model=...)` (or
  `WebModelApplication`, which takes the same arguments) builds one model per session,
  wired to its main view by `setup_model`, and callbacks asking for `model` get their
  session's. A model shared between browsers would leave the others showing stale views,
  since each browser only sees what its own requests return.
- **Save and Open** download the state as a file and upload one; the File menu sits in the
  page header. Its shortcuts use Alt+Shift (Alt+Shift+S saves) because browsers keep the
  Ctrl ones for themselves.
- **`--reload` restarts the server when a Python file under the current directory
  changes,** for development. The new server process runs the program again (the script,
  or the `-m` module) to rebuild its app, with the same command line. Every restart
  drops the sessions.
- **Pages have their own address.** With a router (see [Pages](#pages)), each page is at
  `/<route>`, and `/` sends the browser to the first page. The pages' toolbar sits in the
  header; changing pages puts the new address in the browser's history, so back, forward,
  bookmarks and reloads land on that page. A route can't be `icon`, `jobs`, `state`,
  `static` or `widget`, which the backend uses.
- **Icons** are the image files actions name (`action.icon = "icons/run.svg"`, the path
  Qt reads), served by the backend. An SVG is drawn in the text's color, so it follows
  the light and dark themes: only its shape counts, as with a Lucide or Material icon.
  PNG, JPEG, GIF, WebP and ICO files show as they are.
- Single process only, and no push from the server: the page changes in response to the
  user's own actions, with two exceptions. A status bar message clears itself after its
  timeout, and while [jobs](#running-work-in-threads) run, the page asks every second
  for what their results changed.

## Core concepts

| Concept | Role |
| --- | --- |
| `View` (`composeui.core.view`) | A typed `attrs` data class describing UI state (`MainView`, `InputView`, `FormView`, `ActionView`, etc). Composed by nesting view fields inside other views. |
| `Signal` (`composeui.core.signal`) | A typed event emitter. `signal.connect(callback)` supports callbacks that optionally take `view`, `main_view`, and/or `model` keyword arguments, injected automatically, on the views' signals and the model's alike. A callback may take fewer of the signal's arguments than it emits (the first ones, or none), and `connect(callback, now=True)` also calls it once right away. |
| `Renderer` / `RendererContainer` (`composeui.core.renderer`) | Binds a `View` to a concrete toolkit widget and keeps them in sync in both directions (`refresh_attribute` / `update_state`). |
| `Application` / `ModelApplication` (`composeui.core.application`) | Owns the `MainView` (and optionally a `Model`), parses CLI args (`--debug`, `--log`, `--log-signals`, `-f FILE`), and drives rendering. A `MainView` adds options of its own with its `add_arguments` classmethod and gets their values in `apply_arguments`, once it's wired (for every session on the web). |
| `Model` (`composeui.core.model`) | Base class for the app's data, meant to be subclassed; `SqliteModel` keeps it in a [SQLite database](#a-sqlite-model). |
| `Jobs` (`composeui.core.jobs`) | `main_view.jobs`: functions [run in threads](#running-work-in-threads), their results emitted on the main thread. |

Views can be composed by mixing traits, for example `LabelRowFloatInputView` combines
`FormLabelRowView` and `FloatInputMixin`; a labelled row's `help` says what to enter, shown
by a "?" button beside its label that a click, a tap or the keyboard opens (a hint under the
label on Textual).
See the mixins in `composeui/core/view.py` (`InputMixin`, `FloatInputMixin`,
`IntInputMixin`, `SliderMixin`, `CheckBoxMixin`, `ValuesGroupMixin`, `TableMixin`,
`LogMixin`, `LabelMixin`, `MarkdownMixin`) for the available building blocks,
`PageView`/`Router` for an app split into [pages](#pages), `TabView` for [tabs](#tabs),
`ToolBar` for a [toolbar](#toolbars), `DialogView` for [dialogs](#dialogs), `SidebarView`
for a [sidebar](#sidebar), and `ButtonView` for a button the user clicks (`clicked`),
e.g. under a form to submit it; its `variant` (`ButtonVariant`: primary, secondary,
danger) tells the main action from the others and from one destroying something.
`IntInputView` takes a whole number, e.g. an hour of the day, between its `minimum` and
`maximum`: a spin box on Qt, keeping it in range; elsewhere a text field for digits,
where a number out of range isn't refused (Textual marks it), so validate it.
`SliderView` picks a whole number by dragging a handle, e.g. a number of workers: from
`minimum` to `maximum` by `step`, its value shown beside the track, so its row is no
taller than the others; the handle only stops on a step, and `value_changed` reports the
user's moves.
`ProgressBarView` shows how far a long task has gone: `value` steps out of `maximum`, or
a bar that only shows the task runs while `maximum` is `None`.
`MetricView` shows a figure read at a glance, e.g. the jobs running: its `label`, its
`value` in large type, and its change since some point (`delta`, then `delta_text`, e.g.
"since yesterday") as a badge colored by its sign; a row of them in a `HorizontalView`.
`ExpanderView` is a collapsible section, e.g. a record's details with its Edit and Delete
buttons: a subclass's view fields, one above the other, shown only while `is_expanded`,
under its `title`, which the user clicks to expand or collapse it (`toggled`).
`TreeView` shows `nodes` in a tree, e.g. a site's buildings, floors and rooms: each a
`TreeNode` with its `label` and `children`, known by its path, the `key`s (its label unless
given) from its top-level node down to it, e.g. `("Building A", "Floor 1")`. The user
expands and collapses the nodes (`expanded`, `toggled`) and selects one (`selected`,
`selection_changed`); new `nodes` keep the paths still in them.
[`src/examples/pipecatalogue.py`](src/examples/pipecatalogue.py) shows its pipes in one,
under their material, rebuilt from the database's whenever they change.
`MarkdownView` shows read-only Markdown `text`, e.g. a help page or a report's summary;
its links open in the browser. On the web its raw HTML is left out, so the text can't
inject markup; [`src/examples/pipeform.py`](src/examples/pipeform.py) has a help page, and
[`src/examples/markdownviewer.py`](src/examples/markdownviewer.py) shows a Markdown file
(`uv run python -m examples.markdownviewer --markdown README.md --backend qt`).
An app without studies sets `has_file_menu = False` on its `MainView`, leaving out the
File menu (New, Open, Save, Save As, Exit).
`PickFileAction` is a menu or toolbar action picking a file for the app to read (not a
study): `extensions` names the types it offers, e.g. `{"Markdown": (".md",)}`, and
`file_picked` emits the file's path. On the web the browser uploads the file, and the
path is a copy, gone once the callbacks have run.
[`src/examples/taskview.py`](src/examples/taskview.py) follows tasks running in
[threads](#running-work-in-threads) with one (`uv run python -m examples.taskview`, or
`--backend qt`, or `textual`).

## Pages

A `Router` shows one page at a time and adds a toolbar with an entry per page. Each page
is a `PageView` with a `route`, a unique name made of letters, digits, `_` and `-`, and a
`page_title`, its toolbar entry. Its view fields are its content, laid out in a column:

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

Clicking a toolbar entry, which triggers the page's `action`, shows its page. Code can do
the same with `pages.navigate("results")`, and react to it through `pages.route_changed`.
Which page is shown is navigation, not study data: saving, opening and New leave it alone.
Qt docks the toolbar as a `QToolBar`, Textual shows a row of buttons at the top, and the
web puts it in the page header, with a web address per page. See
[`src/examples/pipeform.py`](src/examples/pipeform.py) for an app with two pages.

## Tabs

A `TabView` shows its views a tab at a time, picked from a row of tabs, e.g. a record's
details and its history. Its `TabPage` fields are the tabs, in order, each with its
`title` on its tab and its view fields as its content, in a column:

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

It starts on the first tab. Code shows another with `current_index` (counted from 0;
`current_tab` is the tab shown) and reacts to the user's picks through
`current_changed`. Which tab shows is navigation, not study data, as for pages. A hidden
tab page hides its tab, and a disabled one can't be picked. Distinct from
[pages](#pages): tabs live inside a page or a form and have no address of their own.
Qt shows a `QTabWidget`, Textual a `TabbedContent`, and the web a row of tabs the arrow
keys move between. [`src/examples/pipechart.py`](src/examples/pipechart.py) shows its
chart on one tab and the measurements plotted on it, as a table, on another.

## Toolbars

A `ToolBar` is a row of the actions the user runs most, docked at the top of the window.
Its `ActionView` and `SeparatorAction` fields are its entries, in order; make it a field of
the main view:

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

Clicking an entry triggers its action, a checkable one shows as pressed while checked,
and disabling the toolbar disables its entries. Qt docks it as a `QToolBar`, Textual shows
a row of buttons at the top, above a router's, and the web puts its buttons in the page
header, before the menus. An action's `icon`, an image file's path, shows on Qt and the
web (see [Web backend](#web-backend)); a terminal shows the text. An icon is set by the
app's code, not study data: never saved, loaded or reset.

## Sidebar

A `SidebarView` is a column of views beside the pages, shown whatever the page, e.g. a
form creating a record. Its view fields are its content, under its `title`; make it a
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

Qt docks it on the window's left, where the user can't close or move it, Textual shows it
left of the content, and the web a column left of the pages. The user retracts it, and
expands it back, with a button named by `toggle_text`: an arrow in its header on Qt and
Textual, leaving a narrow strip, and a button in the page header on the web. Code does the
same with `is_expanded`, and reacts to the user's toggles through `toggled`; whether it's
retracted is layout, not study data. On a phone, the web shows it as a drawer over the
page, opened by the header's button and closed by a tap beside it or Escape. In
[`src/examples/pipecatalogue.py`](src/examples/pipecatalogue.py), the sidebar's form adds
pipes to the catalogue beside it.

## Dialogs

A `DialogView` is a modal message, or a confirmation with an accepting and a rejecting
button (`kind=DialogKind.CONFIRM`). It starts closed; `open()` shows it. Nothing waits
for the answer, since a web request can't: connect to `accepted` and `rejected` instead,
fired once the dialog is closed.

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

Escape, or closing the dialog's window, rejects a confirmation and accepts a message,
which has only one answer. A dialog isn't study data: saving, opening and New leave it
alone. Qt shows a `QMessageBox`, Textual a modal screen, and the web a modal `<dialog>`,
wherever the view is in the tree. In [`src/examples/pipeform.py`](src/examples/pipeform.py),
the Pipe menu's Reset Dimensions asks for a confirmation first.

A `FormDialogView` holds a form, e.g. editing a record from its Edit button, with OK and
Cancel; a subclass gives its form as its `form` field, and its `text` shows above it:

```python
@define_view
class EditPipeDialog(FormDialogView):
    form: PipeForm = Factory(PipeForm)  # a FormView, with its checks
```

OK can't be pressed while a check of the form fails (`is_accept_enabled` follows the
checks as they run), and accepting runs every check first, staying open while one fails,
even one the user hasn't triggered yet (`FormView.check` runs them all, `is_valid` tells
whether they pass). The answer comes through `accepted` or `rejected`; the form keeps its
values, for the app to read once accepted, or to fill before `open()`. In
[`src/examples/pipecatalogue.py`](src/examples/pipecatalogue.py), each pipe's Edit button
changes it in a form dialog.

## Translating the app

Write the app's text in one language in the code and translate it from JSON catalogs, one
`<language>.json` file per language mapping each text to its translation:

```json
{"Radius": "Rayon", "Main Pipe": "Conduite principale"}
```

Declare the text a view shows with `T` where the view's class declares it, or set it
through a view's `tr` once the view is built, and point the main view at the catalogs'
directory:

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

`tr` returns the translation as a `str` that remembers the text as written; `T` is the
same, translated once a view keeps it and the main view sets a language. When
`main_view.set_language("fr")` (or `--language fr` on the command line) changes the
language, every view field keeping such text is translated again: a label or a title, a
status or validator message, a table's headers and rows, a choice's labels (the keys of
`values`). The views being reactive, every backend shows the new text at once; on the web,
each session has its own language, and the page's `<html lang>` follows it. Until then,
`language` is the app's `source_language` (`"en"` unless a main view says otherwise). A
regional language (`fr-CA`) falls back on its base language's catalog (`fr.json`), and
text no catalog translates shows as written.

- Formatted text follows too: `self.tr("Picked {color}").format(color=self.tr("Red"))`
  is formatted again in the new language, its translated arguments translated as well.
- Text set without `tr`, or made from a translation (`self.tr("Name") + ":"`, an f-string),
  stays as it is. For text a view builds from other text, override `retranslate`: it runs
  once as the view is built, then on each language change, once the text is translated.
- A choice's value stays selected when its labels change, and a study saves it by a key no
  language changes (an enum member's name, a string value itself, else its position).
- The main view's `title`, its class's `app_title`, follows a language too when declared
  with `T`: the window's title, the app's in Textual, the page's header and `<title>` on
  the web. So does a page's `page_title`.
- ComposeUI translates its own text (the File menu, a dialog's OK and Cancel) from its own
  catalogs; the app's catalog wins over them.
- A `LanguageMenu` field of the main view lets the user switch:
  `language_menu: LanguageMenu = Factory(LanguageMenu)`. It offers `source_language` and a
  language per catalog in `translations_dir`, each named in itself ("Français"), keeps the
  one shown checked, and isn't study data. A language it can't name shows its code: name
  it in a subclass, `names = {**LanguageMenu.names, "eo": "Esperanto"}`.

[`src/examples/pipeform.py`](src/examples/pipeform.py) is translated into French: start it
with `uv run python -m examples.pipeform --backend qt --language fr`, or switch from its
Language menu.

Check the app's catalogs against its code, e.g. in CI:

```bash
uv run python -m composeui.core.translationcheck examples.pipeform:PipeMainView
```

It fails on text a catalog misses (it would show as written) and on a translation whose
`{placeholders}` differ from the text's (formatting it would fail), and lists the entries
no code uses any more. The text is the literals passed to `tr` or `T` in the views'
source, plus the text the views translate as they are built, which finds the text `tr`
gets from a variable, e.g. an enum's values.

To start or complete a catalog, `--write fr` first adds the text `fr.json` misses to it,
translated as `""` for a translator to fill (it creates the file if needed):

```bash
uv run python -m composeui.core.translationcheck examples.pipeform:PipeMainView --write fr
```

Its entries are kept. A translation left empty counts as missing, and the text shows as
written. Text ComposeUI's own catalog translates in that language (the File menu, OK...)
isn't added, and a new regional catalog (`fr-CA`) starts from its base language's.

## Saving and loading state

`MainView.save_state(path)` and `MainView.load_state(path)` (de)serialize the full view tree
to JSON via `cattrs`, automatically skipping `Signal`/`Renderer` fields and, on load, updating
the live view tree in place so renderer bindings and signal connections survive the reload.
Text the user reads rather than enters (labels, titles, headers, button and menu text) is
tagged `UI_TEXT` and skipped too: it comes from the app's code, in its language, not from a
study. Tag a text field of your own views the same way:
`attrs.field(default="", metadata={UI_TEXT: True})`.

## A SQLite model

Views hold what is shown. Data with many rows, relations between them, and queries over
them (runs and their results, a catalogue of parts) belongs in a `SqliteModel`: a SQLite
database of the app's own, with its own schema and SQL, saved and opened with the study.

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

Give it to the app, `run(PipeMainView, build_model=PipeModel,
setup_model=PipeMainView.connect_model)` (or a `ModelApplication`: `QtModelApplication`, `TextualModelApplication`,
`WebModelApplication`, taking the same arguments), and callbacks asking for `model` reach
the tables (`model.runs.add(...)`):

- **Transactions.** `with self.connection() as db:` commits once the block ends and rolls
  back if it raises; a block inside another joins it.
- **Settings.** `pragmas` is set on every study's connection, since SQLite keeps these
  per connection rather than in the file: foreign keys and recursive triggers on, and
  `synchronous` off, since the model's database is a scratch copy and the study file is
  written apart. Override it to change them (`pragmas = {**SqliteModel.pragmas,
  "cache_size": -64000}`).
- **Typed rows.** `fetch` and `fetch_one` turn rows into `attrs` instances through the
  views' `cattrs` converter, and `fetch_column` gives a query's first column (a list of
  names); `as_parameters(row)` gives an instance's fields as a query's named parameters.
- **New names.** `unique_name(db, "run", "name", "Run")` gives "Run", or else "Run 2",
  "Run 3"... the first name the column doesn't hold, whatever its case: a row the user
  adds, then renames.
- **Refusals.** A constraint failing refuses the transaction: `connection()` raises a
  `RefusedError` (`composeui.core.model`) with the table's message for it, from
  `refusals` (`{"thin_wall": "its wall must be thinner than its radius"}`, by a part of
  SQLite's message), else SQLite's. A view shows it in the status bar with
  `with self.refusing(self.tr("Can't add the pipe: {error}")):`, the message translated
  too (a catalog's check finds a table's `refusals` in a view's module); in a
  `cell_edited` or `record_edited` callback, the edit is refused as well.
- **Refreshing views.** A table's `changed` signal is emitted after a commit that changed
  rows through it, and after New and Open once the views are loaded too, so the views
  showing the rows can follow: connect it in `setup_model(main_view, model)`, which the
  app calls once both are built, and on the web for each session. A method of the main
  view keeps it beside the views it refreshes; a view's method asking for `model` is
  given it, and `now=True` shows the rows right away:

  ```python
  def connect_model(self, model: PipeModel) -> None:  # PipeMainView's
      model.runs.changed.connect(self.show_runs, now=True)
  ```
- **Studies.** New starts an empty database, and Save and Open (and `-f`) save and open
  the views' state and the database together, as a zip archive under the app's
  `extension`. The model works on a scratch copy in a temporary file, so the user's file
  only changes when saved, and a failed save leaves it whole. Opening checks everything
  first: a file that doesn't fit leaves the study as it was and says why in the status bar.
- **Versions.** Raise `schema_version` with every change to the tables and add the step
  from the previous version to `migrations` (`{1: add_stress_column}`): a study saved by an
  older version is brought up to date when opened, and one saved by a newer version is
  refused.
- On the web, each session's database is deleted with the session.

[`src/examples/pipecatalogue.py`](src/examples/pipecatalogue.py) puts it together, on
every backend (`uv run python -m examples.pipecatalogue --backend qt`): a catalogue of
pipes the database checks as they're added, from a form in a [sidebar](#sidebar), listed
an expander each in a [list of views](#a-list-of-views) beside a tree of them by material,
through a filtered query with their mass from a SQL view joining them to their material.

## A table of records

A `TableView` shows text the app formats itself. A `RecordTableView` shows `attrs`
records, such as the ones `fetch` returns, a column per field:

```python
from composeui.core.view import Column, RecordTableView, T, child

runs: RecordTableView[Run] = child(
    RecordTableView[Run],
    columns=[Column("id", T("Run")), Column("radius", T("Radius"), editable=True)],
)
```

Assign `records` to update it (`table.records = model.runs.above(0.1)`) and read
`selected_record` (or `selected_records`). An edited cell is parsed into its field's type
through the views' `cattrs` converter, and `record_edited` emits the old and the new record;
a cell that doesn't parse refuses the edit and says why in the status bar. The records are
saved and loaded with the study by their type, so build the table as
`RecordTableView[Run]` (or subclass it).

### Sorting and filtering

A column the user sorts and filters is marked so, `Column("radius", T("Radius"),
sortable=True, filterable=True)` (on a `TableView`, `sortable_columns` and
`filterable_columns` list them). Clicking a sortable header sorts by it, ascending, then
descending, then back in the app's order. While a column is filterable, a bar above the
table has a search over the filterable columns' text, and "+ Filter", adding a filter on
a column, shown as a chip, which a click (or Enter, the focus landing on it) opens to edit:

- in a text column, ignoring case: the cells containing the text, or `=kitchen` equal to
  it, `!=kitchen` not equal, `!kit` not containing it, `kit*` starting with it, `*en`
  ending with it; with the editor's `.*` toggle on, the cells matching a regular
  expression, e.g. `Room [1-3]` (the chip reads "Room matches Room [1-3]"; the app sets
  one as `as_pattern("Room [1-3]")`, between slashes);
- in a number or a date column, `>20`, `>=20`, `<20`, `<=20`, `!=20`, a range `18..24`
  (both ends included), or a bare value meaning `=`;
- in a boolean column, `true` or `false`;
- in any column, `=` alone: the empty cells.

A `RecordTableView` sorts by the fields' values, so numbers and dates sort as such; a
`TableView` sorts its text. The app sets the order and the filters too (`sort_column`,
`sort_descending`, `search`, `filters`, or `sort_by(column)` as a click does), and they're
saved with the study. `shown_rows` lists the rows shown, in order, as indexes into `rows`;
`selected_rows`, `selection_changed` and the edited row keep meaning indexes into `rows`
whatever the order, and a search or a filter hiding a selected row deselects it.

## A list of views

A `ListView` shows a view per record, one above the other, e.g. an expander per record
with its details and its Delete button. A subclass builds a record's view; setting `items`
to the records, e.g. the model's, shows them:

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

A new record gets a view of its own, a record gone takes its view along, and a record
still there keeps its view, told apart by `item_key` (the record itself by default). A
record changed keeps its view if `update_item` shows the change in it and returns True,
so the view keeps what the user did to it (an expander stays expanded); otherwise it gets
a new view. A view built later is set up like the others: its signals pass `main_view`
and `model` to the callbacks asking for them, and it shows the main view's language. The
records and their views are the model's, not study data: saving, opening and New leave
them alone. On the web, a change swaps only the records' views it adds or removes, never
the others, unless it reorders them. However many records there are, the list stays
compact: on Qt it scrolls within itself, taking the page's spare height, and expanders
in a list join in one box on the web, a line apart on Textual.
[`src/examples/pipecatalogue.py`](src/examples/pipecatalogue.py) lists its pipes this
way, each with a Delete button.

## Charts

A `ChartView` plots results, e.g. a quantity against time or a swept dimension: a list of
`Series`, each a curve with its own `x` and `y` (as many of each) and a `name` for the
legend; a NaN leaves a gap in its curve. The chart's `kind` (`ChartKind`) draws them as
lines (`LINE`, the default) or dots (`SCATTER`), and a series' own `kind` overrides it,
e.g. measurements as dots over a model's curve. A `BAR` chart draws values per case: a
group of bars for each of its `categories`, one per series, each series' x naming a
category by its index and its y the bar's height.

`x_log` and `y_log` make an axis a log axis, which leaves out what it can't show: a point
at an x of 0 or less isn't drawn, and a y of 0 or less leaves a gap.

```python
energy: ChartView = child(
    ChartView,
    kind=ChartKind.BAR,
    y_unit="kWh",
    categories=["Kitchen", "Bedroom", "Office"],
    series=[Series(name="Heating", x=[0, 1, 2], y=[120, 80, 95])],
)
```

```python
from composeui.core.view import ChartView, Series, child

chart: ChartView = child(
    ChartView, title="Pressure Drop", x_title="Flow Rate", x_unit="L/s", y_unit="kPa"
)

chart.series = [*chart.series, Series(name="D = 50 mm", x=flows, y=drops)]
```

The view holds data and labels: each backend draws it in its theme's colors, unless a
series has a `color` of its own (`"#rrggbb"`, the same in every theme, e.g. a logo's), and
`fill=True` fills between its line and 0 in it. `height` sets its height on screen, in
pixels (a terminal's rows of about 16), e.g. to keep a shape's proportions; `None`, the
default, leaves it to the backend. Like a
table's rows, assign a new `series` list to redraw it (a job adding points too), and the
series are saved with the study. Qt draws it with [pyqtgraph](https://www.pyqtgraph.org/)
(in the `pyside6` extra): the mouse zooms and pans, and hovering shows each series' value
at the cursor. The web draws it with [uPlot](https://github.com/leeoniya/uPlot), loaded by
the page once it shows a chart: dragging across zooms, a double click zooms back out, and
the legend shows the values at the cursor; a long series is thinned to the extremes of
each bucket of its points before it's sent. Textual draws it with `textual-plotext` (in the
`tui` extra), without zoom or hover. A new `series` list keeps the user's zoom.
[`src/examples/pipechart.py`](src/examples/pipechart.py) plots a pipe's pressure drop
against its flow rate, and measurements over it (`uv run python -m examples.pipechart
--backend qt`, or `textual`, or `web`).

A click on the chart emits its point, in the axes' values, from `clicked` (`x`, then `y`):
in Qt, and on the web, where a drag still zooms; a terminal has no pointer to click with.
[`src/examples/batman.py`](src/examples/batman.py) draws the Batman logo, in its own
yellow and black, and says whether a click was on the bat (`uv run python -m examples.batman --backend web`, or `qt`).

### Report images

A screen chart follows its window and theme; a report's figure has the page's size and
fonts and a light background. `composeui.core.chartimage` draws one from the chart's
data with matplotlib (the `report` extra), the same whatever the backend, and without any
UI, e.g. a batch run writing a report's figures:

```python
from composeui.core.chartimage import ImageOptions, chart_figure, save_chart_image

save_chart_image(chart, Path("drop.pdf"), ImageOptions(width_mm=80, font_size=8))
figure = chart_figure(chart)  # a matplotlib `Figure`, to annotate before saving it
```

The suffix picks the format: PDF, SVG and EPS keep their text as text, PNG is drawn at
`dpi`; `x_range` and `y_range` show a region of the data. Each backend offers it as Save
Image (its text translated like the other built-in ones): in Qt's chart context menu, at
the region shown; in the web figure's corner, with a format to pick, at the user's zoom;
with the `s` key on a Textual chart. Without the extra, Qt keeps pyqtgraph's own Export,
and the web page draws a PNG of the chart itself.

## Running work in threads

A long computation would freeze the app while it runs. `main_view.jobs.start(work, *args)`
runs `work(job, *args)` in a thread of its own instead. The function must not touch a
view, since a toolkit's widgets belong to the main thread: it returns its result, which
its job's `finished` signal emits on the main thread, where the callbacks update the views:

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

- **Failures.** What the function raises is logged and emitted by the job's `failed`.
- **Canceling.** `job.cancel()`, or `jobs.cancel()` for them all, asks the functions to
  stop: Python can't stop a thread, so each one checks `job.is_canceled`, or waits with
  `job.sleep(seconds)`, which returns False once canceled. It still finishes, and
  `finished` emits what it returned.
- **On the main thread only.** Call `jobs.start`, `jobs.cancel` and `jobs.drop` from a
  callback, never from a job's function: the jobs aren't locked, since the main thread
  alone changes them (`job.cancel()` works from any thread). Called from a job's function,
  they raise `CalledInJobError`: to start another job, return what it needs, and start it
  from the callback getting it.
- **Running or not.** `jobs.is_running` tells whether any job is running, and
  `jobs.running_changed` emits it as it changes, e.g. to disable a Run button.
- **New, Open and closing the app** cancel the jobs running and drop their results: they
  belong to the study replaced. Closing doesn't wait for them either.
- **Callbacks** connected to a job's signals get the `main_view` and `model` they ask for,
  as any signal's.
- **On the web,** the page asks the server for what the jobs changed every second while
  any is running, and stops once they are over.
- **Tests.** A main view no toolkit shows emits its jobs' results when the test calls
  `main_view.jobs.wait()`, on the test's thread.

[`src/examples/taskview.py`](src/examples/taskview.py) runs 25 jobs at once, and cancels
them.

## Development

```bash
uv sync --group dev --all-extras   # every backend: the tests cover Qt, Textual and web
make lint    # ruff format + check --fix
make mypy    # project-wide mypy (Qt bindings resolved to PySide6)
make test    # pytest with coverage
make check   # lint + mypy
make all     # clean + check + test
```

The project lints with `ruff` (`select = ["ALL"]`) and type-checks with `mypy`; both are
expected to pass cleanly before committing.

## License

MIT, see [`LICENSE`](LICENSE).
