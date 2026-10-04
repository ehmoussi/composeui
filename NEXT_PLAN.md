# Next plan

What to do after the web backend (`WEB_BACKEND_PLAN.md`, complete on `web-backend`).
Gathered from the follow-ups that work surfaced and the open items of `REVIEW.md`. Ordered
so each step makes the next ones safer; build and test each before moving on, and cross
out a step's line when it's done.

## 0 — Land the web backend

1. ~~Open a pull request for `web-backend` into `main` (20 commits, M0–M10 plus three core
   fixes: New resets the view, saved files hold every field, `file_view` is excluded
   from state). The PR description can mostly be `WEB_BACKEND_PLAN.md`'s summary.~~ *(Opened: [#1](https://github.com/ehmoussi/composeui3/pull/1).)*

## 1 — Trust: catch regressions automatically

There is no CI: every check depends on someone running `make check test` locally.

1. ~~**GitHub Actions workflow** running `make check` and `make test` on every push and PR:
   `uv sync --group dev --all-extras`, `QT_QPA_PLATFORM=offscreen`, the Ubuntu packages
   offscreen Qt needs (e.g. `libegl1`, `libxkbcommon0`, `libgl1`), uv cache keyed on
   `uv.lock`. Python 3.9 (the floor, `.python-version`) plus the newest supported
   version. The stylesheet-staleness test then also fails a PR that adds a CSS class
   without `make css`.~~ *(`.github/workflows/ci.yml`; runs `ruff format --check` and `ruff check` instead of `make lint`, which rewrites files.)*
2. ~~**Include the web backend in the registry consistency test.**
   `test_every_backend_registers_the_same_renderer_keys` compares Qt with Textual only;
   all three register the same 14 keys today, so a widget added to one backend and
   forgotten in another should fail it.~~
3. ~~**Fix `Signal._log_signal` crashing on callbacks without `__code__`.** Connecting a
   built-in (e.g. `list.append`) or any callable object raises `AttributeError` as soon
   as the signal emits, from `get_function_file`. Found in M2 and worked around in the
   web tests. Fall back to `repr`/`type` when there's no code object; add a core test
   connecting a built-in and a callable instance.~~

## 2 — Core: make what the web backend learned available to every backend

1. ~~**Atomic `load_state` in core.** A state file failing halfway (e.g. a valid name, then
   an age of `"abc"`) leaves the live view half loaded on Qt and Textual. The web backend
   already avoids this by applying uploads to a scratch instance first. Move that into
   core (`load_state` validates on `type(self)()` before applying, raising one clear
   error type), so Qt/Textual's Open gets it too and can show the error.~~
