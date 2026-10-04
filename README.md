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
  bookmarks and reloads land on that page. A route can't be `state`, `static` or `widget`,
  which the backend uses.
- Single process only, and no push from the server: the page changes in response to the
  user's own actions (a status bar message still clears itself after its timeout).

## Core concepts

| Concept | Role |
| --- | --- |
| `View` (`composeui.core.view`) | A typed `attrs` data class describing UI state (`MainView`, `InputView`, `FormView`, `ActionView`, etc). Composed by nesting view fields inside other views. |
| `Signal` (`composeui.core.signal`) | A typed event emitter. `signal.connect(callback)` supports callbacks that optionally take `view`, `main_view`, and/or `model` keyword arguments, injected automatically. |
| `Renderer` / `RendererContainer` (`composeui.core.renderer`) | Binds a `View` to a concrete toolkit widget and keeps them in sync in both directions (`refresh_attribute` / `update_state`). |
| `Application` / `ModelApplication` (`composeui.core.application`) | Owns the `MainView` (and optionally a `Model`), parses CLI args (`--debug`, `--log`, `--log-signals`, `-f FILE`), and drives rendering. |
| `Model` (`composeui.core.model`) | Empty base class for application/business-logic state, meant to be subclassed. |

Views can be composed by mixing traits, for example `LabelRowFloatInputView` combines
`FormLabelRowView` and `FloatInputMixin`. See the mixins in `composeui/core/view.py`
(`InputMixin`, `FloatInputMixin`, `CheckBoxMixin`, `ValuesGroupMixin`, `TableMixin`,
`LogMixin`, `LabelMixin`) for the available building blocks, and `PageView`/`Router` for
an app split into [pages](#pages).

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

## Saving and loading state

`MainView.save_state(path)` and `MainView.load_state(path)` (de)serialize the full view tree
to JSON via `cattrs`, automatically skipping `Signal`/`Renderer` fields and, on load, updating
the live view tree in place so renderer bindings and signal connections survive the reload.

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
