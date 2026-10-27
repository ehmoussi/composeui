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
  uv sync --group dev --all-extras   # extras: pyside6, tui (Textual), web (Starlette), report, reload, dataframe
  ```

- Always run tools through `uv run` (or the `make` targets below), never a global Python.

## Commands

```bash
make lint    # ruff format + ruff check --fix
make mypy    # mypy on composeui, examples and tests, Qt binding resolved to PySide6
make typecheck  # mypy on source + tests; Pyright, Pyrefly and ty on tests
make pyright pyrefly ty  # individual test checkers
make zuban   # optional test checker; currently reports known incompatibilities
make test    # pytest tests in parallel, Qt offscreen, with coverage (browser tests excluded)
make browser-test  # the web backend in headless Chromium (tests/test_browser.py, Playwright)
make translations  # each app's catalogs against the text it translates (TRANSLATED_MAIN_VIEWS)
make check   # lint + mypy + translations
make all     # clean + check + test
make css     # rebuild webcore/static/app.css after changing classes in webcore (commit it)
make web-deps  # htmx, uPlot, Cally and deck.gl from npm at pinned versions and SHA-256 (commit them)
make docs    # Sphinx + MyST site in docs/_build/html, warnings as errors (needs `--group docs`)
make screenshots   # docs/images/<example>-<backend>.png for the docs and README (Chromium)
```

On Windows without `make`, run the same targets in PowerShell with `make.ps1`
(`.\make.ps1 check test`; `-Examples pipeform, batman` for `EXAMPLES`, `-TailwindPlatform`
for `TAILWIND_PLATFORM`). Keep it in step with the `Makefile`, including its
`$TranslatedMainViews` list (`TRANSLATED_MAIN_VIEWS`).

`make mypy` checks source, examples and tests together. It installs the `browser` group and
all extras so every test import resolves; Chromium is not needed. The other checker targets
also install the `typecheck` group. The same targets are available in `make.ps1`.
Zuban is excluded from the aggregate target and retains its nonzero exit status when
diagnostics remain.

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
src/examples/    # example apps (pipeform.py, pipecatalogue.py, ...), also used by tests; not in the wheel
tests/           # pytest suite (pytest-qt, pytest-asyncio, Textual run_test pilot)
docs/            # user guide, examples guide, technical guide; Sphinx site (conf.py, api/, _ext/)
```

## Architecture rules

- **`composeui.core` must never import a backend** (Qt, Textual, Starlette) at import time.
  Backends are resolved lazily through `composeui.core.registry`.
- **Backend registration:** each `RendererType` member's value is a `Backend`: the dotted
  paths of the backend's renderers module, exposing a
  `RENDERERS: dict[str, Callable[[Any], Renderer]]` mapping, and of its application module,
  exposing `APPLICATION` and `MODEL_APPLICATION` (what `core.application.run` starts). A
  view picks its renderer by its `_renderer_key` class variable. A backend that doesn't
  register a key simply doesn't render that view (returns `None`), so partial backends are
  fine.
- **Adding a widget:** define the view in `core/view.py` (set `_renderer_key`), then add a
  renderer + `RENDERERS` entry in each backend that should support it, plus tests per backend.
- **Adding a backend:** add one `RendererType` member in `core/registry.py`, one
  `RENDERERS` mapping in the new backend's renderers module, and its application classes
  (built from `build_main_view=`, plus `build_model=`/`setup_model=` for the model one) as
  `APPLICATION`/`MODEL_APPLICATION`. `core/view.py` should not need changes.
- **Renderer contract:** implement `render`, `refresh_attribute` and the
  `_refresh_dispatcher` (one handler per view attribute the renderer cares about; a missing
  handler raises `MissingRefreshAttributeFunctionError`). The user's changes reach the view
  from the widget's signals, set inside `stop_refresh()`.
- Views are reactive: setting a view attribute pushes the change to its renderer. Don't add
  manual `update()`/`refresh()` calls.
- `Signal.connect` injects `main_view` and `model`, and `Application.connect` also `view`, as
  keyword arguments based on the callback's parameter names; keep those names exact.
- View state is (de)serialized with `cattrs` (`MainView.save_state` / `load_state`); new view
  fields must remain serializable, or be excluded like `Signal`/`Renderer`/`Validator` fields.

## Code style

- `ruff` with `select = ["ALL"]` and line length 100; see `pyproject.toml` for the ignore list.
  Fix lint properly rather than adding `noqa`, unless it is clearly justified.
- `mypy` must pass. Fully type-annotate new code; the package ships `py.typed`.
- Every Python module starts with `from __future__ import annotations` (after its docstring).
  Ruff enforces it (`required-imports`, rule I002) and `make lint` adds it to a new file.
  Annotations are then strings, so: don't quote them; define views that `attrs`/`cattrs`
  resolve (`attrs.resolve_types`) at module level, not inside a function, so their field
  types resolve from the module globals; and give `cattrs` hooks their type explicitly
  (`CONVERTER.register_structure_hook(cls, func)`) rather than as a bare decorator, which
  reads the annotation.
