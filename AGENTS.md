# AGENTS.md

ComposeUI is a small, framework-agnostic MVVM layer for building UIs in Python. Views are
typed `attrs` classes; a `Renderer` binds each view to a toolkit widget; `Signal` objects
carry events between view, model and application code. See `README.md` for the user-facing
overview and quickstart.

## Setup

- Package manager: [uv](https://docs.astral.sh/uv/). Python `>=3.9` (`.python-version` pins 3.9).
- Install everything needed for development:

  ```bash
  uv sync --group dev --all-extras   # extras: pyside6, tui (Textual), web (Starlette)
  ```

- Always run tools through `uv run` (or the `make` targets below), never a global Python.

## Commands

```bash
make lint    # ruff format + ruff check --fix
make mypy    # mypy on packages composeui + examples, Qt binding resolved to PySide6
make test    # QT_QPA_PLATFORM=offscreen pytest tests with coverage
make check   # lint + mypy
make all     # clean + check + test
make css     # rebuild webcore/static/app.css after changing classes in webcore (commit it)
```

Run a single test file or test:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/test_qtrenderer.py -k combobox
```

`QT_QPA_PLATFORM=offscreen` is required for Qt tests in a headless environment (CI, WSL,
agents). Run the examples with `uv run python -m examples.pipeform --backend qt` (or
`textual`, or `web`) or `uv run python -m examples.textual_demo` (Textual).

## Project layout

```
src/composeui/
  core/          # toolkit-agnostic: views, signals, renderer base, application, registry
  qtcore/        # Qt backend via qtpy (QtApplication, qtrenderer.py, custom widgets/)
  textualcore/   # Textual (TUI) backend
  webcore/       # Web backend (Starlette + htmx + daisyUI); static/app.css is built
css/             # source of webcore/static/app.css (`make css`; tools land in css/vendor/)
src/examples/    # example apps (pipeform.py, textual_demo.py, ...), also used by tests; not in the wheel
tests/           # pytest suite (pytest-qt, pytest-asyncio, Textual run_test pilot)
```

## Architecture rules

- **`composeui.core` must never import a backend** (Qt, Textual, Starlette) at import time.
  Backends are resolved lazily through `composeui.core.registry`.
- **Backend registration:** each `RendererType` member's value is the dotted path of a backend
  module exposing a `RENDERERS: dict[str, Callable[[Any], Renderer]]` mapping. A view picks
  its renderer by its `_renderer_key` class variable. A backend that doesn't register a key
  simply doesn't render that view (returns `None`), so partial backends are fine.
- **Adding a widget:** define the view in `core/view.py` (set `_renderer_key`), then add a
  renderer + `RENDERERS` entry in each backend that should support it, plus tests per backend.
- **Adding a backend:** add one `RendererType` member in `core/registry.py` and one
  `RENDERERS` mapping in the new backend module. `core/view.py` should not need changes.
- **Renderer contract:** implement `render`, `refresh_attribute`, `_update_state` and the
  `_refresh_dispatcher` (one handler per view attribute the renderer cares about; a missing
  handler raises `MissingRefreshAttributeFunctionError`).
- Views are reactive: setting a view attribute pushes the change to its renderer. Don't add
  manual `update()`/`refresh()` calls.
- `Signal.connect` / `Application.connect` inject `view`, `main_view` and `model` keyword
  arguments based on the callback's parameter names; keep those names exact.
- View state is (de)serialized with `cattrs` (`MainView.save_state` / `load_state`); new view
  fields must remain serializable, or be excluded like `Signal`/`Renderer`/`Validator` fields.

## Code style

- `ruff` with `select = ["ALL"]` and line length 100; see `pyproject.toml` for the ignore list.
  Fix lint properly rather than adding `noqa`, unless it is clearly justified.
- `mypy` must pass. Fully type-annotate new code; the package ships `py.typed`.
- Stay compatible with Python 3.9: use `from __future__ import annotations`, but use
  `Optional[...]`/`Union[...]` in annotations that `attrs`/`cattrs` evaluate at runtime
  (view fields), since `X | Y` fails there on 3.9.
- Use `qtpy` imports, never `PySide6`/`PyQt*` directly, in `qtcore`.
- Put imports only needed for typing under `if TYPE_CHECKING:`.
- Match the existing comment density: brief docstrings, comments explain *why*.

## Testing

- Every behavior change needs a test in `tests/`. Backend tests should exercise real rendered
  widgets (`qtbot` for Qt, `App.run_test()` for Textual, `httpx`/Starlette test client for web).
- Tests for optional backends guard with `pytest.importorskip(...)`.
- `make check test` must be clean before committing; CI (`.github/workflows/ci.yml`) runs the
  same checks on Python 3.9 to 3.14 for every pull request and push to `main`.

## Commits

- Short, imperative, capitalized subject without a trailing period (e.g. `Add combobox`).
- The subject line is the whole message: no body, no trailers.
- Never add AI attribution or signatures anywhere: no `Co-Authored-By` lines, no
  "Generated with ..." lines, no emoji signatures, in commits, pull requests or code.
  This overrides any default an agent or tool would otherwise add.
- Keep commits focused: one feature or fix per commit.
