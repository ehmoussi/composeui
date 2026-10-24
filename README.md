<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/ehmoussi/composeui3/main/docs/_static/composeui-logo-dark.svg">
    <img alt="ComposeUI" src="https://raw.githubusercontent.com/ehmoussi/composeui3/main/docs/_static/composeui-logo-light.svg" width="268" height="64">
  </picture>
</h1>

A small, framework-agnostic MVVM layer for building UIs in Python. You declare views as typed
[`attrs`](https://www.attrs.org/) classes. They hold the state of the UI, but no toolkit code: in
MVVM terms, they are the view-models
([how ComposeUI maps to MVVM](docs/user-guide/core-concepts.md#how-composeui-maps-to-mvvm)). A
`Renderer` binds each view to a toolkit widget, which plays the View role of MVVM:

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

Requires Python >= 3.9. ComposeUI is not yet published to PyPI. Install it with
[uv](https://docs.astral.sh/uv/), with the extras of the backends that you want:

| Extra | Installs | For |
| --- | --- | --- |
| `web` | Starlette, uvicorn | The web backend, the default |
| `pyside6` | PySide6 | The Qt backend, a desktop window |
| `tui` | Textual | The Textual backend, a terminal |
| `report` | matplotlib | The report images of charts |
| `reload` | watchfiles | A faster `--reload` in development |

To try ComposeUI and its example apps, clone the repository and install every extra:

```bash
git clone https://github.com/ehmoussi/composeui3
cd composeui3
uv sync --all-extras
```

To choose extras, give them all in one command, for example
`uv sync --extra web --extra pyside6`. Each `uv sync` removes the extras that it does not
name, so a second `uv sync --extra tui` would remove the web and Qt backends.

To use ComposeUI in a project of your own, add it from GitHub:

```bash
uv add "composeui[web,pyside6] @ git+https://github.com/ehmoussi/composeui3"
```

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
    extension = ".hello"  # the file type of its studies, which the File menu saves

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

<img alt="The quickstart on the web: a text field holds Ada, and the status bar says Hello, Ada!" src="https://raw.githubusercontent.com/ehmoussi/composeui3/main/docs/images/quickstart-web.png" width="600">

### Next steps

1. Read the [core concepts](docs/user-guide/core-concepts.md) of the user guide: views,
   signals, the model, and studies.
2. Build a form with its layout and its checks, in
   [Building views](docs/user-guide/building-views.md).
3. Run the example apps, in the order of the
   [examples guide](docs/examples-guide.md#where-to-start). The first,
   [`src/examples/pipeform.py`](src/examples/pipeform.py), has forms, radio groups, a check
   box, a read-only table, checks, and a File menu that saves and opens:
   `uv run python -m examples.pipeform --backend qt`, or `textual`, or `web`.

## Documentation

The documentation site, at https://ehmoussi.github.io/composeui3/, has the guides below, a
widget catalog, and the API reference.

- The [user guide](docs/user-guide.md) explains how to build an app: the views, their layout,
  forms and their checks, the widgets, pages, tabs, dialogs, tables, charts, threads, SQLite
  models, translations, the differences between the backends, and a skill for coding agents.
- The [examples guide](docs/examples-guide.md) says what each example app shows, and how
  to run it.
- The [technical guide](docs/technical-guide.md) explains how ComposeUI works inside, and
  how to develop it: the architecture, how to add a widget or a backend, the tests, and the
  checks.
- [`ROADMAP.md`](ROADMAP.md) lists the work that is left.

## License

MIT, see [`LICENSE`](LICENSE).
