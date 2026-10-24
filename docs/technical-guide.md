# Technical guide

This guide explains how ComposeUI works inside, and how to change it: add a widget, add a
backend, and run the checks. To build an app with ComposeUI, read the
[user guide](user-guide.md) instead.

## Contents

- [Project layout](#project-layout)
- [Architecture](#architecture)
  - [The core imports no backend](#the-core-imports-no-backend)
  - [The registry](#the-registry)
  - [Views and renderers](#views-and-renderers)
  - [Signals](#signals)
  - [View state](#view-state)
  - [A button click](#a-button-click)
  - [The web backend](#the-web-backend)
  - [A button click on the web](#a-button-click-on-the-web)
- [Reloading on a change](#reloading-on-a-change)
  - [Reloading on Qt](#reloading-on-qt)
  - [Reloading on Textual](#reloading-on-textual)
  - [Reloading on the web](#reloading-on-the-web)
- [Add a widget](#add-a-widget)
- [Add a backend](#add-a-backend)
- [Development](#development)
  - [Setup](#setup)
  - [Commands](#commands)
  - [Tests](#tests)
  - [Translations](#translations)
  - [Styles of the web backend](#styles-of-the-web-backend)
  - [Code style](#code-style)
  - [Documentation site](#documentation-site)
  - [Continuous integration](#continuous-integration)

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
docs/            # the user guide (user-guide/), the examples guide, this guide, the Sphinx site
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

The views are the view-models of MVVM, and the toolkit objects are the views. The renderers
are the binding between them. See
[How ComposeUI maps to MVVM](user-guide/core-concepts.md#how-composeui-maps-to-mvvm).

A view is an `attrs` class. `@define_view` adds the `notify_renderer` hook to the
`on_setattr` of its fields. When code sets a public attribute to a new value, the hook calls
`refresh_attribute(name, value)` on the renderer of the view. Do not add manual `update()`
or `refresh()` calls.

A renderer (`composeui.core.renderer.Renderer`) binds a view to a toolkit object, its
rendered object. It syncs them in both directions:

| Method | Direction | Does |
| --- | --- | --- |
| `render()` | view to toolkit | Creates the rendered object. |
| `refresh()` | view to toolkit | Calls every handler of `_refresh_dispatcher` with the current value of its attribute. |
| `refresh_attribute(name, value)` | view to toolkit | Calls the handler of one attribute. |
| `update_state()` | toolkit to view | Calls `_update_state(view, rendered_object)` inside `stop_refresh()`. |

`_refresh_dispatcher` maps each view attribute that the renderer cares about to its
handler. When a view attribute changes and it has no handler,
`refresh_attribute` raises `MissingRefreshAttributeFunctionError`.

While `update_state()` runs, `is_updating_state()` is true. `notify_renderer` then doesn't
refresh the toolkit with the values that came from it.

`call_on_main_thread(callback)` calls the callback directly by default. Each backend of this
repo overrides it: Qt and Textual run the callback on their main thread, and the web runs it
under the session's lock. See [A button click](#a-button-click).

### Signals

`Signal.connect` and `Application.connect` read the parameter names of a callback:

- `Signal.connect` injects the `main_view` and `model` keyword arguments when the callback
  asks for them. The callback gets only as many of the signal's arguments as it takes.
- `Application.connect` also injects `view`, the view that it connects.

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
  [Saving and loading state](user-guide/building-views.md#saving-and-loading-state).

### A button click

An event goes from the toolkit's widget to the view, and a change goes back from the view to
the toolkit's widget. For example, a page has a `ButtonView` and a `LabelView`. A callback
connected to the button's `clicked` signal sets the label's `text` to "Done". On every backend,
one click does this:

![Each backend turns the click into the view's clicked signal. In composeui.core, the signal runs the callback, which sets the label's text, and notify_renderer calls refresh_attribute. Each backend's label handler then shows the value.](images/button-click.svg)

1. **The button's renderer emits the view's signal.** It turns the toolkit's click into the
   `clicked` signal of the `ButtonView`.
2. **The signal runs the callback.** `Signal.emit` calls each connected callback, with the
   arguments that it injects (see [Signals](#signals)).
3. **The view notifies its renderer.** The callback sets `label.text = "Done"`.
   `notify_renderer` compares the new value with the old one, and calls
   `refresh_attribute("text", "Done")` on the label's renderer.
4. **The renderer shows the value.** The `"text"` handler of the label renderer's
   `_refresh_dispatcher` changes the toolkit's widget.

Steps 2 and 3 are in `composeui.core`, and are the same on every backend. Steps 1 and 4 are
the backend's:

- **Qt.** The button is a `QPushButton`. Its Qt `clicked` signal calls
  `QtButtonRenderer._emit_clicked`, which emits the view's `clicked`. The click and the callback
  run in Qt's event loop, on the main thread. The label's `"text"` handler calls
  `QLabel.setText`. `QtWidgetRenderer.refresh_attribute` blocks the widget's signals while it
  sets the value. So the widget does not send the app's own change back to the view as an edit
  of the user.
- **Textual.** The button is a `ComposeButton`, a Textual `Button`. Its `on_button_pressed`
  emits its own `clicked` signal, which is connected to the view's. The click and the callback
  run in the app's event loop. The label's `"text"` handler calls `Label.update`.
  `TextualWidgetRenderer.refresh_attribute` goes through `call_on_main_thread`, which calls the
  handler directly on the app's own thread. A widget that is not mounted yet, for example on a
  screen that is not shown, gets its state when it is mounted (`_is_waiting_to_mount`).
- **The web.** The button is a `<button>` element in the browser. htmx posts the click to the
  server, and `WebButtonRenderer.dispatch` emits the view's `clicked`. No widget lives between
  two requests. So the label's `"text"` handler, `_mark_dirty`, changes nothing in the page: it
  marks the renderer dirty, and the server sends the label's fragment in its response. See
  [A button click on the web](#a-button-click-on-the-web).

A change can also come from another thread, for example a job's. `call_on_main_thread` hands
it over:

- **Qt.** It queues the change on Qt's main thread (`_MainThreadInvoker`).
- **Textual.** It runs the change with `App.call_from_thread`.
- **The web.** It runs the change under the session's lock. The next response, or the next
  fetch of `/jobs`, sends the change.

### The web backend

The web backend renders HTML on the server and updates the page with htmx. Its design
decisions are in "Design notes for the web backend" in [`ROADMAP.md`](../ROADMAP.md). Read
them before you change `composeui.webcore`.

- **The id is the rendered object.** The web has no live widget between two requests. A web
  renderer's rendered object is the id of its HTML fragment, `cui-{id(view)}-{role}`.
- **One main view per session.** Each browser session has its own main view, in a `WebSession`
  (`session.py`). `WebApplication.connect` records each connection, and connects it again on the
  main view of each new session.
- **Events go in, fragments come out.** An event goes to the server. The response sends back
  the fragments that the event changed, and htmx swaps them into the page.

### A button click on the web

This is the click of [A button click](#a-button-click) on the web, step by step:

![The browser posts the click. The middleware checks it. The route gives it to the session, which dispatches it to the button's renderer under its lock. The callback changes the label, which marks the label's renderer dirty. The session renders the dirty fragments, and htmx swaps them into the page.](images/web-click.svg)

1. **The browser posts the event.** The button's fragment (`WebButtonRenderer.to_html`) has
   `hx-post="/widget/{id}"` and `hx-vals` with `event=click`. Its `hx-swap="none"` tells htmx
   not to swap the button with the response.
2. **The middleware checks the request.** `create_starlette_app` in `webapplication.py` adds
   the middleware. `SecurityHeadersMiddleware` (`headers.py`) adds the security headers to
   every response. `BodySizeLimitMiddleware` (`limits.py`) refuses a body that is too large.
   `SameOriginMiddleware` (`origin.py`) refuses a request from another origin. Starlette's
   `SessionMiddleware` reads the signed session cookie.
3. **The route finds the session.** `widget_event` (`routes.py`) gets the session from the
   cookie's id. When the session is gone, the response has `HX-Refresh`, and the page reloads
   with a new session. Otherwise, the route calls `WebSession.handle_event` in a thread: the
   app's callbacks are synchronous code, and must not block the event loop.
4. **The session dispatches the event.** `handle_event` finds the renderer by its id in the
   session's own `renderers`. An id of another session is not found. `_respond` takes the
   session's lock and opens `collect_dirty()`, a set of dirty renderers for this request. Then
   it calls `WebButtonRenderer.dispatch`, which refuses the click when the button is disabled.
5. **The signal runs the callback.** `dispatch` emits `clicked`. The callback sets
   `label.text = "Done"`.
6. **The label's renderer becomes dirty.** `notify_renderer`, the `on_setattr` hook of every
   view field, calls the renderer's `refresh_attribute("text", ...)`. The handler in the
   `_refresh_dispatcher` of `WebLabelRenderer` is `_mark_dirty`. It only adds the renderer to
   the dirty set: the renderer renders nothing yet.
7. **The session renders the dirty fragments.** `_respond` adds the renderers that a thread
   changed since the last response (`take_pending`) to the dirty ones. `render_dirty` calls
   `to_html(oob=True)` on each, which adds `hx-swap-oob="true"` to the root element. It drops a
   fragment that another dirty fragment contains, else htmx would swap it twice.
8. **The session adds the page's fragments.** When the event changed the main view's title,
   language, or running jobs, `_respond` adds their fragments too. When the event opened
   another page, `_respond` also returns the page's address.
9. **The route responds.** `_widget_response` sends the fragments as HTML. With a new page, it
   adds `HX-Push-Url`, which puts the address in the browser's history. When the app closed
   (the Exit action), it drops the session and responds with `HX-Redirect` to `/`.
10. **htmx swaps the fragments.** htmx puts each `hx-swap-oob` fragment in place of the element
    with the same id. The label shows "Done". The button stays as it is.

The other routes follow the same steps. `widget_file` gives an upload to the session in place of
a form. `jobs_poll` runs no event: its response sends the changes that the threads made.

## Reloading on a change

`--reload` runs the app's changed code each time that a Python file is saved. The user guide says
what the user sees
([Reloading the app on a change](user-guide/running-the-app.md#reloading-the-app-on-a-change)). Qt
and Textual use `composeui.core.reload`, without a toolkit. The web uses uvicorn's reload.

### Reloading on Qt

On Qt, `--reload` works like this:

1. **A supervisor process.** With `--reload`, the process that the user starts runs
   `run_reloading` and shows no window. It runs the same command line again in a child
   process (`program_command`). The `COMPOSEUI_RELOADED` environment variable marks the
   child, so the child shows the app and does not start a supervisor of its own. The
   variable holds a scratch directory that the two processes share.
2. **Watching the files.** `watch_changes` watches the Python files under the current
   directory. It skips hidden directories, `__pycache__`, `node_modules`, and
   `site-packages`. With watchfiles, the system reports the changes
   (`force_polling=False`). Without watchfiles, and for a Windows drive under WSL
   (`has_change_events`), the supervisor compares the modification times every half
   second. watchfiles polls everywhere on WSL by default, and its polling misses changes.
3. **The change request.** On a change, the supervisor writes the paths of the changed files
   to the `changes` file of the scratch directory. The app looks for it every 200 ms, and
   takes it: it renames it to `taken` (`take_changes`). From then on, the supervisor waits
   for the app as long as the app needs. While a modal dialog is open, the app waits until
   it closes: a dialog's own event loop also runs the timer, and its callback goes on with
   the app after it. Then the app saves the study to the same directory
   (`save_reloaded_state`): the view state, the model's data, and in `session.json` the
   study file's path and the language shown.
4. **In place.** When only the app's own code changed (`can_reload_in_place`),
   `rerun_program` removes the program's modules from `sys.modules`. These are the modules
   under the current directory, without ComposeUI's. Then it runs the program again as a new
   `__main__`. The app's `run` calls `keep_rerun`, which keeps the new app and ends the
   program there, as `run` would. `_Reloads` opens the study in the new main view. It
   detaches the previous views from their widgets (`_forget_widgets`), and renders the new
   main view into the same `QMainWindow` (`QtMainRenderer(view, window)` removes the
   previous bars, menus, and sidebar). Then the app removes the `taken` file
   (`acknowledge_changes`), and the supervisor keeps it running.
5. **In a new process.** When ComposeUI's own code changed, the app exits after it saves the
   study. It does the same when the new main view fails to show. The supervisor then starts
   a new child, which opens the study (`load_reloaded_state`). It does the same when the app
   does not take the request within 5 seconds, after it terminates it. When the program
   fails while it runs again, for example on a syntax error, the app logs the error, keeps
   the previous code, and answers.

The supervisor stops its child when it exits, also on Ctrl+C or `kill` (SIGTERM).

### Reloading on Textual

Textual has the supervisor and the change request of Qt, but not the reload in place: its app
saves the study and exits on every request, and the supervisor starts a new child. Its
timer starts once the Textual app is mounted (`mounted_callbacks`). The supervisor logs a
change only after the app answered or exited, so it never prints over a terminal app.

### Reloading on the web

The web's `--reload` is uvicorn's, which restarts the server process. The web app only tells
watchfiles not to poll where the system reports the changes. Its sessions outlive the
processes: the process that `run` starts makes a scratch directory and a key that signs
the session cookies, and gives both to the server's processes through environment
variables. Each process saves its sessions as it stops, in its lifespan's end
(`SessionStore.save_all`, with `save_reloaded_state`). The next opens a session there
when its cookie comes back, under the same id (`SessionStore._restore`). Its pages ask
`GET /reload` every second, naming the process that served them (`reload_poller`):
another process answers with `HX-Refresh`.

## Add a widget

1. Define the view in `core/view.py`. Set its `_renderer_key`, and give it a class docstring:
   the [widget catalog](#documentation-site) shows its first paragraph.

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

   A web renderer has no widget to keep. It renders its fragment in `to_html`, and applies the
   browser's events to the view in `dispatch`. Its handlers mark it dirty (`_mark_dirty`). See
   [A button click on the web](#a-button-click-on-the-web).

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
4. Add the new backend's `RENDERERS` to
   `test_every_backend_registers_the_same_renderer_keys` in
   `tests/test_renderer_registry.py`. A backend of this repo registers every key, so that
   every view renders on it. Then add tests for its renderers and its application. See
   [Tests](#tests).
5. Add the backend and its extra to the "Backends" table of the
   [user guide](user-guide/running-the-app.md#backends). In each feature section of the user guide,
   say what the new backend shows, as the section does for Qt, Textual, and the web.

`core/view.py` should not need changes. `run` reads the `--backend` choices from
`RendererType`, so the new backend is one of them.

## Development

### Setup

ComposeUI uses [uv](https://docs.astral.sh/uv/) and Python 3.9 or later. `.python-version`
pins 3.9. Install every backend, because the tests cover Qt, Textual, and the web:

```bash
uv sync --group dev --all-extras   # extras: pyside6, tui (Textual), web (Starlette), report, reload
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
make web-deps      # download htmx, uPlot and Cally at their versions (then make css)
make docs          # build the documentation site into docs/_build/html
make screenshots   # the screenshots of the examples guide, on every backend
```

On Windows without `make`, run the same targets in PowerShell with `make.ps1`, such as
`.\make.ps1 check test`. Pass `EXAMPLES` as `-Examples pipeform, batman` and
`TAILWIND_PLATFORM` as `-TailwindPlatform`. When you change a target in the `Makefile`,
change it in `make.ps1` too.

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
`Makefile`, and `make.ps1` has the same list in `$TranslatedMainViews`. When you translate a
new app, add its main view to both. See
[Checking the catalogs](user-guide/translation.md#checking-the-catalogs).

### Styles of the web backend

`webcore/static/app.css` is built from `css/` with Tailwind and daisyUI. When you change
the classes used in `webcore`, run `make css`, and commit the built file. `make css`
downloads the Tailwind CLI and the daisyUI files once, into `css/vendor/`, which is not
committed. It needs no Node or npm. It checks the SHA-256 of each file against the one in the
`Makefile` and `make.ps1`, and fails when they differ. When you change `TAILWIND_VERSION` or
`DAISYUI_VERSION`, change the SHA-256 values in both files, and delete `css/vendor/`.

The page's scripts are committed in `webcore/static/`: htmx, uPlot and Cally. uPlot's
stylesheet, `css/uPlot.min.css`, is committed too. The package then needs no download, and
the page works offline. `make web-deps` downloads these files from npm at the versions in
the `Makefile`, and checks their SHA-256. It adds Cally's license to `cally.js` as a
comment. To update one of them:

1. Change its version and its SHA-256 in the `Makefile` and in `make.ps1`.
2. Change its version in the comments of `webcore/page.py`.
3. Run `make web-deps css`, then the tests, and commit the files.

### Code style

- `ruff` lints with `select = ["ALL"]` and a line length of 100. `pyproject.toml` has the
  ignore list. Fix lint properly rather than adding `noqa`, unless it is clearly justified.
- `mypy` must pass. Fully type-annotate new code: the package ships `py.typed`.
- Every Python module starts with `from __future__ import annotations`, after its
  docstring. Ruff enforces it (`required-imports`, rule I002), and `make lint` adds it to a
  new file. The annotations are then strings:
  - Do not quote them.
  - Define the views that `attrs` and `cattrs` resolve at module level, not inside a
    function, so that their field types resolve from the module's globals.
  - Give a `cattrs` hook its type explicitly, with
    `CONVERTER.register_structure_hook(cls, func)`, not as a bare decorator, which reads
    the annotation.
- Stay compatible with Python 3.9. In the annotations that `attrs` and `cattrs` evaluate at
  runtime, such as view fields, use `Optional[...]` and `Union[...]`, not `X | Y`.
- In `qtcore`, import Qt from `qtpy`, never from `PySide6` or `PyQt*`.
- In `webcore`, build HTML with `Markup(template).format(...)` from `markupsafe`, never with
  an f-string. `format` escapes every value that isn't `Markup` itself.
- Put imports that only typing needs under `if TYPE_CHECKING:`.
- Match the comment density of the code around: brief docstrings, and comments that explain
  why.

### Documentation site

`make docs` builds the documentation site with Sphinx and MyST into `docs/_build/html`.
The site holds the guides, a widget catalog, and an API reference. Install the `docs` group
and every extra first, because the API reference imports the application module of each
backend:

```bash
uv sync --group dev --group docs --all-extras
```

- **The guides stay Markdown.** MyST reads `docs/*.md` and `docs/user-guide/*.md` as they
  are. A link from a guide to a file outside `docs/`, such as `../src/examples/pipeform.py`,
  goes to that file on GitHub (`docs/conf.py`).
- **The user guide is a page per topic.** `docs/user-guide.md` lists the pages of
  `docs/user-guide/` and their sections, and its `toctree` orders them. A new page goes in
  both.
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
  `make screenshots EXAMPLES=<example>`, and commit the images. The script also takes
  `docs/images/quickstart-web.png` for the README. It runs the code of the README's
  quickstart, so run `make screenshots EXAMPLES=quickstart` when the quickstart changes.

### Continuous integration

`.github/workflows/ci.yml` runs on every pull request and every push to `main`. It runs
the lint, `make mypy`, `make translations`, and `make test` on Python 3.9 to 3.14, and
`make browser-test` and `make docs` on Python 3.13. On Windows, it runs
`.\make.ps1 translations test` on Python 3.9 and 3.14. Run `make check test` before you commit.

A change of the documentation only, in `docs/` and the Markdown files, runs only the `docs`
job. That job also lints the Python files of `docs/`.

On a push to `main`, the `pages` job publishes the site that `make docs` built to GitHub
Pages, at https://ehmoussi.github.io/composeui3/. A pull request only builds the site.
