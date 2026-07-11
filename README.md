# ComposeUI

A small, framework-agnostic MVVM layer for building desktop UIs in Python. Views are
declared as typed [`attrs`](https://www.attrs.org/) classes; a `Renderer` binds each view to
a concrete toolkit widget (currently [Qt](https://pypi.org/project/QtPy/) via `qtpy`); `Signal`
objects carry events between view, model and application code.

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
    def _on_name_changed(self, text: str, *, main_view: "HelloMainView") -> None:
        main_view.status_bar.show_message(f"Hello, {text}!" if text else "")


@define_view
class HelloMainView(MainView):
    greeting: GreetingInputView = Factory(GreetingInputView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # title/extension are frozen after construction, so they're set once
        # here via object.__setattr__.
        object.__setattr__(self, "title", "Hello ComposeUI")
        object.__setattr__(self, "extension", ".hello")


class HelloApp(QtApplication[HelloMainView]):
    def __init__(self) -> None:
        super().__init__(main_view=HelloMainView())


if __name__ == "__main__":
    HelloApp().run()
```

Run it with `uv run python hello.py` (requires the `pyside6` extra installed).

For a larger, real-world-shaped example with forms, radio groups, validation, and a file menu
with save/load, see [`src/examples/pipeform.py`](src/examples/pipeform.py).

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
(`InputMixin`, `FloatInputMixin`, `RadioGroupMixin`, `LogMixin`, `LabelMixin`) for the
available building blocks.

## Saving and loading state

`MainView.save_state(path)` and `MainView.open_state(path)` (de)serialize the full view tree
to JSON via `cattrs`, automatically skipping `Signal`/`Renderer` fields and, on load, updating
the live view tree in place so renderer bindings and signal connections survive the reload.

## Development

```bash
uv sync --group dev --extra pyside6
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
