# Testing your app

The views hold the whole state of the UI, so most tests need no backend. A test builds the
app, acts as the user does on the views, and checks their fields. The tests run with
[pytest](https://docs.pytest.org/), and without a window, a terminal, or a browser.

## Test the views

Build the app with `Application` from `composeui.core.application`, the application of
`composeui.core`. Then do what the user does, and check the fields:

```python
from attrs import Factory

from composeui.core.application import Application
from composeui.core.view import InputView, MainView, define_view


@define_view
class GreetingInputView(InputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.text_edited.connect(self._on_name_changed)

    def _on_name_changed(self, text: str, *, main_view: MainView) -> None:
        main_view.status_bar.show_message(f"Hello, {text}!" if text else "")


@define_view
class HelloMainView(MainView):
    app_title = "Hello ComposeUI"
    extension = ".hello"

    greeting: GreetingInputView = Factory(GreetingInputView)


def test_the_status_bar_greets_the_name_typed() -> None:
    app = Application(build_main_view=HelloMainView)
    app.main_view.status_bar.timeout = 0  # the message stays until the next one

    app.main_view.greeting.text = "Ada"  # as the user types, a renderer sets the text,
    app.main_view.greeting.text_edited.emit("Ada")  # then emits the signal

    assert app.main_view.status_bar.message == "Hello, Ada!"
```

- **Build the app, not only the main view.** The app gives each callback the `main_view` and
  the `model` that it asks for. Without the app, a callback that asks for `main_view` raises
  `ValueError`.
- **Act as the user.** When the user edits a field, the renderer sets the view's field,
  then emits its signal. So set the field, then emit the signal, for example `text` then
  `text_edited`. For a button, emit `clicked`. For a menu or toolbar action, emit
  `triggered`.
- **Check the fields.** For example `status_bar.message`, the `text` of a label, the `rows`
  of a table, or `is_enabled`.
- **Keep the messages.** The status bar clears a message after its `timeout`, in a timer of
  its own. With a `timeout` of 0, the message stays, so a slow test still sees it.

## Test a form

A form runs its checks without an app. `check()` runs them all, as a Save button does
before it acts. `is_valid` then tells whether they pass, and each row's `log_message` holds
its error:

```python
from typing import Optional

from composeui.core.view import FormView, LabelRowInputView, child, define_view


@define_view
class NameRow(LabelRowInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.set_validator(self._check_name, self.text_edited)

    def _check_name(self) -> Optional[str]:
        return "A name is required" if self.text == "" else None


@define_view
class PipeForm(FormView):
    name: NameRow = child(NameRow, label="Name")


def test_a_pipe_needs_a_name() -> None:
    form = PipeForm()

    form.check()

    assert not form.is_valid
    assert form.name.log_message == "A name is required"


def test_a_named_pipe_is_valid() -> None:
    form = PipeForm()
    form.name.text = "Main pipe"

    form.check()

    assert form.is_valid
```

See [Check a form](building-views.md#check-a-form).

## Test the jobs

No event loop runs in a test, so the results of the [jobs](threads.md) wait.
`main_view.jobs.wait()` waits for the jobs, then emits their signals on the test's thread:

```python
from attrs import Factory

from composeui.core.application import Application
from composeui.core.jobs import Job
from composeui.core.view import ButtonView, LabelView, MainView, child, define_view


def count_rows(job: Job[int], count: int) -> int:  # in its thread
    return count


@define_view
class CountMainView(MainView):
    count: ButtonView = child(ButtonView, text="Count")
    result: LabelView = Factory(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.count.clicked.connect(self._count)

    def _count(self) -> None:
        job = self.jobs.start(count_rows, 3)
        job.finished.connect(self._show)

    def _show(self, rows: int) -> None:
        self.result.text = f"{rows} rows"


def test_count_shows_the_rows_once_its_job_is_over() -> None:
    app = Application(build_main_view=CountMainView)

    app.main_view.count.clicked.emit()
    app.main_view.jobs.wait()  # the job's signals then emit, on the test's thread

    assert app.main_view.result.text == "3 rows"
```

- **Make the work fast.** Replace a slow computation or a long wait with
  `monkeypatch.setattr`, for example a constant that sets the duration of a step.
- **A task too.** `jobs.wait()` also gives a [loading task](threads.md#reusable-loading-tasks)
  its outcome, so its `finished` or `failed` callbacks run.

## Test with a model

Build the app with `ModelApplication`, with the same arguments as `run`. A fixture builds
the app for each test, and closes the model after it:

```python
from collections.abc import Iterator
from pathlib import Path

import attrs
import pytest
from attrs import Factory

from composeui.core.application import ModelApplication
from composeui.core.sqlitemodel import SqliteModel, SqliteTable, table
from composeui.core.study import open_study, save_study
from composeui.core.view import ButtonView, MainView, TableView, child, define_view


@attrs.define
class Run:
    id: int
    radius: float


class Runs(SqliteTable):
    create = "CREATE TABLE run(id INTEGER PRIMARY KEY, radius REAL NOT NULL);"

    def add(self, radius: float) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO run(radius) VALUES (?)", (radius,))

    def all(self) -> list[Run]:
        return self.fetch(Run, "SELECT * FROM run ORDER BY id")


class PipeModel(SqliteModel):
    runs = table(Runs)


@define_view
class PipeMainView(MainView):
    extension = ".pipe"

    add: ButtonView = child(ButtonView, text="Add")
    runs: TableView = child(TableView, headers=["Radius"])

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.add.clicked.connect(self._add)

    def _add(self, *, model: PipeModel) -> None:
        model.runs.add(0.5)

    def connect_model(self, model: PipeModel) -> None:
        model.runs.changed.connect(self._show_runs, now=True)

    def _show_runs(self, *, model: PipeModel) -> None:
        self.runs.rows = [[f"{run.radius:g}"] for run in model.runs.all()]


App = ModelApplication[PipeMainView, PipeModel]


def _app() -> App:
    return App(
        build_main_view=PipeMainView,
        build_model=PipeModel,
        setup_model=PipeMainView.connect_model,
    )


@pytest.fixture
def app() -> Iterator[App]:
    app = _app()
    yield app
    app.model.close()  # deletes the model's scratch copy of the database


def test_add_shows_the_new_run(app: App) -> None:
    app.main_view.add.clicked.emit()

    assert app.main_view.runs.rows == [["0.5"]]


def test_a_study_keeps_the_runs(app: App, tmp_path: Path) -> None:
    app.main_view.add.clicked.emit()
    save_study(app.main_view, app.model, tmp_path / "runs.pipe")

    other = _app()
    try:
        open_study(other.main_view, other.model, tmp_path / "runs.pipe")
        assert other.main_view.runs.rows == [["0.5"]]
    finally:
        other.model.close()
```

- **Close the model.** `model.close()` deletes the scratch copy of its database. Close it in
  the fixture, after the `yield`, so a failed test closes it too.
- **Save and open a study.** `save_study` and `open_study` from `composeui.core.study` save
  and open the views and the model's data together, as the File menu does. For an app
  without a model, `main_view.save_state(path)` and `main_view.load_state(path)` do the
  same.
- **One model per test.** Each test builds its own app. So the tests also run in parallel,
  for example with pytest-xdist.

## Test on a backend

Test on a backend only what the backend does: the widget that it shows, a key that the
user presses, a page that the server sends. The tests of ComposeUI do this, and show how:

- **Qt:** [pytest-qt](https://pytest-qt.readthedocs.io/)'s `qtbot`, in
  [`tests/test_qtrenderer.py`](../../tests/test_qtrenderer.py). Set
  `QT_QPA_PLATFORM=offscreen` to run them without a display.
- **Textual:** `App.run_test()` and its pilot, in
  [`tests/test_textual_renderer.py`](../../tests/test_textual_renderer.py).
- **The web:** Starlette's `TestClient`, in
  [`tests/test_webrenderer.py`](../../tests/test_webrenderer.py).

The tests of the example apps, such as
[`tests/test_pipesweep.py`](../../tests/test_pipesweep.py), test the views as this page does.
