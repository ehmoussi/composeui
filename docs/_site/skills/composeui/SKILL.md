---
name: composeui
description: "Use when writing or changing an app built with ComposeUI, the Python MVVM layer whose views are typed attrs classes that a Qt, Textual or web renderer shows: when the code imports composeui, defines a MainView, a FormView or another view with @define_view, connects a Signal, or starts an app with run(). Holds the rules that keep such an app correct on every backend, a minimal app, and where the documentation is."
---

# ComposeUI

ComposeUI is a small MVVM layer. The app is a tree of views under a `MainView`. A view is a
typed `attrs` class that holds the state of a part of the UI. A renderer of the chosen
backend (Qt, Textual, or the web) binds each view to a widget. Signals carry events between
the views, the model, and the app. The API is early-stage and still moving: when the
documentation and this skill disagree, trust the documentation.

Full documentation: https://ehmoussi.github.io/composeui/ (an index for models is at
https://ehmoussi.github.io/composeui/llms.txt).

## A minimal app

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

    def _on_name_changed(self, text: str, *, main_view: MainView) -> None:
        main_view.status_bar.show_message(f"Hello, {text}!" if text else "")


@define_view
class HelloMainView(MainView):
    app_title = "Hello ComposeUI"
    extension = ".hello"

    greeting: GreetingInputView = Factory(GreetingInputView)


if __name__ == "__main__":
    run(HelloMainView)
