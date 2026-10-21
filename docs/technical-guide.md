# Technical guide

This guide explains how ComposeUI works inside, and how to change it: add a widget, add a
backend, and run the checks. To build an app with ComposeUI, read the
[user guide](user-guide.md) instead.

## Contents

- [Project layout](#project-layout)
- [Architecture](#architecture)
- [Add a widget](#add-a-widget)
- [Add a backend](#add-a-backend)
- [Development](#development)

## Project layout

```
src/composeui/
  core/          # toolkit-agnostic: views, signals, renderer base, application, registry
  qtcore/        # Qt backend via qtpy (QtApplication, qtrenderer.py, custom widgets/)
  textualcore/   # Textual (TUI) backend
  webcore/       # Web backend (Starlette + htmx + daisyUI); static/app.css is built
css/             # source of webcore/static/app.css (`make css`; tools land in css/vendor/)
src/examples/    # example apps (pipeform.py, pipecatalogue.py, ...), also used by tests; not in the wheel
tests/           # pytest suite (pytest-qt, pytest-asyncio, Textual run_test pilot)
docs/            # the user guide, the examples guide, this guide, and the Sphinx site
```

## Architecture

### The core imports no backend

`composeui.core` never imports a backend (Qt, Textual, Starlette) at import time.
The Qt binding lives entirely in `composeui.qtcore`. Python imports it only when a view
renders with `RendererType.QT`. The same is true for Textual and the web.
`tests/test_renderer_registry.py` checks that importing `composeui.core.view` imports no
toolkit.

### The registry

`composeui.core.registry` maps renderer keys to the renderers of each backend:

- Each `RendererType` member is a backend. Its value is a `Backend`, which holds two dotted
  module paths:
  - `renderers`: the module that exposes the `RENDERERS` mapping,
    `dict[str, Callable[[Any], Renderer]]`;
  - `applications`: the module that exposes `APPLICATION` and `MODEL_APPLICATION`, the
    application classes that `core.application.run` starts.
- A view names its renderer with its `_renderer_key` class variable, for example
  `"label"`.
- `create_renderer(renderer_type, key, view)` imports the renderers module of the backend
  and looks up the key. When the backend doesn't register the key, it returns `None`, and
  the view is not rendered. So a partial backend works.

The three backends of this repo register the same keys:
`test_every_backend_registers_the_same_renderer_keys` fails when one backend misses a key.

### Views and renderers

A view is an `attrs` class. `@define_view` adds the `notify_renderer` hook to the
`on_setattr` of its fields. When code sets a public attribute to a new value, the hook calls
`refresh_attribute(name, value)` on the renderer of the view. Do not add manual `update()`
or `refresh()` calls.

A renderer (`composeui.core.renderer.Renderer`) binds a view to a toolkit object, its
rendered object. It syncs them in both directions:

| Method | Direction | Does |
| --- | --- | --- |
| `render()` | view to toolkit | Creates the rendered object, then calls `refresh()`. |
| `refresh()` | view to toolkit | Calls every handler of `_refresh_dispatcher` with the current value of its attribute. |
| `refresh_attribute(name, value)` | view to toolkit | Calls the handler of one attribute. |
| `update_state()` | toolkit to view | Calls `_update_state(view, rendered_object)` inside `stop_refresh()`. |

`_refresh_dispatcher` maps each view attribute that the renderer cares about to its
handler. When a view attribute changes and it has no handler,
`refresh_attribute` raises `MissingRefreshAttributeFunctionError`.

While `update_state()` runs, `is_updating_state()` is true. `notify_renderer` then doesn't
refresh the toolkit with the values that came from it.

`call_on_main_thread(callback)` calls the callback directly by default. A renderer whose
toolkit has thread affinity, such as Qt, overrides it to run the callback on its main
thread.

### Signals

`Signal.connect` and `Application.connect` read the parameter names of a callback. They
inject `view`, `main_view`, and `model` keyword arguments when the callback asks for them.
These names are part of the API: keep them exact.

### View state

`MainView.save_state` and `MainView.load_state` serialize the view tree with the `cattrs`
converter `CONVERTER` of `composeui.core.view`. A new view field must stay serializable, or
be excluded:

- Fields of the types in `_OMITTED_TYPES` (`Signal`, `Renderer`, `RendererContainer`,
  `threading.Timer`) are skipped automatically.
- Other fields that can't be serialized, such as `Validator` fields, take the `OMIT`
  metadata key.
- Text that the app's code sets, not the user, takes the `UI_TEXT` metadata key. See
  [Saving and loading state](user-guide.md#saving-and-loading-state).

### The web backend

The web backend renders HTML on the server and updates the page with htmx. Its design
decisions are in "Design notes for the web backend" in [`ROADMAP.md`](../ROADMAP.md). Read
them before you change `composeui.webcore`.

## Add a widget

1. Define the view in `core/view.py`. Set its `_renderer_key`:

   ```python
   @define_view
   class LabelView(LabelMixin, View):
       _renderer_key = "label"
   ```

2. In each backend, add a renderer and its `RENDERERS` entry (`"label": QtLabelRenderer`).
   The renderer registers a handler per view attribute, creates its rendered object in
   `render`, and reads the user's changes back in `_update_state`:

   ```python
   class QtLabelRenderer(QtWidgetRenderer[LabelViewLike, QLabel]):
       def __init__(self, view: LabelViewLike) -> None:
           super().__init__(view)
           self._refresh_dispatcher.update(
               {
                   "text": self._refresh_text,
               }
           )

       def render(self) -> None:
           if self._rendered_object is None:
               self._rendered_object = QLabel()
               self.refresh()

       @staticmethod
       def _refresh_text(_view: LabelViewLike, rendered_object: QLabel, value: str) -> None:
           rendered_object.setText(value)

       @staticmethod
       def _update_state(view: LabelViewLike, rendered_object: QLabel) -> None:
           view.text = rendered_object.text()
   ```

3. Add tests for each backend that exercise the real rendered widgets. See
   [Tests](#tests).
4. Document the widget in the [user guide](user-guide.md), and update the list of widgets
   at the top of [`ROADMAP.md`](../ROADMAP.md). When an example app uses the widget,
   update the [examples guide](examples-guide.md) too.

## Add a backend

1. Add one `RendererType` member in `core/registry.py`, with the `Backend` paths of the new
   modules.
2. In the renderers module of the new backend, add a `RENDERERS` mapping.
3. In its application module, add its application classes as `APPLICATION` and
   `MODEL_APPLICATION`. They are built from `build_main_view=`, plus `build_model=` and
   `setup_model=` for the model application.

`core/view.py` should not need changes.

## Development

### Setup

ComposeUI uses [uv](https://docs.astral.sh/uv/) and Python 3.9 or later. `.python-version`
pins 3.9. Install every backend, because the tests cover Qt, Textual, and the web:

```bash
uv sync --group dev --all-extras   # extras: pyside6, tui (Textual), web (Starlette)
```

Always run the tools through `uv run` or the `make` targets, never a global Python.

### Commands

```bash
make lint          # ruff format + ruff check --fix
make mypy          # mypy on packages composeui + examples, Qt binding resolved to PySide6
make test          # pytest with coverage (browser tests excluded)
make browser-test  # the web backend in headless Chromium (tests/test_browser.py, Playwright)
make translations  # each app's catalogs against the text it translates
make check         # lint + mypy + translations
make all           # clean + check + test
make css           # rebuild webcore/static/app.css after changing classes in webcore
make docs          # build the documentation site into docs/_build/html
make screenshots   # the screenshots of the examples guide, on every backend
```

Run the examples with `uv run python -m examples.pipeform --backend qt`, or `textual`, or
`web`.

### Tests

Every behavior change needs a test in `tests/`.

- Backend tests exercise real rendered widgets: `qtbot` for Qt, `App.run_test()` for
  Textual, and the `httpx` or Starlette test client for the web.
- Tests for an optional backend guard with `pytest.importorskip(...)`.
- Qt tests in a headless environment (CI, WSL) need `QT_QPA_PLATFORM=offscreen`.
  `make test` sets it. To run one file or test:

  ```bash
  QT_QPA_PLATFORM=offscreen uv run pytest tests/test_qtrenderer.py -k combobox
  ```

- What only a browser shows, such as the page's scripts and htmx swaps, goes in
  `tests/test_browser.py`, marked `browser`. These tests need the `browser` group and
  Chromium. Install Chromium once with `uv run --group browser playwright install chromium`,
  then run `make browser-test`.

### Translations

`make translations` checks the catalogs of each app in `TRANSLATED_MAIN_VIEWS` of the
`Makefile`. When you translate a new app, add its main view there. See
[Checking the catalogs](user-guide.md#checking-the-catalogs).

### Styles of the web backend

`webcore/static/app.css` is built from `css/` with Tailwind and daisyUI. When you change
the classes used in `webcore`, run `make css`, and commit the built file. `make css`
downloads the Tailwind CLI and the daisyUI files once, into `css/vendor/`, which is not
committed. It needs no Node or npm.

### Code style

- `ruff` lints with `select = ["ALL"]` and a line length of 100. `pyproject.toml` has the
  ignore list. Fix lint properly rather than adding `noqa`, unless it is clearly justified.
- `mypy` must pass. Fully type-annotate new code: the package ships `py.typed`.
- Every Python module starts with `from __future__ import annotations`, after its
  docstring. `make lint` adds it to a new file.
- Stay compatible with Python 3.9. In the annotations that `attrs` and `cattrs` evaluate at
  runtime, such as view fields, use `Optional[...]` and `Union[...]`, not `X | Y`.
- In `qtcore`, import Qt from `qtpy`, never from `PySide6` or `PyQt*`.
- In `webcore`, build HTML with `Markup(template).format(...)` from `markupsafe`, never with
  an f-string. `format` escapes every value that isn't `Markup` itself.
- Put imports that only typing needs under `if TYPE_CHECKING:`.

### Documentation site

`make docs` builds the documentation site with Sphinx and MyST into `docs/_build/html`.
The site holds the guides, a widget catalog, and an API reference. Install the `docs` group
and every extra first, because the API reference imports the application module of each
backend:

```bash
uv sync --group dev --group docs --all-extras
```

- **The guides stay Markdown.** MyST reads `docs/*.md` as they are. A link from a guide to
  a file outside `docs/`, such as `../src/examples/pipeform.py`, goes to that file on
  GitHub (`docs/conf.py`).
- **The API reference is built from the docstrings.** Each page in `docs/api/` runs
  `automodule` in an `{eval-rst}` block, because autodoc writes reStructuredText. In a
  docstring, single backticks link to the name they hold. When you add a module to
  `composeui.core`, add its page and its entry in `docs/api/index.md`.
- **The widget catalog is built from the views.** The `widget-catalog` directive
  (`docs/_ext/widgetcatalog.py`) lists each view of `composeui.core.view` that has a
  `_renderer_key`, with the first paragraph of its docstring. A new widget is in the
  catalog without a change to `docs/widgets.md`.
- **A warning fails the build**, as a broken link or a docstring that autodoc cannot read.
- **The screenshots of the examples are taken by a script.** `make screenshots` runs
  `docs/screenshots.py`, which writes `docs/images/<example>-<backend>.png` for Qt,
  Textual, and the web, in the light theme. The script sets each example up first, for
  example by filling in its form or running its job, so every backend shows the same
  state. It needs the `browser` group and Chromium, as `make browser-test` does. When an
  example changes what it shows, update its set-up in the script, run
  `make screenshots EXAMPLES=<example>`, and commit the images.

### Continuous integration

`.github/workflows/ci.yml` runs on every pull request and every push to `main`. It runs
the lint, `make mypy`, `make translations`, and `make test` on Python 3.9 to 3.14, and
`make browser-test` and `make docs` on Python 3.13. Run `make check test` before you commit.

On a push to `main`, the `pages` job publishes the site that `make docs` built to GitHub
Pages, at https://ehmoussi.github.io/composeui3/. A pull request only builds the site.
