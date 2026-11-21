# Development

This page covers how to set up the repository, check a change, and publish a release.

## Setup

ComposeUI uses [uv](https://docs.astral.sh/uv/) and Python 3.9 or later. `.python-version`
pins 3.9. Install every backend, because the tests cover Qt, Textual, and the web:

```bash
uv sync --group dev --all-extras   # extras: pyside6, tui (Textual), web (Starlette), report, terminal-images, reload
```

Always run the tools through `uv run` or the `make` targets, never a global Python.

## Commands

```bash
make lint          # ruff format + ruff check --fix
make mypy          # mypy on composeui, examples and tests, Qt binding resolved to PySide6
make typecheck     # mypy on source + tests; Pyright, Pyrefly and ty on tests
make pyright pyrefly ty  # individual test checkers
make test          # pytest in parallel, with coverage (browser tests excluded)
make browser-test  # the web backend in headless Chromium (tests/test_browser.py, Playwright)
make translations  # each app's catalogs against the text it translates
make js-check      # the page's scripts against their JSDoc types (TypeScript's compiler)
make check         # lint + mypy + translations + js-check
make all           # clean + check + test
make css           # rebuild webcore/static/app.css after changing classes in webcore
make web-deps      # download htmx, uPlot, Cally and deck.gl at pinned versions (commit them)
make docs          # build the documentation site into docs/_build/html
make screenshots   # the screenshots of the examples guide, on every backend
```

On Windows without `make`, use the matching targets in `make.ps1`. To run the same checks as
the Windows job in CI, run `.\make.ps1 translations test`. The Linux `check` job runs
`make mypy`. The `browser` job runs `make js-check`. Locally, `make check` includes both.

In PowerShell, pass `EXAMPLES` as `-Examples pipeform, batman`, `TAILWIND_PLATFORM` as
`-TailwindPlatform`, and `TSC_PLATFORM` as `-TscPlatform`. When you change a target in the
`Makefile`, change it in `make.ps1` too.

`make mypy` checks source, examples, and tests together. It installs the `browser` group and
all extras so every test import resolves; Chromium is not needed. The other checker targets
also install the `typecheck` group. Use an individual target to run one checker, or
run `make typecheck` to run all four.

The `browser` group includes Playwright. The locked version of its `greenlet` dependency
has no prebuilt wheel for Python 3.9 on Windows x64. To install that group on this platform,
use Python 3.13, as the browser job does, or use a C++20 compiler to build `greenlet`.

Run the examples with `uv run python -m examples.pipeform --backend qt`, or `textual`, or
`web`.

## Tests

Every behavior change needs a test in `tests/`.

- Backend tests exercise real rendered widgets: `qtbot` for Qt, `App.run_test()` for
  Textual, and the Starlette test client for the web. It runs on `httpx2`, or on `httpx`
  before Python 3.11, as `httpx2` needs 3.11.
- Tests for an optional backend guard with `pytest.importorskip(...)`.
- `make test` runs the tests in parallel, a worker per CPU (pytest-xdist). So a test must
  not depend on the state or the order of another. `pytest` without `-n` runs them one
  after another.
- `tests/conftest.py` turns off automatic garbage collection, and collects on the main thread
  after each test. PySide can crash when a job's thread collects a main view that a test dropped.
- A test that reads what a worker thread or a job does waits for that work, not for a fixed
  number of pauses. After a Textual file action (Open, Save, Save As, `PickFileAction`),
  call `await app.workers.wait_for_complete()`. For a job, call `main_view.jobs.wait()`. On
  Qt, use `qtbot.waitUntil(...)`. On the web, read the views only after a request that follows
  the job's result (`GET /jobs`). The job's thread sets a flag such as `has_result` under the
  session's lock, before its reactive methods fill the views. A fixed wait passes on a fast
  machine and fails on a slow CI runner, such as Windows with Python 3.9.
- Concurrency coverage must not depend on scheduling. Explicitly arrange and verify the
  waiting, cancellation, or cleanup state that a test protects. Do not rely on incidental
  execution, elapsed time, or a fixed number of event-loop turns. Required coverage must
  remain exercised on platforms where other tests are skipped.
- Qt tests in a headless environment (CI, WSL) need `QT_QPA_PLATFORM=offscreen`.
  `make test` sets it. To run one file or test:

  ```bash
  QT_QPA_PLATFORM=offscreen uv run pytest tests/test_qtrenderer.py -k combobox
  ```

- What only a browser shows, such as the page's scripts and htmx swaps, goes in
  `tests/test_browser.py`, marked `browser`. These tests need the `browser` group and
  Chromium. Install Chromium once with `uv run --group browser playwright install chromium`,
  then run `make browser-test`.
- Preserve the browser tests' `_no_browser_error` guard. It checks every page in each context
  for unhandled JavaScript errors and unexpected Content Security Policy (CSP) violations,
  even when visible assertions pass. An expected exception needs a narrow, explained
  allowance in its test, not a disabled guard.
- A property-based test, with [Hypothesis](https://hypothesis.readthedocs.io/), checks a
  rule for many inputs that Hypothesis makes. Use one when two implementations must agree,
  such as `SqliteSource` or `DataFrameSource` and `ListSource`. Use one also for a rule of
  a pure function, such as a date read back as it was shown. Do not use one for rendered
  widgets or the browser: they are too slow for many inputs.
  - Make the inputs from a small set of values, so that cells are often equal, or equal
    except for their case. Wide random values rarely make the input that fails.
  - Add each input that found a bug with `@example(...)`, so that each run tries it.
  - Discard an input (`reject()`) only for the reason that the test expects, never for
    another error.
  - Break the code that the property checks, and make sure that the test fails. Then
    restore the code.
  - `tests/conftest.py` removes the time limit of each input. On CI (`CI` set),
    Hypothesis's `ci` profile tries the same inputs on each run, so a pull request fails
    for its own change only. A local run makes new inputs on each run.
- `make test` fails when the coverage of lines and branches is below 100% (`fail_under` in
  `pyproject.toml`). Coverage also counts the child processes that the reload tests start.
  Add a test with each new line. When no test can reach a line, mark it
  `# pragma: no cover` and say why in a comment.
- A line that only POSIX runs, such as the kill of a process that ignores its
  termination, gets a `# posix only` comment. On Windows, `make.ps1` sets
  `COMPOSEUI_POSIX_ONLY`, and coverage leaves these lines out.
- A line that only Windows runs, such as the threads that read a process's output, gets a
  `# windows only` comment. On Linux and macOS, the `Makefile` sets
  `COMPOSEUI_WINDOWS_ONLY`, and coverage leaves these lines out.

## Translations

`make translations` checks the catalogs of each app in `TRANSLATED_MAIN_VIEWS` of the
`Makefile`, and `make.ps1` has the same list in `$TranslatedMainViews`. When you translate a
new app, add its main view to both. See
[Checking the catalogs](../user-guide/translation.md#checking-the-catalogs).

## Styles of the web backend

`webcore/static/app.css` is built from `css/` with Tailwind and daisyUI. When you change
the classes used in `webcore`, run `make css`, and commit the built file. `make css`
downloads the Tailwind CLI and the daisyUI files once, into `css/vendor/`, which is not
committed. It needs no Node or npm. It checks the SHA-256 of each file against the one in the
`Makefile` and `make.ps1`, and fails when they differ. When you change `TAILWIND_VERSION` or
`DAISYUI_VERSION`, change the SHA-256 values in both files, and delete `css/vendor/`. A new
daisyUI version also needs `make web-deps`, which downloads its license.

The page's scripts are committed in `webcore/static/`: htmx, uPlot, Cally, and deck.gl.
uPlot's stylesheet, `css/uPlot.min.css`, is committed too. The package then needs no
download, and the page works offline. `make web-deps` downloads these files from npm at the
versions in the `Makefile`, and checks their SHA-256. It adds Cally's license to `cally.js`
as a comment. It keeps the licenses of deck.gl and uPlot beside their scripts, in
`deckgl.LICENSE` and `uPlot.LICENSE`, and daisyUI's beside `app.css`, in `daisyui.LICENSE`.
`make js-check` downloads TypeScript's compiler once into `js/vendor/`, which is not
committed, as `make css` does Tailwind. It checks the archive's SHA-256 against the one in the
`Makefile` and `make.ps1`. When you change `TSC_VERSION`, change the SHA-256 values in both
files, and delete `js/vendor/`.

`make web-deps` also downloads the declarations of htmx and uPlot into `js/`, for
`make js-check`. They don't go in the package. To update one of them:

1. Change its version and its SHA-256 in the `Makefile` and in `make.ps1`.
2. Change its version in the comments of `webcore/page.py`.
3. Run `make web-deps css`, then the tests, and commit the files.

## Code style

- `ruff` lints with `select = ["ALL"]` and a line length of 100. `pyproject.toml` has the
  ignore list. Fix lint properly rather than adding `noqa`, unless it is clearly justified.
  A justified `noqa` says why in parentheses, e.g. `# noqa: SLF001 (shared task lifecycle)`.
- `mypy` must pass in strict mode, with the extra checks in `pyproject.toml`. Fully
  type-annotate new code: the package ships `py.typed`. Mark each method that
  overrides a base class's method with `@override` from `typing_extensions`, below
  `@property` when the method has one.
- Every Python module starts with `from __future__ import annotations`, after its
  docstring. Ruff enforces it (`required-imports`, rule I002), and `make lint` adds it to a
  new file. The annotations are then strings:
  - Do not quote them.
  - Define the views that `attrs` and `cattrs` resolve at module level, not inside a
    function, so that their field types resolve from the module's globals.
  - Give a `cattrs` hook its type explicitly, with
    `CONVERTER.register_structure_hook(cls, func)`, not as a bare decorator, which reads
    the annotation.
  - Import the type of a view field at run time, not under `TYPE_CHECKING`, in the module
    that defines the view: `attrs` resolves it there. Ruff checks it:
    `runtime-evaluated-decorators` lists `define_view` and `attrs.frozen`. A module of
    `core/_views/` that `main.py` imports cannot name `MainView` in a field. Only `base.py`
    has it, which `main.py` gives it (see [Views and renderers](architecture.md#views-and-renderers)).
- Stay compatible with Python 3.9. In the annotations that `attrs` and `cattrs` evaluate at
  runtime, such as view fields, use `Optional[...]` and `Union[...]`, not `X | Y`.
- In `qtcore`, import Qt from `qtpy`, never from `PySide6` or `PyQt*`.
- In a Qt renderer, connect a widget's signal to a method of the renderer with
  `self._connect(widget.toggled, self._update_checked)`, and to a view's signal with
  `self._relay(self._view.toggled, widget.toggled)`. Both helpers build a `QtSlot`
  (`qtcore/qtslot.py`): a `QObject` child of the widget, which PySide connects as a Qt slot.
  PySide keeps a connection to any other callable, such as a lambda or a view's method, in a
  table, and searches the whole table each time a sender is deleted. A page of many widgets
  then took seconds to free. Call `connect` with such a callable only for a widget that a
  page has few of, such as a table. Each `QtSlot` takes time to make, so pass all the
  methods of one signal to one `_connect`, in order:
  `self._connect(widget.toggled, self._update_checked, self._view.toggled.call_callbacks)`.
  A widget's own slots are methods of a `QObject`, and need no `QtSlot`.
- A view's signals report the user's changes only, so a renderer shows a value set by code
  without the widget reporting it. Qt blocks the widget's signals in `refresh_attribute`, but
  not the signals of a child widget, such as the line edit of a date field. Textual sets the
  value under `prevent(...)` through a method of the widget, such as `ComposeInput.set_value`.
- In `webcore`, build HTML with `Markup(template).format(...)` from `markupsafe`, never with
  an f-string. `format` escapes every value that is not `Markup` itself.
- The page's scripts in `webcore/static/` are classic scripts with JSDoc types, each in a
  closure, sharing only what another script calls under `window.ComposeUI`. Put a feature's
  code in the script of its domain (`page.js`, `tables.js`, `charts.js`, `maps.js`).
  `make js-check` must pass: type what you add, with a JSDoc cast rather than a runtime check
  that changes what the code does.
- Put imports that only typing needs under `if TYPE_CHECKING:`.
- Before you change code that holds state over time, write down its states and events, and what
  each event does in each state. The `state-machines` skill gives the method. It applies to jobs,
  threads and timers, `SqliteModel` locking, web sessions and post order, `page.js` loaders and
  swaps, reload, dialogs and screens, or a file being replaced.
- The `__all__` of each module of `composeui.core` is its public API. The API reference
  shows only these names, and `tests/test_docs.py` checks that the docs and the examples
  import no other name. Add a name that apps use to `__all__`. The other names, also those
  that the backends import, can change in any release.
- Match the comment density of the code around: brief docstrings, and comments that explain
  why.

## Documentation site

`make docs` builds the documentation site with Sphinx and MyST into `docs/_build/html`.
The site holds the guides, a widget catalog, and an API reference. Install the `docs` group
and every extra first, because the API reference imports the application module of each
backend:

```bash
uv sync --group dev --group docs --all-extras
```

- **The guides stay Markdown.** MyST builds the Markdown pages in `docs/` and its guide
  directories. A link from a guide to a file outside `docs/`, such as `../src/examples/pipeform.py`,
  goes to that file on GitHub (`docs/conf.py`).
- **The user and technical guides have one page per topic.** The first page of each guide lists
  its pages and their sections. Its `toctree` orders the pages. Add a new page to both lists.
- **The API reference is built from the docstrings.** Each page in `docs/api/` runs
  `automodule` in an `{eval-rst}` block, because autodoc writes reStructuredText. In a
  docstring, single backticks link to the name they hold. When you add a module to
  `composeui.core`, add its page and its entry in `docs/api/index.md`.
- **The widget catalog is built from the views.** The `widget-catalog` directive
  (`docs/_ext/widgetcatalog.py`) lists each view of the modules of `core/_views/` that has a
  `_renderer_key`, by module, with the first paragraph of its docstring. A column per backend says
  whether its `RENDERERS` has the key. A new widget, or a new backend, is in the catalog
  without a change to `docs/widgets.md`.
- **A warning fails the build**, as a broken link or a docstring that autodoc cannot read.
- **`tests/test_docs.py` checks examples and navigation.** Each name that a Python block of the
  README, the guides, or the skill imports from `composeui` must be public. A block that defines
  every name it uses must run in a scratch directory. A block that defines `test_` functions
  must pass under pytest. The contents of each guide must list its pages and their `##` and `###`
  headings. Links in the README to the site or repository must have a target.
- **The screenshots of the examples are taken by a script.** `make screenshots` runs
  `docs/screenshots.py`, which writes `docs/images/<example>-<backend>.png` for Qt,
  Textual, and the web, in the light theme. The script sets each example up first, for
  example by filling in its form or running its job, so every backend shows the same
  state. It needs the `browser` group and Chromium, as `make browser-test` does. When an
  example changes what it shows, update its setup in the script, run
  `make screenshots EXAMPLES=<example>`, and commit the images. The script also takes
  `docs/images/quickstart-web.png` for the README. It runs the code of the README's
  quickstart, so run `make screenshots EXAMPLES=quickstart` when the quickstart changes.

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and every push to `main`. It runs
the lint, `make mypy`, `make translations`, and `make test` on Python 3.9 to 3.14, and
`make js-check`, `make browser-test` and `make docs` on Python 3.13. On Windows, it runs
`.\make.ps1 translations test`, and on macOS `make translations test`, on Python 3.9 and
3.14. Run `make check test` before you commit.

The existing mypy matrix checks source, examples, and tests together. Separate jobs run
`make pyright`, `make pyrefly`, and `make ty` on tests on Python 3.9, matching their
configuration. Failures in these jobs fail the workflow. Run `make typecheck` locally to
run all four type checkers.

A change of the documentation and the benchmarks' results only, in `docs/`, the Markdown files
and `benchmarks/results/`, runs only the `docs` job. That job also lints the Python files of
`docs/` and runs `tests/test_docs.py`.

On a push to `main` or a `v*` tag, the `pages` job publishes two versions to GitHub Pages.
Current `main` is at https://ehmoussi.github.io/composeui/. The latest release is at
https://ehmoussi.github.io/composeui/stable/. The sidebar dropdown selects either version.
A pull request builds both versions without publishing them.

The docs job selects the highest version tag that matches `v[0-9]*`. It builds that tag's
guides, widget catalog, and API reference in a separate environment. Only `docs/conf.py`,
the sidebar templates, and the version selector's CSS and JavaScript come from the current site.
`COMPOSEUI_DOCS_REF` sets the version label, repository links, and canonical URL.
`COMPOSEUI_DOCS_LATEST_TAG` sets the release option. Without it, the build uses the highest
local version tag. A local `make docs` build defaults to `main`. Each version generates its
own `sitemap.xml` with its published URLs. Switching versions opens that version's home page.

## Release

`.github/workflows/release.yml` publishes the package to PyPI with
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/): PyPI trusts the workflow,
so the repository stores no token.

Once, on [PyPI](https://pypi.org/manage/account/publishing/) and on
[TestPyPI](https://test.pypi.org/manage/account/publishing/), add a publisher for the
project `composeui`: the owner `ehmoussi`, the repository `composeui`, the workflow
`release.yml`, and the environment `pypi` (`testpypi` on TestPyPI). In the repository's
settings, add the two environments.

To release a version, for example 0.3.0:

1. On `main`, give the version's entry in `CHANGELOG.md` its date
   (`## [0.3.0] - 2026-11-20`), and set the `composeui-version` of the agent skill and its
   text to the minor version (`0.3`).
2. Tag `main`'s commit, and push the tag. Name the commit: a pull request's merge makes a new
   commit, so its branch's commit is not in `main`'s history, and a tag on it would leave the
   next development versions counting from the previous tag.

   ```bash
   git fetch origin
   git tag -a v0.3.0 -m v0.3.0 origin/main
   git push origin v0.3.0
   ```
3. In the run of the Release workflow, approve the deployment to `testpypi`, then the one to
   `pypi` (Review deployments). Each environment asks for a reviewer.

The tag runs the tests again, then builds the package. Before it publishes, the workflow
checks that the build's version is the tag's, and that `CHANGELOG.md` has a dated entry for
it; the tests check the skill's version. Then it publishes to TestPyPI. On Python 3.9 and
3.13, it installs the version from there with the `web` extra, takes its dependencies from
PyPI, imports each module of `composeui.core` and runs `composeui --help`. Only then does it
publish to PyPI, and create the tag's GitHub release, with the changelog entry as its notes
and the built files. TestPyPI keeps a version that is already there, so a rerun of the tag
does not fail on it.

A manual run of the Release workflow, in the repository's Actions, is a dry run: it stops
after the install from TestPyPI. It publishes a development version of the commit that it
runs on. setuptools-scm numbers it after the last tag, with its next patch version, such as
`0.2.1.dev12` after `v0.2.0`: only the tag gives the release's version.
