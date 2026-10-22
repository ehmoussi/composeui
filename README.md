# ComposeUI

A small, framework-agnostic MVVM layer for building UIs in Python. You declare views as
typed [`attrs`](https://www.attrs.org/) classes. A `Renderer` binds each view to a concrete
toolkit widget:

- a desktop window with [Qt](https://pypi.org/project/QtPy/), through `qtpy`;
- a terminal with [Textual](https://textual.textualize.io/);
- a web page served with [Starlette](https://www.starlette.io/) and [htmx](https://htmx.org/).

`Signal` objects carry events between view, model, and application code.

> **Status:** early-stage / pre-alpha. The API is small and still moving.

## Why

- **Declarative views.** A view is an `attrs` class with typed fields. You don't build
  widgets or wire their signals by hand.
- **Reactive by construction.** When you set an attribute of a view (`view.text = "..."`),
  the view pushes the change to its renderer. Normal state changes need no `update()` or
  `refresh()` calls.
- **Toolkit-agnostic core.** `composeui.core` doesn't import Qt, Textual, or Starlette
  when Python imports it. Each backend is imported only when a view renders with it.
- **Typed callback injection.** `Signal.connect` and `Application.connect` read the
  parameter names of a callback. They inject `view`, `main_view`, or `model` when the
  callback asks for them. So callbacks stay short, without manual lookups.

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
uv sync --extra reload      # + watchfiles, for faster --reload in development
```

Requires Python >= 3.9.

## Quickstart

A minimal window with a text input. As you type your name, the status bar greets you:

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

Run it with one of the backends. Each backend needs its extra:

```bash
uv run python hello.py --backend qt        # a window: the pyside6 extra
uv run python hello.py --backend textual   # a terminal: the tui extra
uv run python hello.py                     # a web page, the default: the web extra
```

The web backend serves the page at http://127.0.0.1:8000. `run` imports only the backend
that you choose, and leaves the rest of the command line to the app (`--help` lists it).

For a larger example, see [`src/examples/pipeform.py`](src/examples/pipeform.py). It has
forms, radio groups, a checkbox, a read-only table, validation, and a File menu with save
and load. Run it with `uv run python -m examples.pipeform --backend qt`, or `textual`, or
`web`.

## Documentation

The documentation site, at https://ehmoussi.github.io/composeui3/, has the guides below, a
widget catalog, and the API reference.

- The [user guide](docs/user-guide.md) explains how to build an app: the views and widgets,
  pages, tabs, dialogs, tables, charts, threads, SQLite models, translations, and the
  differences between the backends.
- The [examples guide](docs/examples-guide.md) says what each example app shows, and how
  to run it.
- The [technical guide](docs/technical-guide.md) explains how ComposeUI works inside, and
  how to develop it: the architecture, how to add a widget or a backend, the tests, and the
  checks.
- [`ROADMAP.md`](ROADMAP.md) lists the work that is left.

## License

MIT, see [`LICENSE`](LICENSE).