2. ~~**Public "load from data" API.** The web session imports core's private
   `_apply_state` to load an uploaded dict. Add `MainView.load_state_data(data)` (sharing
   step 1's validation) and use it from `webcore/session.py`.~~
3. ~~**Checkable actions write `is_checked` back.** Qt's `QAction` toggles its own check
   mark without updating the view, and the web and Textual don't toggle at all, so
   `is_checked` never reflects a click on any backend. Toggle in core when a checkable
   action triggers (or connect Qt's `toggled`), then render it on all three; one core
   test plus a web test for the ✓.~~

## 3 — Examples and packaging

1. ~~**Keep `examples` out of the wheel.** `uv build` ships a top-level `examples` package
   (and `examples/py.typed`) to anyone installing ComposeUI. Exclude it in
   `[tool.setuptools.packages.find]`, or rename it `composeui_examples` if it should
   stay installable. Check that the static files keep shipping (they do today, through
   setuptools-scm).~~ *(`include = ["composeui*"]`; the sdist still carries `src/examples` for the tests, and the editable install keeps it importable.)*
2. ~~**Split `pipeform.py`'s views from its apps.** The module imports the Qt, Textual and
   web apps at the top, so the web tests skip entirely without Qt and Textual installed.
   Move the views to `examples/pipeform/views.py`, with one small app module per backend
   (`main()` choosing by a `--backend` flag), so each backend's tests only need its own
   extra.~~ *(Kept in one file instead: `main()` imports the chosen backend's `Application` only once `--backend qt|textual|web` picks it.)*
3. ~~Fix pipeform's "cant'be" typo in the cross-field message (and the test asserting it).~~ *(No test asserted the typo; they match "incident radius" only.)*

## 4 — Web backend follow-ups

1. ~~**Make `app.connect` work per session.** Today it only wires the template
   `app.main_view`, which no browser displays: the web backend's biggest surprise.
   Record each `connect(view=..., signals=...)` made against the template, resolve the
   view by its attribute path from the main view, and replay it on every session's main
   view (in `_new_session_view`, before `setup_session`). Test with a callback connected
   through `app.connect` reacting in two browsers.~~ *(Also fixed in core: `app.connect` crashed on any backend when the callback asked for `main_view`, because `Signal` held every injected callback as a `WeakMethod`.)*
2. ~~**Web `ModelApplication`.** Decide per-session versus shared models: a
   `build_model` factory per session matches how main views work, while one shared
   `Model` would need its own locking. Implement the chosen one with
   `_add_reference_to_signals(main_view, model)`.~~ *(Per session: `WebModelApplication(build_main_view=..., build_model=...)`. A shared model would also leave other browsers stale, since a browser only gets fragments from its own requests.)*
3. ~~**Opt-in browser test suite.** Caret preservation, Alt+Shift shortcuts, the
   `aria-invalid` sync, the offline page and the status bar's auto-clear were all checked
   by hand in headless Chromium, repeatedly. Add Playwright tests marked and skipped
   when Playwright or a browser isn't installed (`pytest.importorskip`), with a
   `make browser-test` target, and run them in CI (step 1.1) with `playwright install
   chromium`.~~ *(`tests/test_browser.py`, marker `browser`, Playwright in a `browser` dependency group; `make test` excludes them; CI runs them in a separate `browser` job on Python 3.13.)*
4. ~~**Development reload.** `--reload` was removed because uvicorn's reloader needs an
   import string. Support it via a module-level app factory (e.g.
   `WebApplication.run()` accepting `"package.module:AppClass"`), or document
   `uvicorn --reload --factory` against such a factory.~~ *(`--reload` is back: `run()` serves `create_reloaded_starlette_app`, which runs the program named in `COMPOSEUI_WEB_ENTRY` (the script or `-m` module) again as the new process's `__main__`, with the inherited command line, and keeps the app whose `run()` it reaches instead of serving it. So apps built inline, like pipeform's, and `app.connect` calls in `main()` reload too.)*
5. ~~**`make css` beyond Linux x64.** The Makefile downloads `tailwindcss-linux-x64` only.
   Pick the binary from `uname -s`/`uname -m` (macOS arm64/x64, Linux arm64) so
   contributors on other machines can rebuild the stylesheet.~~ *(`TAILWIND_PLATFORM`, from `uname`, overridable, e.g. `linux-x64-musl` on Alpine; anything else stops with the list. Windows through Git Bash, MSYS2 or Cygwin (`windows-x64`, untested there); WSL is Linux; native cmd/PowerShell can't run the Makefile at all.)*
6. ~~**Open's file picker filters by extension.** Actions don't know their main view's
   extension; pass it down (e.g. the main renderer adds `accept` when it renders the
   menus) so the picker only offers matching files. Small; the server already checks.~~ *(`WebMainRenderer.render` sets `accept` on every Open action's renderer, which keeps it for later re-renders of the action alone.)*
7. **Optional: keep sessions across restarts.** Persist each session's `save_state` JSON
   (a directory, or Redis later) and reload it when a cookie for an unknown session
   arrives; needs a fixed signing key from the environment. Only worth it for a deployed
   app, which also raises multi-process serving (out of scope until then).

## 5 — Widgets (REVIEW.md item 4)

One widget at a time, each on all three backends with tests (the consistency test from
1.2 enforces this): ~~`CheckBoxView` first (the most common missing form field)~~ *(with
`RowCheckBoxView`/`LabelRowCheckBoxView`; pipeform's "Insulated pipe" enables its
thickness)*, then ~~a read-only `TableView`~~ *(text cells the app formats; pipeform's
summary under the form)*, tabs, simple dialogs (message/confirm), and a progress bar. The
web versions follow the same rules: the focus rule, OOB updates, `aria-*` links, and a
`make css` rebuild when new classes appear.

## 6 — Adoption (REVIEW.md items 2, 6–8)

1. API reference docs (mkdocs + mkdocstrings; the code is fully typed).
2. A packaging story for apps built on ComposeUI (PyInstaller/briefcase for Qt; a plain
   `uvicorn` deployment note for web).
3. `CHANGELOG.md`, semantic versions, and a PyPI release once sections 1–3 are done.
