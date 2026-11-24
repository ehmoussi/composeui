# AGENTS.md

ComposeUI is a small, framework-agnostic MVVM layer for building UIs in Python. Views are
typed `attrs` classes; a `Renderer` binds each view to a toolkit widget; `Signal` objects
carry events between view, model and application code. See `README.md` for the overview and
quickstart, `docs/user-guide/` for each feature, `docs/examples-guide.md` for the example apps, and
`docs/technical-guide.md` for the architecture and development.

## Setup

- Package manager: [uv](https://docs.astral.sh/uv/). Python `>=3.9` (`.python-version` pins 3.9).
- Install everything needed for development:

  ```bash
  uv sync --group dev --all-extras   # extras: pyside6, tui (Textual), web (Starlette), report, terminal-images, reload
  ```

  Add `--group textual-dev` for Textual's console (`textual console`). It is not in `dev`:
  it installs Textual, which the tests without extras must not find.

- Always run tools through `uv run` (or the `make` targets below), never a global Python.
- Run `make hooks` once in a clone: the hooks of `.githooks/` refuse a commit on `main`, a
  branch with a slash, and a message that breaks the rules of "Commits".

## Commands

```bash
make lint    # ruff format + ruff check --fix
make mypy    # mypy on composeui, examples and tests, Qt binding resolved to PySide6
make typecheck  # mypy on source + tests; Pyright, Pyrefly and ty on tests
make pyright pyrefly ty  # individual test checkers
make test    # pytest tests in parallel, Qt offscreen, with coverage (browser tests excluded)
make hooks   # git's hooks of .githooks/ in this clone (core.hooksPath)
make browser-test  # the web backend in headless Chromium (tests/test_browser.py, Playwright)
make translations  # each app's catalogs against the text it translates (TRANSLATED_MAIN_VIEWS)
make js-check  # the page's scripts against their JSDoc types (TypeScript's compiler, no Node)
make check   # lint + mypy + translations + js-check
make all     # clean + check + test
make css     # rebuild webcore/static/app.css after changing classes in webcore (commit it)
make web-deps  # htmx, uPlot, Cally and deck.gl from npm at pinned versions and SHA-256 (commit them)
make docs    # Sphinx + MyST site in docs/_build/html, warnings as errors (needs `--group docs`)
make screenshots   # docs/images/<example>-<backend>.png for the docs and README (Chromium)
```

On Windows without `make`, the matching targets are in `make.ps1`. Run
`.\make.ps1 translations test` to match the Windows CI job. The Linux `check` job runs
`make mypy`. The `browser` job runs `make js-check`. Locally, `make check` includes both.
In PowerShell, use `-Examples pipeform, batman` for `EXAMPLES`, `-TailwindPlatform` for
`TAILWIND_PLATFORM`, `-TscPlatform` for `TSC_PLATFORM`, and `-Workers` for `PYTEST_WORKERS`.
Keep `make.ps1` in step with the `Makefile`, including its `$TranslatedMainViews` list
(`TRANSLATED_MAIN_VIEWS`): `tests/test_code_rules.py` checks both.

`make mypy` checks source, examples and tests together. It installs the `browser` group and
all extras so every test import resolves; Chromium is not needed. The other checker targets
also install the `typecheck` group. The locked version of Playwright's `greenlet` dependency has
no prebuilt wheel for Python 3.9 on Windows x64. Use Python 3.13 to install the `browser` group
on this platform, or use a C++20 compiler to build `greenlet`.

Run a single test file or test:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/qtcore/test_choices.py -k combobox
```

`QT_QPA_PLATFORM=offscreen` is required for Qt tests in a headless environment (CI, WSL,
agents). Run the examples with `uv run python -m examples.pipeform --backend qt` (or
`textual`, or `web`) or `uv run python -m examples.textual_demo` (Textual).

## Project layout

```
src/composeui/
  cli.py         # the `composeui` command (`composeui run app.py`, `composeui translations`)
  core/          # toolkit-agnostic: views, signals, renderer base, application, registry
    _views/      # the views, a module per family (view.py exports them)
  qtcore/        # Qt backend via qtpy (QtApplication, qtrenderer.py, custom widgets/)
    _renderers/  # its renderers, a module per family (renderers.py maps their keys)
  textualcore/   # Textual (TUI) backend
    _renderers/  # its renderers, a module per family (renderers.py maps their keys)
  webcore/       # Web backend (Starlette + htmx + daisyUI); static/app.css is built
    _renderers/  # its renderers, a module per family (renderers.py maps their keys)
css/             # source of webcore/static/app.css (`make css`; tools land in css/vendor/)
js/              # the scripts' type check (`make js-check`; TypeScript lands in js/vendor/)
src/examples/    # example apps (pipeform.py, pipecatalogue.py, ...), also used by tests; not in the wheel
tests/           # pytest suite (pytest-qt, pytest-asyncio, Textual run_test pilot)
  qtcore/        # the Qt backend's tests, a module per family, as in _renderers/
  textualcore/   # the Textual backend's tests, a module per family, as in _renderers/
  webcore/       # the web backend's tests, a module per family or per other webcore module
  contracts/     # the rules every backend follows, each test run on each backend
docs/            # user guide, examples guide, technical guide; Sphinx site (conf.py, api/, _ext/)
```

## Architecture rules

- **`composeui.core` must never import a backend** (Qt, Textual, Starlette) at import time.
  Backends are resolved lazily through `composeui.core.registry`.
- **Backend registration:** each `RendererType` member's value is a `Backend`: the dotted
  paths of the backend's renderers module, exposing a
  `RENDERERS: dict[str, Callable[[Any], Renderer]]` mapping, and of its application module,
  exposing `APPLICATION` and `MODEL_APPLICATION` (what `core.application.run` starts),
  plus the extra that installs its dependencies and their top-level modules (`run` names
  the extra when one is missing). A view picks its renderer by its `_renderer_key` class variable. A
  backend that doesn't register a key simply doesn't render that view (returns `None`), so partial
  backends are fine.
- **Adding a widget:** define the view in the `core/_views/` module of its family (set
  `_renderer_key`) and export it in the `__all__` of `core/view.py`, then add a
  renderer + `RENDERERS` entry in each backend that should support it, plus tests per backend.
  The tests go in the backend's test module of the family, such as `tests/qtcore/test_tables.py`.
  In each backend, the renderer goes in the backend's `_renderers/` module of its
  family (a new module for a new family), and its entry in the backend's `renderers.py`.
- **Qt renderer modules:** `qtrenderer.py` holds only `QtWidgetRenderer`, the shared
  main-thread invoker, type variables and the widget-size constant. Each module of
  `qtcore/_renderers/` holds one family, as on the web. `forms.py` owns `_widget_of` and the
  form-row widget cache; `containers.py` owns shared layout and dialog-parent helpers.
  `navigation.py` holds the main renderer, window, router and sidebar. Family modules import
  each other directly, not through `renderers.py`, which only maps keys. `maprenderer.py`
  stays lazy: `graphics.py` loads it only when a map is rendered, not with the backend.
- **Textual renderer modules:** `textualrenderer.py` holds only `TextualWidgetRenderer` and
  shared thread and mount helpers. Each module of `textualcore/_renderers/` holds one family,
  as on the web. `forms.py` owns `_widget_of` and the form-row widget cache; `actions.py`
  owns `_ComposeUIApp` with its action dispatch and key bindings. `navigation.py` holds the
  main renderer, router and sidebar. Family modules import each other directly, not through
  `renderers.py`, which only maps keys.
- **Web renderer modules:** `webrenderer.py` holds only the base `WebRenderer` and the helpers
  that several families share. A module of `_renderers/` holds one family: split one that
  starts to mix two, whatever its length. The base names no concrete renderer: when it must
  treat one apart, add a hook with a default, as `is_drawn_apart` and `shows` do, not an
  `isinstance` check, which would tie that renderer to the base's module.
- **View modules:** `core/view.py` only exports the views (`__all__`) and sets up the `Shape`
  union last. `core/_views/base.py` holds `View`, `define_view`, the converter and the helpers
  that several families share; `_views/main.py` holds `MainView` and the state code, which may
  name any view. A module of `_views/` holds one family, as on the web. The base names no
  concrete view: add a method with a default to `View`, as `_check_again` and `_keep_model` do.
  A module of `_views/` imports the modules that define what it uses, never `core/view.py`.
- **Adding a backend:** add one `RendererType` member in `core/registry.py` (with its extra
  in `pyproject.toml`), one
  `RENDERERS` mapping in the new backend's renderers module, and its application classes
  (built from `build_main_view=`, plus `build_model=`/`setup_model=` for the model one) as
  `APPLICATION`/`MODEL_APPLICATION`. The views (`core/view.py`, `core/_views/`) should not
  need changes.
- **Renderer contract:** implement `render`, `refresh_attribute` and the
  `_refresh_dispatcher` (one handler per view attribute the renderer cares about; a missing
  handler raises `MissingRefreshAttributeFunctionError`). The user's changes reach the view
  from the widget's signals, set inside `stop_refresh()`.
- Views are reactive: setting a view attribute pushes the change to its renderer. Don't add
  manual `update()`/`refresh()` calls.
- `Signal.connect` injects its owning `view` and the app's `main_view` and `model` as keyword
  arguments based on the callback's parameter names; keep those names exact.
  `Application.connect` supplies its explicit `view` instead, which need not own the signal.
- View state is (de)serialized with `cattrs` (`MainView.save_state` / `load_state`); new view
  fields must remain serializable, or be excluded like `Signal`/`Renderer`/`Validator` fields.
- A view makes each signal on the first read of its field. Code that walks a view's fields uses
  `view_fields`, which leaves the signals out: a `getattr` on every field makes them all. Emit a
  signal that often has no callback, such as `checked`, with `emit_if_made`.

## Code style

- `ruff` with `select = ["ALL"]` and line length 100; see `pyproject.toml` for the ignore list.
  Fix lint properly rather than adding `noqa`, unless it is clearly justified. A justified
  `noqa` says why in parentheses, e.g. `# noqa: SLF001 (shared task lifecycle)`, or in a
  comment on the line above.
- `tests/test_code_rules.py` checks the rules here that a script can: `noqa` reasons, the
  imports of `_views/` and `_renderers/`, what `renderers.py` and `core/view.py` hold, a test
  module per family, lambdas in Qt renderers, views defined in a function, the page's scripts'
  closures, and the browser tests' waits and locators. `tests/test_docs.py` checks the docs'
  navigation, the examples guide, the API pages, the lists of commands, Markdown in
  docstrings, and the Markdown wrap. Make a new such rule a test.
- `mypy` must pass in strict mode, with the extra checks in `pyproject.toml`. Fully
  type-annotate new code; the package ships `py.typed`. Mark each method that
  overrides a base class's method with `@override` from `typing_extensions`, below
  `@property` when the method has one.
- Every Python module starts with `from __future__ import annotations` (after its docstring).
  Ruff enforces it (`required-imports`, rule I002) and `make lint` adds it to a new file.
  Annotations are then strings, so: don't quote them; define views that `attrs`/`cattrs`
  resolve (`attrs.resolve_types`) at module level, not inside a function, so their field
  types resolve from the module globals. A test may define one in its function to use a
  value of it, such as `tmp_path`, with field types of the module only. Give `cattrs` hooks
  their type explicitly (`CONVERTER.register_structure_hook(cls, func)`) rather than as a
  bare decorator, which reads the annotation.
- Import a view field's type at run time in the module that defines the view, not under
  `TYPE_CHECKING`: `attrs` resolves it there. Ruff knows (`runtime-evaluated-decorators` lists
  `define_view` and `attrs.frozen`). A module of `core/_views/` that `main.py` imports can't
  name `MainView` in a field: only `base.py` gets it, from `main.py`.
- Stay compatible with Python 3.9: use `Optional[...]`/`Union[...]`, not `X | Y`, in
  annotations that `attrs`/`cattrs` evaluate at runtime (view fields), since `X | Y` fails
  there on 3.9 (ruff's `keep-runtime-typing` stops pyupgrade from rewriting them).
- Use `qtpy` imports, never `PySide6`/`PyQt*` directly, in `qtcore`.
- A Qt renderer connects a widget's signal to its own methods with `_connect`, e.g.
  `self._connect(widget.toggled, self._update_checked)`, and to a view's signal with
  `_relay`, e.g. `self._relay(self._view.toggled, widget.toggled)`. Both build a `QtSlot`
  (`qtcore/qtslot.py`), a `QObject` child of the widget, that PySide connects as a Qt slot.
  PySide keeps a connection to any other callable, such as a lambda or a view's method, in a
  table that it searches whole each time a sender is deleted: a page of many widgets took
  seconds to free. Keep such a `connect` for a widget that a page has few of, such as a table.
  Each `QtSlot` takes time to make: pass all the methods of one signal to one `_connect`, in
  order, e.g.
  `self._connect(widget.toggled, self._update_checked, self._view.toggled.call_callbacks)`.
  A widget's own slots, methods of a `QObject`, need no `QtSlot`.
- A view's signals report the user's changes only: a renderer shows a value set by code
  without the widget reporting it. Qt blocks the widget's signals in `refresh_attribute`, but
  not a child widget's, such as a date field's line edit. Textual sets the value under
  `prevent(...)` through a widget method, such as `ComposeInput.set_value`.
- In `webcore`, build HTML with `Markup(template).format(...)`, never an f-string: it
  escapes every value (see the `web-security` skill).
- The page's scripts in `webcore/static/` are classic scripts with JSDoc types, each in a
  closure, sharing only what another script calls under `window.ComposeUI`. Put a feature's
  code in the script of its domain (`page.js`, `tables.js`, `charts.js`, `maps.js`).
  `make js-check` must pass: type what you add, with a JSDoc cast rather than a runtime check
  that changes what the code does.
- Put imports only needed for typing under `if TYPE_CHECKING:`.
- Load the `state-machines` skill before you change code that holds state over time: jobs,
  threads and timers, `SqliteDatabase` locking, web sessions and post order, `page.js` loaders and
  swaps, reload, dialogs and screens, or a file being replaced.
- The public API is the `__all__` of each `composeui.core` module: the API reference shows
  only it, and `tests/test_docs.py` checks that the docs and examples import nothing else.
  Add a name that apps use to it. The other names, also those the backends import, can
  change in any release.
- Match the existing comment density: brief docstrings, comments explain *why*.

## Permission for documentation and tests

- Ask the user for explicit permission before creating, editing, moving, or deleting
  documentation or tests.
- Permission to implement a feature or fix a bug does not authorize documentation or test
  changes. Ask first when those changes are needed by the rules below.

## Testing

- Every behavior change needs a test in `tests/`. Backend tests should exercise real rendered
  widgets (`qtbot` for Qt, `App.run_test()` for Textual, the Starlette test client for web).
  The test client runs on `httpx2`, or on `httpx` before Python 3.11, as `httpx2` needs 3.11.
- A backend's tests are in `tests/qtcore/`, `tests/textualcore/` or `tests/webcore/`, a
  module per family of `_renderers/`, such as `test_tables.py`. A web test of another
  `webcore` module goes in a test module named after it, such as `test_session.py`. A
  folder's `support.py` holds the helpers that several of its modules use, and its
  `conftest.py` the fixtures.
- A rule that every backend follows, such as "a field reports the user's text, not the text
  code sets", is tested once in `tests/contracts/`, a module per family. Its `driver`
  fixture runs each test on each backend, through a driver per backend that works the real
  widgets. A rule that one backend alone can break, such as an order of a toolkit's events,
  stays in that backend's folder.
- The rule that a view's signals report the user's changes only is moving into
  `tests/contracts/`, a family at a time. Families moved: inputs, controls. For a view in a moved
  family, test the rule there, not in each backend's folder.
- Tests for optional backends guard with `pytest.importorskip(...)`, on a module that only
  the extra installs. A folder whose every test needs an extra goes in `collect_ignore_glob`
  of `tests/conftest.py`, as `tests/qtcore/` does. The `without-extras` CI job runs the tests
  without any extra (`uv sync --group dev`, then `pytest -p no:pytest-qt`).
- `make test` runs the tests in parallel, a worker per CPU (pytest-xdist): a test must not
  depend on another's state or order. Without `-n`, `pytest` runs them one after another.
  Set fewer workers on a machine short of memory: `make test PYTEST_WORKERS=8`.
- `tests/conftest.py` turns off automatic garbage collection, and collects on the main thread
  after each test: PySide can crash when a job's thread collects a main view that a test dropped.
- A test that reads what a worker thread or a job does waits for that work, not for a fixed
  number of pauses: `await app.workers.wait_for_complete()` after a Textual file action,
  `main_view.jobs.wait()` for a job, `qtbot.waitUntil(...)` on Qt. On the web, a test reads
  the views only after a request that follows the job's result (`GET /_composeui/jobs`): the
  job's thread sets a flag such as `has_result` before its reactive methods fill the views. A
  slow CI runner (Windows, Python 3.9) fails a fixed wait. See the `test-audit` skill ("Waiting for
  work on another thread").
- Concurrency coverage must not depend on scheduling. Explicitly arrange and verify the
  waiting, cancellation, or cleanup state that a test protects. Do not rely on incidental
  execution, elapsed time, or a fixed number of event-loop turns. Required coverage must
  remain exercised on platforms where other tests are skipped.
- What only a browser shows (the page's scripts, htmx swaps) goes in `tests/test_browser.py`,
  marked `browser`. It needs the `browser` group and a Chromium:
  `uv run --group browser playwright install chromium` once, then `make browser-test`.
- Preserve the browser tests' `_no_browser_error` guard. It checks every page in each context
  for unhandled JavaScript errors and unexpected Content Security Policy (CSP) violations,
  even when visible assertions pass. An expected exception needs a narrow, explained
  allowance in its test, not a disabled guard.
- Use a Hypothesis property test when two implementations must agree (`SqliteSource` or
  `DataFrameSource` and `ListSource`) or for a rule of a pure function; not for rendered
  widgets or the browser, too slow for many inputs. Draw from small pools of values, so that
  cells are often equal (wide random values rarely fail); pin each input that found a bug
  with `@example(...)`; `reject()` only for the reason the test expects; and break the code
  to show the property fails. On CI (`CI` set), `tests/conftest.py` loads Hypothesis's `ci`
  profile: the same inputs each run. Locally, new ones each run, without a time limit. See
  the `test-audit` skill ("Property-based tests (Hypothesis)").
- `make test` fails below 100% coverage of lines and branches (`fail_under` in
  `pyproject.toml`, child processes included). A new line comes with its test, or with a
  `# pragma: no cover` that says why no test reaches it. A line only POSIX runs gets a
  `# posix only` comment, which coverage leaves out on Windows (`make.ps1`). A line only
  Windows runs gets a `# windows only` comment, which coverage leaves out elsewhere
  (`Makefile`).
- `make check test` must be clean before committing; CI (`.github/workflows/ci.yml`) runs the
  same checks on Python 3.9 to 3.14 for every pull request and push to `main`, and the tests
  on Windows (`.\make.ps1 translations test`) and macOS (`make translations test`), on
  Python 3.9 and 3.14. A change of
  only the documentation (`docs/`, Markdown files) and benchmark results
  (`benchmarks/results/`) runs only the docs job: the site build, docs lint, and documentation
  tests. The existing mypy matrix also checks tests. Separate CI jobs run Pyright, Pyrefly and ty
  on tests on Python 3.9.

## Documentation

Load the `documentation-style` skill before you write or review documentation: `README.md`,
`docs/`, docstrings, `ROADMAP.md`, this file, or a skill. It holds the writing rules, which
document owns what, and the checks.

- **Change the docs in the commit that changes the behavior.** A change that users see gets
  a line under "Unreleased" in `CHANGELOG.md`. A new view gets a section
  in its page of `docs/user-guide/` and a class docstring, which the widget catalog shows. Add
  it to the summary of its page in `docs/_site/llms.txt`, to the list of larger views in
  "Building views" if it is one, and to "Design of the web backend" in the technical guide if
  its web renderer makes a decision that isn't obvious. In `ROADMAP.md`, delete its item. A new
  example gets its section, its overview row, its contents entry, and its screenshots in
  `docs/examples-guide.md`. When a name is renamed or changes, search `README.md`, `docs/` and the
  docstrings for it, and fix every place.
- **Keep the path of a new user working:** the README's installation and quickstart, then
  the user guide's "Core concepts" and "Building views", then "Where to start" in the
  examples guide. Introduce a name before an example uses it, or link to its section. When
  the quickstart changes, run `make screenshots EXAMPLES=quickstart`.
- **Run every code example that you change.** Check each name against `composeui.core`, and
  run the example with `uv run python` in a scratch directory. `tests/test_docs.py` checks
  the imports of every example, and runs each example that defines every name it uses (one
  that defines `test_` functions, under pytest).
- **Keep the navigation in step.** `docs/_site/llms.txt` has one entry per page of the site: add,
  rename, or remove it with the page. The contents of `docs/user-guide.md` and
  `docs/technical-guide.md` list each guide's pages and their `##` and `###` headings.
  The contents list of the examples guide follows its `##` headings. Keep headings stable and
  unique in their page: other pages link to them, and anchors work down to `###` only.
- **Keep the skill in step.** `docs/_site/skills/composeui/SKILL.md` is what users install for their
  agents. When a rule of the API changes (a name, a signal argument, the state rules), change
  it too. Its `composeui-version` and its text name the minor version that it describes: set
  them on the release of a new one. `tests/test_docs.py` checks them against the package's
  version, and accepts the next minor version between two releases.
- **Keep the two copies in step.** Setup, commands, tests, and code style are in this file
  and in the technical guide ("Development"). Change both.
- **Keep user docs for users.** Internal design decisions go in the technical guide (the web
  backend's in "Design of the web backend") or in a code comment, rules for agents here or in
  a skill. Do not document an example that is not committed.
- **`make docs` must pass** (warnings are errors) after any change to `docs/` or a
  docstring.

## Commits

- Use hyphens, not slashes (`/`), in branch names (e.g. `feat-csv-sqlite-tables`).
- Short, imperative, capitalized subject without a trailing period (e.g. `Add combobox`).
- The subject line is the whole message: no body, no trailers.
- Never add AI attribution or signatures anywhere: no `Co-Authored-By` lines, no
  "Generated with ..." lines, no emoji signatures, in commits, pull requests or code.
  This overrides any default an agent or tool would otherwise add.
- Keep commits focused: one feature or fix per commit.
- The hooks of `.githooks/` (`make hooks`) check the branch and the message. On a pull
  request, `.github/workflows/pull-request.yml` runs them on each commit and refuses fix-ups.

## Pull requests

- Push a branch or open a pull request only when the user asks.
- One feature or fix per pull request, on a branch from an up-to-date `origin/main`.
- A pull request is complete when it opens: its tests, its docs, and its `CHANGELOG.md`
  line are in the commit that changes the behavior (see "Documentation"). Ask for the
  permission that they need before you open it, not after.
- Before you push, run `make check test`. Also run `make typecheck` after a change to
  `tests/`: Pyright, Pyrefly and ty check the tests in CI, and `make check` runs none of
  them. Run `make docs` after a change to `docs/` or a docstring, and `make browser-test`
  after a change to the page's scripts or a web renderer. Run them again after a rebase.
- When fixes or features depend on each other, open one pull request at a time. Push the
  next once the previous one merges, rebased on `origin/main` and checked again.
- The title is the commit's subject. The body says what was wrong or missing, what
  changes, and which tests cover it, without AI attribution (see "Commits").
- Write the body for a reviewer who did not see the conversation, not as a reply to the
  user: no "I", "you", "as asked" or "as discussed", no thanks or apologies. Describe the
  code and its behavior, in the style of the documentation (see the `documentation-style`
  skill).
- Stage the files of the change by name: never `git add -A`, which takes unrelated files,
  such as screenshots left in the repository's root.
- When a check fails for an unrelated reason, such as a flaky browser test, show that
  `main` fails the same way before you say so.