- Stay compatible with Python 3.9: use `Optional[...]`/`Union[...]`, not `X | Y`, in
  annotations that `attrs`/`cattrs` evaluate at runtime (view fields), since `X | Y` fails
  there on 3.9 (ruff's `keep-runtime-typing` stops pyupgrade from rewriting them).
- Use `qtpy` imports, never `PySide6`/`PyQt*` directly, in `qtcore`.
- In `webcore`, build HTML with `Markup(template).format(...)`, never an f-string: it
  escapes every value (see the `web-security` skill).
- Put imports only needed for typing under `if TYPE_CHECKING:`.
- Match the existing comment density: brief docstrings, comments explain *why*.

## Permission for documentation and tests

- Ask the user for explicit permission before creating, editing, moving, or deleting
  documentation or tests.
- Permission to implement a feature or fix a bug does not authorize documentation or test
  changes. Ask first when those changes are needed by the rules below.

## Testing

- Every behavior change needs a test in `tests/`. Backend tests should exercise real rendered
  widgets (`qtbot` for Qt, `App.run_test()` for Textual, `httpx`/Starlette test client for web).
- Tests for optional backends guard with `pytest.importorskip(...)`.
- `make test` runs the tests in parallel, a worker per CPU (pytest-xdist): a test must not
  depend on another's state or order. Without `-n`, `pytest` runs them one after another.
- What only a browser shows (the page's scripts, htmx swaps) goes in `tests/test_browser.py`,
  marked `browser`. It needs the `browser` group and a Chromium:
  `uv run --group browser playwright install chromium` once, then `make browser-test`.
- `make test` fails below 100% coverage of lines and branches (`fail_under` in
  `pyproject.toml`, child processes included). A new line comes with its test, or with a
  `# pragma: no cover` that says why no test reaches it. A line only POSIX runs gets a
  `# posix only` comment, which coverage leaves out on Windows (`make.ps1`).
- `make check test` must be clean before committing; CI (`.github/workflows/ci.yml`) runs the
  same checks on Python 3.9 to 3.14 for every pull request and push to `main`, and the tests
  on Windows (`.\make.ps1 translations test`, Python 3.9 and 3.14). A change of
  the documentation only (`docs/`, Markdown files) runs only the docs build and its lint.
  The existing mypy matrix also checks tests. Separate CI jobs run Pyright, Pyrefly and ty
  on tests on Python 3.9. Zuban runs in an additional non-blocking job while its known
  incompatibilities remain.

## Documentation

Load the `documentation-style` skill before you write or review documentation: `README.md`,
`docs/`, docstrings, `ROADMAP.md`, this file, or a skill. It holds the writing rules, which
document owns what, and the checks.

- **Change the docs in the commit that changes the behavior.** A new view gets a section
  in its page of `docs/user-guide/` and a class docstring, which the widget catalog shows. In
  `ROADMAP.md`, add it to "Already there" and remove its entry. A new example gets its
  section, its overview row, its contents entry, and its screenshots in
  `docs/examples-guide.md`. When a name is renamed or changes, search `README.md`, `docs/`
  and the docstrings for it, and fix every place.
- **Keep the path of a new user working:** the README's installation and quickstart, then
  the user guide's "Core concepts" and "Building views", then "Where to start" in the
  examples guide. Introduce a name before an example uses it, or link to its section. When
  the quickstart changes, run `make screenshots EXAMPLES=quickstart`.
- **Run every code example that you change.** Check each name against `composeui.core`, and
  run the example with `uv run python` in a scratch directory. `tests/test_docs.py` checks
  the imports of every example, and runs each example that defines every name it uses.
- **Keep the navigation in step.** `docs/_site/llms.txt` has one entry per page of the site: add,
  rename, or remove it with the page. `docs/user-guide.md` lists the pages of
  `docs/user-guide/` and their `##` and `###` headings. The contents list of the examples
  guide follows its `##` headings. Keep headings stable and unique in their page: other
  pages link to them, and anchors work down to `###` only.
- **Keep the skill in step.** `docs/_site/skills/composeui/SKILL.md` is what users install for their
  agents. When a rule of the API changes (a name, a signal argument, the state rules), change
  it too.
- **Keep the two copies in step.** Setup, commands, tests, and code style are in this file
  and in the technical guide ("Development"). Change both.
- **Keep user docs for users.** Internal design decisions go in `ROADMAP.md` or in a code
  comment, rules for agents here or in a skill. Do not document an example that is not
  committed.
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