```

Run it with `--backend qt` (extra `pyside6`), `--backend textual` (extra `tui`), or without
the option for the web (extra `web`, the default).

## Rules

- **Import views, signals and `run` from `composeui.core`.** Never import `PySide6`,
  Textual, or Starlette in the app's views: the same views must run on every backend.
  Use `qtpy` if the app needs Qt itself.
- **Decorate every view class with `@define_view`,** and give it typed fields. Fields are
  keyword-only. A class variable such as `app_title`, `extension`, or `align` configures
  the class and is not state.
- **A child view is a field that builds it:** `Factory(MyView)`, or
  `child(MyView, label="Name")` to set fields. Never share one instance between views.
- **Wire a view in `__attrs_post_init__`.** Call `super().__attrs_post_init__()` first,
  then set values and connect signals.
- **Views are reactive.** Set an attribute (`view.text = "..."`) and the renderer shows it.
  Never call `update()` or `refresh()`, and never touch a widget: the app's code does not
  see the toolkit.
- **A signal callback asks for `view`, `main_view`, or `model` by parameter name,** and
  `connect` injects them. Spell the names exactly. A callback may take fewer of the
  signal's arguments than it emits.
- **Check a form with a validator:** `self.set_validator(self._check, self.text_edited)`
  where `_check` returns an error message or `None`. Then read `form.check()` and
  `form.is_valid`.
- **Keep the state saveable.** `MainView.save_state` writes the views' fields with
  `cattrs`. The shared `CONVERTER` handles `datetime.date` and `datetime.datetime` as ISO 8601
  strings without custom hooks. A new field must be serializable, or the app must leave it out of
  the state as `Signal` and validator fields are.
- **Run slow work in jobs** (`main_view.jobs`), not in a callback: a callback blocks the UI.
  Results and failures are emitted on the main thread. Handle `job.failed` there to show
  errors and clear loading indicators. `RefusedError` logs a warning without a traceback;
  unexpected failures keep their tracebacks.
  For typed progress, annotate the worker's job as `Job[ResultT, ProgressT]`;
  `Job[ResultT]` defaults to no progress (`None`). Call `job.report_progress(value)` in the
  worker and connect `job.progress`
  on the main thread. Reports arrive in order before the outcome, with `main_view`/`model`
  injection. Dropping a job discards queued progress too.
- **Reuse loading state with `jobs.task(work)`.** Create a task once as an instance attribute
  in `__attrs_post_init__`, not a saved view field. Connect `task.changed` to one main-thread
  handler that reads `is_running`, `progress`, `result`, and `error`; `has_result` also handles
  successful `None` results. Call `task.start(*args, **kwargs)` on the main thread. It clears
  prior state, or returns `False` unchanged if already running. `task.cancel()` asks only its
  current run to stop. Dropping the study's jobs resets all tasks and discards old outcomes.
  The worker's annotations type the task's result, progress, and start arguments.
- **Mark user-visible text for translation** with `T("...")` or `self.tr("...")`
  (`T` is in `composeui.core.view`).
- **Keep the model out of the views.** The optional model (`Model`, `SqliteModel`) holds
  the data and knows no view. The app gives it to `run` with `build_model=`.
- **Finish batch inserts.** `SqliteTable.insert_batches(sql, rows, batch_size=100_000,
  limit=None)` yields cumulative submitted-row counts in one transaction. Exhaust it to
  commit; use `contextlib.closing` to roll back if iteration stops early. Inside an outer
  `connection()` block, the caller owns the transaction and must raise to roll it back.
  With `db=db`, the helper uses that connection without committing, rolling back or closing
  it. Use the table's `connection()` for change notifications.
- **Import CSV through an attrs schema.** Declare
  `class Readings(CSVSqliteTable, row_type=Reading, name="reading")` and use
  `csv_field("Header", date_format="...", validator=...)` on the row class as needed.
  Import these names from `composeui.core.sqlitemodel`. `fill(text, batch_size=100_000,
  limit=None)` follows the batch-insert transaction rules. Conversion and attrs validation
  errors become `RefusedError`. `date_format` requires a date or datetime field and cannot
  accompany a custom converter. The caller owns the text stream. Rebuild table sources from
  the table's `changed` signal after Open or reload; do not import restored rows again.
  `table.source()` builds a `SqliteSource` with inferred field types and CSV headers.
  Use `source(headers={"field": "Label", ...})` to select, order, and label columns.
  It uses hidden SQLite row IDs; use `SqliteSource` directly for custom queries or explicit keys.
- **Read CSV files and URLs without stream wrappers.**
  `CSVSqliteTable.fill_from_file(path, ...)` accepts a path string or `pathlib.Path`,
  opens plain or gzip CSV, and closes the file. Relative paths use the working directory.
  `CSVSqliteTable.fill_from_url(url, ...)`
  imports trusted HTTP, HTTPS, or file URLs, detects gzip by content, and yields row counts.
  It appends rows and follows `fill`'s transaction rules; use `contextlib.closing` if iteration
  can stop early. `open_csv_url(url, encoding="utf-8", timeout=30.0)` is a context manager for
  CSV text without importing it. Import it from `composeui.core.sqlitemodel`. Both APIs close
  their streams and propagate I/O errors. The timeout is per socket operation, not a total
  deadline. They do not restrict hosts, redirects, or local files: never pass untrusted URLs.
  File and URL imports accept `sniff=True` to infer a dialect from at most `sniff_sample_size`
  decoded characters (8192 by default) and replay the sample without seeking. Increase the
  sample size for wide headers or long rows; it must be positive when sniffing and is ignored
  otherwise. Explicit CSV options override detection.
  Sniffing is off by default, never infers headers, and raises `RefusedError` on detection
  failure. For known formats, keep explicit options instead of relying on guesses.
- **Support Python 3.9 in view fields.** Write `Optional[int]` and `Union[int, str]`, not
  `int | None`, because `attrs` and `cattrs` evaluate the annotations at runtime. Start
  every module with `from __future__ import annotations`, and do not quote annotations.
  Define the views at module level.
- **Run a code example before you answer with it.** The API moves: check each name against
  `composeui.core.view` or the widget catalog before you use it.

## Where to look

- Which view to use: the widget catalog, https://ehmoussi.github.io/composeui/widgets.html
- Core concepts, views, layout, forms: the user guide,
  https://ehmoussi.github.io/composeui/user-guide.html
- Complete apps to copy from: the examples guide,
  https://ehmoussi.github.io/composeui/examples-guide.html
- Exact signatures: the API reference, https://ehmoussi.github.io/composeui/api/index.html
