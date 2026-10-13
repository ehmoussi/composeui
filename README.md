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
```

Requires Python >= 3.9.

## Quickstart

A minimal window with a text input that greets you in the status bar as you type:

```python
from attrs import Factory

from composeui.core.view import InputView, MainView, define_view
from composeui.qtcore.qtapplication import QtApplication


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
    greeting: GreetingInputView = Factory(GreetingInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Hello ComposeUI", extension=".hello")


class HelloApp(QtApplication[HelloMainView]):
    def __init__(self) -> None:
        super().__init__(main_view=HelloMainView())


if __name__ == "__main__":
    HelloApp().run()
```

Run it with `uv run python hello.py` (requires the `pyside6` extra installed).

For a larger, real-world-shaped example with forms, radio groups, a checkbox, a read-only
table, validation, and a file menu with save/load, see [`src/examples/pipeform.py`](src/examples/pipeform.py) (`uv run python -m
examples.pipeform --backend qt`, or `textual`, or `web`).

## Web backend

The same views can be served as a web page instead of a window. Only the application
changes: a `WebApplication` takes a function building the main view, because every
browser gets its own copy of it.

```python
from composeui.webcore.webapplication import WebApplication


class WebHelloApp(WebApplication[HelloMainView]):
    def __init__(self) -> None:
        super().__init__(build_main_view=HelloMainView)


if __name__ == "__main__":
    WebHelloApp().run()  # serves http://127.0.0.1:8000 (--host/--port to change)
```

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
- **Models are per session too:** `WebModelApplication(build_main_view=..., build_model=...)`
  builds one model per session, and callbacks asking for `model` get their session's. A
  model shared between browsers would leave the others showing stale views, since each
  browser only sees what its own requests return.
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
  bookmarks and reloads land on that page. A route can't be `icon`, `state`, `static` or
  `widget`, which the backend uses.
- **Icons** are the image files actions name (`action.icon = "icons/run.svg"`, the path
  Qt reads), served by the backend. An SVG is drawn in the text's color, so it follows
  the light and dark themes: only its shape counts, as with a Lucide or Material icon.
  PNG, JPEG, GIF, WebP and ICO files show as they are.
- Single process only, and no push from the server: the page changes in response to the
  user's own actions (a status bar message still clears itself after its timeout).

## Core concepts

| Concept | Role |
| --- | --- |
| `View` (`composeui.core.view`) | A typed `attrs` data class describing UI state (`MainView`, `InputView`, `FormView`, `ActionView`, etc). Composed by nesting view fields inside other views. |
| `Signal` (`composeui.core.signal`) | A typed event emitter. `signal.connect(callback)` supports callbacks that optionally take `view`, `main_view`, and/or `model` keyword arguments, injected automatically. |
| `Renderer` / `RendererContainer` (`composeui.core.renderer`) | Binds a `View` to a concrete toolkit widget and keeps them in sync in both directions (`refresh_attribute` / `update_state`). |
| `Application` / `ModelApplication` (`composeui.core.application`) | Owns the `MainView` (and optionally a `Model`), parses CLI args (`--debug`, `--log`, `--log-signals`, `-f FILE`), and drives rendering. |
| `Model` (`composeui.core.model`) | Base class for the app's data, meant to be subclassed; `SqliteModel` keeps it in a [SQLite database](#a-sqlite-model). |

Views can be composed by mixing traits, for example `LabelRowFloatInputView` combines
`FormLabelRowView` and `FloatInputMixin`. See the mixins in `composeui/core/view.py`
(`InputMixin`, `FloatInputMixin`, `CheckBoxMixin`, `ValuesGroupMixin`, `TableMixin`,
`LogMixin`, `LabelMixin`) for the available building blocks, `PageView`/`Router` for
an app split into [pages](#pages), `ToolBar` for a [toolbar](#toolbars), `DialogView`
for [dialogs](#dialogs), and `ButtonView` for a button the user clicks (`clicked`), e.g.
under a form to submit it; its `variant` (`ButtonVariant`: primary, secondary, danger)
tells the main action from the others and from one destroying something.

## Pages

A `Router` shows one page at a time and adds a toolbar with an entry per page. Each page
is a `PageView` with a route, a unique name made of letters, digits, `_` and `-`. Its view
fields are its content, laid out in a column:

```python
from attrs import Factory

from composeui.core.view import MainView, PageView, Router, TableView, define_view


@define_view
class ResultsPage(PageView):
    summary: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_route("results")
        self.title = "Results"  # its toolbar entry


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

## Translating the app

Write the app's text in one language in the code and translate it from JSON catalogs, one
`<language>.json` file per language mapping each text to its translation:

```json
{"Radius": "Rayon", "Main Pipe": "Conduite principale"}
```

Set the text a view shows through `tr`, wherever you set it, and point the main view at the
catalogs' directory:

```python
@define_view
class PipeDimensionView(GroupFormView):
    radius: DimensionInputView = Factory(DimensionInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Main Pipe")
        self.radius.label = self.tr("Radius")


@define_view
class PipeMainView(MainView):
    translations_dir = Path(__file__).parent / "locales"
```

`tr` returns the translation as a `str` that remembers the text as written. When
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
- The main view's `title`, set once as the app starts (`_init_app_info`), follows a
  language too when set with `tr`: the window's title, the app's in Textual, the page's
  header and `<title>` on the web.
- ComposeUI translates its own text (the File menu, a dialog's OK and Cancel) from its own
  catalogs; the app's catalog wins over them.

[`src/examples/pipeform.py`](src/examples/pipeform.py) is translated into French: start it
with `uv run python -m examples.pipeform --backend qt --language fr`, or switch from its
Language menu, which calls `set_language` and checks the language shown.

Check the app's catalogs against its code, e.g. in CI:

```bash
uv run python -m composeui.core.translationcheck examples.pipeform:PipeMainView
```

It fails on text a catalog misses (it would show as written) and on a translation whose
`{placeholders}` differ from the text's (formatting it would fail), and lists the entries
no code uses any more. The text is the literals passed to `tr` in the views' source, plus
the text the views translate as they are built, which finds the text `tr` gets from a
variable, e.g. an enum's values.

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

from composeui.core.sqlitemodel import SqliteModel, SqliteTable


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
    def __init__(self) -> None:
        super().__init__()
        self.runs = self.add_table(Runs)
```

Give it to a `ModelApplication` (`QtModelApplication`, `TextualModelApplication`,
`WebModelApplication`), and callbacks asking for `model` reach the tables
(`model.runs.add(...)`):

- **Transactions.** `with self.connection() as db:` commits once the block ends and rolls
  back if it raises; a block inside another joins it.
- **Settings.** `pragmas` is set on every study's connection, since SQLite keeps these
  per connection rather than in the file: foreign keys and recursive triggers on, and
  `synchronous` off, since the model's database is a scratch copy and the study file is
  written apart. Override it to change them (`pragmas = {**SqliteModel.pragmas,
  "cache_size": -64000}`).
- **Typed rows.** `fetch` and `fetch_one` turn rows into `attrs` instances through the
  views' `cattrs` converter; `as_parameters(row)` gives an instance's fields as a query's
  named parameters.
- **Refusals.** A constraint failing refuses the transaction: `connection()` raises a
  `RefusedError` (`composeui.core.model`) with the table's message for it, from
  `refusals` (`{"thin_wall": "its wall must be thinner than its radius"}`, by a part of
  SQLite's message), else SQLite's. A view shows it in the status bar with
  `with self.refusing(self.tr("Can't add the pipe: {error}")):`, the message translated
  too (a catalog's check finds a table's `refusals` in a view's module); in a
  `cell_edited` callback, the edit is refused as well.
- **Refreshing views.** A table's `changed` signal is emitted after a commit that changed
  rows through it, and after New and Open once the views are loaded too, so the views
  showing the rows can follow: connect it once the app is built (`app.model.runs.changed`),
  or, on the web, in `WebModelApplication.setup_model`, which gets each session's main
  view and model.
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
pipes the database checks as they're added, listed through a filtered query with their
mass from a SQL view joining them to their material.

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
