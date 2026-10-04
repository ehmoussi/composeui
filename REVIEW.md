# ComposeUI — Library Review & Roadmap

*Reviewed at commit `9a50bcd` (2026-07-13). Scope: `src/composeui/`, `src/examples/`, `tests/`.*

## What it is

A small, framework-agnostic MVVM layer for building desktop UIs. Views are declared as
`attrs` classes (`@define_view`) with plain typed fields; a `Renderer`/`RendererContainer`
binds each view to a concrete toolkit widget. Two backends exist today — Qt (`qtpy`) and
Textual — selected via `RendererType` and resolved through a registry
(`composeui.core.registry`) so `composeui.core` has no import-time dependency on either.
`Signal` objects carry events between view, model and application code with automatic
keyword injection (`view`/`main_view`/`model`) based on the connected callback's signature.

## Known gaps

- **No CI.** No `.github/workflows` or equivalent — `ruff`/`mypy`/`pytest` are enforced only
  if a contributor remembers to run `make check test` locally.
- **Narrow widget catalog.** Only input/float-input/label/radio-group/log/form-row/menu/
  action/status-bar/file-dialog exist. No combo box, checkbox, table/tree view, tabs, custom
  dialogs, or progress bar.
- **No packaging/distribution guidance** (PyInstaller/briefcase/etc.) for shipping apps built
  on top of this, and no published package.
- **No widget catalog or architecture doc**, beyond the README quickstart.

## Next up

### Trustworthiness
1. Add CI (GitHub Actions): run `make check test` (ruff + mypy + pytest) on every PR/push;
   fail the build on lint/type/test regressions.
2. Add a `CHANGELOG.md` (or rely on `setuptools-scm` + release notes) once versioned releases
   start.

### Correctness
3. ~~Add `pytest-qt` and cover `qtrenderer.py`~~ *(done)*: `pytest-qt` was already a dev
   dependency but unused; `tests/test_qtrenderer.py` now renders real widget trees (mostly
   via `examples/pipeform.py`, matching `tests/test_textual_renderer.py`'s style for the
   other backend) and, per renderer, asserts on the actual widget state and drives a real
   interaction back into the view: typed keystrokes into a `QLineEdit` (plus the reverse,
   `update_state`), a `QDoubleValidator` rejecting bad input, a genuine `QRadioButton.click()`
   round-tripping `value` and cascading into a status-bar message and a sibling group's
   visibility, a `QGroupBox` title, a `QMainWindow`'s title/minimum size/status bar, a real
   `QMenu` with shortcuts and a separator, and `Ctrl+O`/`Ctrl+S`-equivalent `QAction.trigger()`
   flows against a monkeypatched `QFileDialog` (covering `MainRenderer.open_file`/`save_file`,
   including the save path's auto-appended extension). `qtrenderer.py` coverage went from
   43% to 86%.

   Two bugs surfaced along the way. First, a real one in `composeui.core.view`:
   `MainView.file_menu` defaulted to a bare `FileMenu(title="File")` instead of
   `attrs.Factory(FileMenu)` (unlike every sibling field), so every `MainView` instance
   silently shared one `FileMenu` - including its renderer, once any instance rendered.
   Harmless by accident for Qt/Textual today (nothing yet constructs two live `MainView`s
   against different backends in the same process outside tests), but exactly the kind of
   cross-instance state leak that would corrupt a real multi-window or multi-backend app.
   Fixed (`file_menu: FileMenu = attrs.Factory(FileMenu)`); `FileMenu.__attrs_post_init__`
   already sets `title = "File"` unconditionally, so the constructor arg was redundant.

   Second, a test-hygiene footgun rather than a library bug: triggering a status-bar message
   with the default 3s `timeout` while a Qt window is rendered leaves a real background
   `threading.Timer` running past the end of the test, which then fires against that test's
   already-destroyed `QStatusBar` - non-deterministically corrupting whichever *other* test
   (Qt or Textual) happens to be running when the 3 seconds elapse. Every test that renders
   and triggers a status message now sets `timeout = 0` first.

### Widget catalog
4. Add the widgets most real forms need next: `CheckBoxView`, `ComboBoxView`, `TableView`/
   `TreeView`, `TabView`, generic `DialogView` (not just open/save file dialogs),
   `ProgressBarView`. New widgets register into the existing `RENDERERS` mapping per backend
   (`composeui.core.registry`) — no per-view backend branching needed.
5. ~~Add a small reusable validation abstraction~~ *(done)*: two tiers, one per log
   widget that already existed. `LogMixin.set_validator(validator, *signals)` wires a
   zero-argument `Validator = Callable[[], Optional[str]]` (reads whatever state it
   needs itself, e.g. `self.text`) to run whenever any of `signals` fires, pushing a
   failing result into that row's *own* `log_message`/`log_type` -
   `PipeNameRowView`/`textual_demo.NameRowView` now use it instead of hand-rolling
   `_check_name`. `FormView.add_validator(validator, *signals)` is the form-level
   counterpart: a form can register several independent cross-field checks that all
   feed the *same* shared `log_view`, combining every failing message into the
   existing `"- " + "\n- ".join(...)` bullet format instead of one callback
   overwriting another's - `PipeFormView._display_error_message`'s two checks
   (main-pipe-fits-incident, incident-radius-vs-main-radius) are now two separate
   validators. Neither `set_validator` nor `add_validator` runs its validator
   immediately on registration (matching the pre-existing asymmetry: `PipeNameRowView`
   always validated its initial empty state, `PipeFormView` never validated eagerly at
   construction) - callers that want an initial check call `run_validator()`/
   `validate()` themselves right after registering.

   `run_validator`/`validate` both accept and ignore `*_args: Any` so the same hook
   connects directly to a signal of any arity - a per-keystroke `text_edited:
   Signal[str]` or a no-argument `editing_finished: SignalNoArgs` alike (typed as
   `Signal[Unpack[tuple[Any, ...]]]` in the `*signals` parameter itself, since a
   `TypeVarTuple`-generic `Signal[Any]` doesn't structurally accept `Signal[()]`).

   The `validator`/`_validators` fields needed excluding from `save_state`/
   `load_state` the same way `Signal`/`Renderer` fields already are, but neither a
   bare `Optional[Validator]` nor a `list[Validator]` is a single class
   `_is_omitted_type`'s type-based matching can catch generically. Rather than
   special-casing `Callable` there, added an orthogonal `metadata={_TRANSIENT: True}`
   tag and a combined `_is_transient_field` check, reusable by any future field that's
   runtime-only wiring but not cleanly expressible as "is an instance of type X".

   Covered by `tests/test_validation.py`.

### External adoption
6. Document a packaging story (PyInstaller/briefcase) for apps built on ComposeUI.
7. Add API reference docs (mkdocs + mkdocstrings, given the codebase is already fully typed).
8. Publish to PyPI with semantic versioning once the above are in reasonable shape.
