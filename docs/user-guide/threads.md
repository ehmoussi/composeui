# Running work in threads

A slow operation can freeze the app if it runs on the main thread. Use a `Job` or a `Task`
to run the function in a worker thread instead.

## Job or task: which should you use?

A `Job` represents one run. A `Task` is an object you keep: it starts new jobs for the same
function and tracks their progress and results. To choose, ask what should happen if the user
triggers the action again while a run is in progress.

| What should happen? | Use | Example |
| --- | --- | --- |
| Start another independent run. | `jobs.start(...)` | [Export two different files](#independent-exports-with-jobs). |
| Refuse the new run. It is not queued. | `task.start(...)` | [Ignore a second click on **Import**](#reusable-loading-tasks). |
| Replace the previous request. Ignore its progress and outcome. | `task.start_latest(...)` | [Update search results as the user types](#run-the-latest-call-only). |

## Independent exports with jobs

Use `jobs.start(...)` when both exports matter. The second export can start before the
first one finishes. Connect `finished` to each job so both completions appear in the
log. Update the view in the callback, not in the export function.

```python
import csv

from composeui.core.jobs import Job
from composeui.core.view import ConsoleView, MainView, child, define_view


def export_rows(job: Job[str], path: str, rows: tuple[tuple[str, ...], ...]) -> str:
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        for row in rows:
            job.raise_if_canceled()
            writer.writerow(row)
    return path


@define_view
class ExportView(MainView):
    log: ConsoleView = child(ConsoleView)

    def export(self, path: str, rows: tuple[tuple[str, ...], ...]) -> None:
        job = self.jobs.start(export_rows, path, rows)
        job.finished.connect(self.show_export)

    def show_export(self, path: str) -> None:
        self.log.append(f"Exported {path}\n")


main_view = ExportView()
main_view.export("stock.csv", (("Pipe", "12"),))
main_view.export("orders.csv", (("Valve", "3"),))
main_view.jobs.wait()  # Only for a main view with no toolkit.
```

Use a different destination for each export. The jobs can finish in either order.

- **Errors.** Connect `failed` to show an error. See [How jobs behave](#how-jobs-behave)
  for which exceptions it emits.
- **Callbacks** connected to the signals of a job get the `main_view` and `model` that they
  ask for, as for any signal.
- **Running or not.** `jobs.is_running` tells whether any job runs. `jobs.running_changed`
  emits it when it changes, for example to disable a Run button.
- **From another view.** A view that is not the main view runs its work with
  `self.build_task(work)` (see [A task of another view](#a-task-of-another-view)).

[`src/examples/taskview.py`](../../src/examples/taskview.py) runs 25 jobs at once, and cancels
them.

## Progress and canceling

- **Progress.** In the function, `job.report_progress(value)` reports a value of your
  choice, such as a count, a percentage, or a message. `job.progress` emits each value
  in the order of the reports, before `finished` or `failed`. Connect it as `finished`
  and `failed` are. Its callbacks can ask for `main_view` and `model` too.
  - Annotate the function's job as `Job[ResultT, ProgressT]`: the second type is the type
    of the values, and of the callbacks' argument. `Job[ResultT]` is a job without
    progress: its `ProgressT` is `None`.
  - A dropped job emits none of the values that still wait.
  - On Qt and Textual, the values reported while the main thread is busy come to it
    together. `job.progress` emits each one, and the reactive methods that they change run
    once after them, not once per value. So a job can report often, such as after each file
    that it copies.
  - `job.call_on_main_thread(callback)` runs a callback in order with progress reports,
    before the job's outcome. It uses the same [thread as the job's signals](#how-jobs-behave).
    A dropped job does not run pending callbacks.
- **Canceling.** `job.cancel()`, or `jobs.cancel()` for all the jobs, asks the functions to
  stop. Python cannot stop a thread, so each function checks `job.is_canceled`, or waits with
  `job.sleep(seconds)`, which returns False once the job is canceled. The function still
  finishes, and `finished` emits what it returned.
  - `job.raise_if_canceled()` raises `JobCanceledError` once the job is canceled. Call it
    where the function can stop without a result, also in the helpers it calls. The job then
    fails with `JobCanceledError`, which is logged as information only.

To report rows processed, connect a callback right after starting the job:

```python
from composeui.core.jobs import Job
from composeui.core.view import MainView


def process(job: Job[int, int], count: int) -> int:
    for completed in range(1, count + 1):
        if job.is_canceled:
            return completed - 1
        # Process one row here.
        job.report_progress(completed)
    return count


def show_progress(completed: int, *, main_view: MainView) -> None:
    main_view.status_bar.show_message(f"Processed {completed} rows")


main_view = MainView()
job = main_view.jobs.start(process, 3)
job.progress.connect(show_progress)
main_view.jobs.wait()  # Only for a main view with no toolkit; apps use their event loop.
```

## Run an external program

In the function of a job, `job.run_process(command)` runs a program, such as a solver, and
waits for it to exit. It returns the exit code of the program. Canceling the job stops the
program. To show the output of the program, pass `on_output=job.report_progress`, and append
each value to a [`ConsoleView`](widgets.md#console):

```python
import sys

from composeui.core.jobs import Job
from composeui.core.view import ConsoleView, MainView, child, define_view

SOLVER = "print('Step 1'); print('Done')"


def run_solver(job: Job[int, str], command: list[str]) -> int:  # in its thread
    return job.run_process(command, on_output=job.report_progress)


@define_view
class SolverView(MainView):
    output: ConsoleView = child(ConsoleView)

    def run(self) -> None:
        job = self.jobs.start(run_solver, [sys.executable, "-c", SOLVER])
        job.progress.connect(self.output.append)


main_view = SolverView()
main_view.run()
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert main_view.output.text == "Step 1\nDone\n"
```

- **Output.** `on_output` gets the output and the errors of the program as text, in the
  thread of the job, in the order that the program sends them. Without `on_output`, the output
  is read and dropped.
- **Buffering.** Many programs keep their output in a buffer when it goes to a pipe, not to a
  terminal, and send it in blocks of a few kilobytes. The console then shows it late, and after
  the errors. For a Python program, pass `env={**os.environ, "PYTHONUNBUFFERED": "1"}`: `env`
  replaces the whole environment. For many C programs on Linux, put `stdbuf -oL` before the
  command, so that each line is sent.
- **Errors apart.** With `on_errors`, `on_output` gets the output only, and `on_errors` the
  errors, also in the thread of the job. Use it for a program that writes data, such as CSV,
  on its output and warnings on its errors. The order between the output and the errors is
  then lost: the text of each comes as it's read.
- **Encoding.** The text is decoded from `encoding`, UTF-8 by default. A character whose bytes
  come in two reads arrives whole. A byte that the encoding can't decode shows as "�". On
  Windows, many programs write in the code page of the system: pass
  `encoding=locale.getpreferredencoding(False)`, or `"oem"` for a console tool. An unknown
  encoding raises `LookupError` before the program starts.
- **Options.** `cwd` and `env` set the folder and the environment of the program, as for
  `subprocess.Popen`. The program reads no input.
- **Stopping.** `run_process` stops the program in these cases:
  - When the job is canceled, it raises `JobCanceledError`.
  - After `timeout` seconds, it raises `subprocess.TimeoutExpired`.
  - When `on_output` or `on_errors` raises, the error goes on.

  The text that the program writes as it stops still reaches `on_output` and `on_errors`,
  unless one of them raised.
- **The programs that it starts.** On Linux and macOS, the program runs in a session of its
  own, with the programs that it starts, such as the processes of an MPI run. When it exits or
  is stopped, the programs left in the session get SIGTERM, then SIGKILL after `grace` seconds
  (5 by default). So a program that saves its work on SIGTERM has `grace` seconds to save.
- **When the app exits** while the program runs, Python stops the program as the job would.
  The web server also stops the programs as it stops, after Ctrl+C or SIGTERM. A signal that
  ends a Qt or Textual app before Python exits leaves the program running: SIGTERM, SIGKILL,
  or Ctrl+C on Qt.
- **On the web,** the input of a user can reach the command. `run_process` uses no shell, so
  each item of the list stays one argument. A program can still read an argument that starts
  with `-` as an option: check the input first. Each session can start a program. To limit
  how many run at once, see
  [A limit on the jobs that run at once](#a-limit-on-the-jobs-that-run-at-once).
- **On Windows,** only the program that `run_process` started is stopped. The programs that
  it started go on, and `run_process` waits at most 2 seconds for the output that they still
  write.

## Reusable loading tasks

Keep one task for the **Import** button so a second click cannot start another import while
the first is in progress. Create the task and connect its signals once. On each request,
call `import_file(path)`. The `changed` callback shows progress, and `finished` or `failed`
shows the outcome.

```python
import csv

from composeui.core.jobs import Job
from composeui.core.view import LabelView, MainView, child, define_view


def read_rows(job: Job[list[list[str]], int], path: str) -> list[list[str]]:
    rows = []
    with open(path, encoding="utf-8", newline="") as file:
        for row in csv.reader(file):
            job.raise_if_canceled()
            rows.append(row)
            job.report_progress(len(rows))
    return rows


@define_view
class ImportView(MainView):
    status: LabelView = child(LabelView, text="Ready")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loader = self.jobs.task(read_rows)
        self.loader.changed.connect(self.show_progress)
        self.loader.finished.connect(self.show_rows)
        self.loader.failed.connect(self.show_error)

    def import_file(self, path: str) -> None:
        self.loader.start(path)

    def show_progress(self) -> None:
        if self.loader.is_running:
            self.status.text = f"Processed {self.loader.progress or 0} rows"

    def show_rows(self, rows: list[list[str]]) -> None:
        self.status.text = f"Done: {len(rows)} rows"

    def show_error(self, error: Exception) -> None:
        self.status.text = f"Failed: {error}"
```

Use `main_view.jobs.task(work)` in the main view, or
[`self.build_task(work)`](#a-task-of-another-view) in another view.

- **Its state.** These attributes are read-only.
  - `is_running` stays true until the task receives the outcome.
  - `progress` holds the last value reported, also once the run is over.
  - `result` holds the result of a run that succeeded, and `error` the exception of a run
    that failed. `progress`, `result`, and `error` are `None` while they have no value.
  - `has_result` tells a run that succeeded with a result of `None` from an idle task or a
    task that failed.
- **Start again.** `start` clears `progress`, `result`, and `error`, emits `changed` with
  `is_running` true, and returns `True`. While the task runs, another `start` returns
  `False`: it changes nothing and starts no function. Other tasks and jobs can run at the
  same time. A `finished` or `failed` callback can start the next run. For an input that
  changes quickly, use [`start_latest`](#run-the-latest-call-only) instead.
- **Cancel and drop.** `task.cancel()` asks only the current run of this task to stop. As
  `job.cancel()`, it works from any thread, and the function still returns its outcome.
  `jobs.cancel()` cancels every run. New, Open, closing the app, and `jobs.drop()` clear
  the state of every task and emit `changed`, also for a task that is over. The progress
  and the outcome of a dropped run never reach the task, so they cannot overwrite a new run.
- **One callback per outcome.** Connect `finished` to show a result, and `failed` to show an
  error. Their callbacks get the result or the exception, so they read no state. `changed`
  then only shows that a run is in progress. New, Open, and `jobs.drop()` emit neither.
- **Each progress value.** `progress` holds only the last value, and `changed` also emits
  for a start, a cancel, and an outcome. To use each value once, such as a chunk of output
  that a `ConsoleView` appends, connect `progress_reported`: its callbacks get the value.
- **Callbacks and types.** The callbacks of `changed`, `progress_reported`, `finished`, and
  `failed` can ask for `main_view` and `model`. The annotations of the function give the
  types of `result`, `progress`, and the arguments of `start`.
- **Where to start.** Create and start a task from app setup or a callback. From the
  function of a job, both operations raise `CalledInJobError`.
- **Errors.** A task follows the [rules of a job](#how-jobs-behave) for failures and
  programming errors. After a programming error, `error` and `result` are `None`,
  `has_result` is false, and the task can start a new run.
- **Not study data.** Create the task in `__attrs_post_init__`, as an attribute of the
  instance, not as a view field. The study then does not save it. New and Open keep the
  same task, and clear its state with the jobs of the study.

### A task of another view

`view.build_task(work)` builds a task in a view that is not the main view, such as a panel or a row
of a `ListView`. The jobs of the main view that holds the view run it. Build it in the view's
`__attrs_post_init__`, as a main view does. A main view can call `self.build_task(work)` too.

```python
from composeui.core.jobs import Job
from composeui.core.view import LabelView, MainView, View, child, define_view


def read_rows(_job: Job[int], count: int) -> int:
    return count


@define_view
class RowsPanel(View):
    status: LabelView = child(LabelView)
    rows: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loader = self.build_task(read_rows)
        self.loader.show_state(self.status, views=[self.rows])
        self.loader.finished.connect(self.show_rows)

    def show_rows(self, count: int) -> None:
        self.rows.text = f"{count} rows"


@define_view
class PanelView(MainView):
    panel: RowsPanel = child(RowsPanel)


main_view = PanelView()
main_view.panel.loader.start(3)
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert main_view.panel.rows.text == "3 rows"
```

- **Its main view's jobs.** The view's task can start once a main view holds the view: once
  the main view is built, or once a `ListView` builds the row. Until then, `start` and
  `start_latest` raise `RuntimeError`. `show_state`, `disables`, `cancel_with`, and the
  reactive methods follow the task before it starts.
- **A row removed.** When a `ListView` removes the view of a row, the task of the view cancels
  its run. The outcome of that run, and the task's `changed` signal, then reach no view. The
  task cannot start again. A changed record also gets a new view, unless `update_item` shows
  the change in the old one.
- **The same task.** The rules of [Reusable loading tasks](#reusable-loading-tasks) apply to
  it: New, Open, and `jobs.drop()` reset it with the other tasks.

### Run the latest call only

Connect the input to `task.start_latest(...)` so a new search replaces a pending or
running search. If the user types `cats` while the search for `cat` is still running,
the result for `cat` no longer reaches the view.

```python
from composeui.core.jobs import Job
from composeui.core.view import InputView, LabelView, MainView, child, define_view


def search_titles(job: Job[list[str]], query: str) -> list[str]:
    matches = []
    for title in ("Cat care", "Big cats", "Bird watching"):
        job.raise_if_canceled()
        if query.casefold() in title.casefold():
            matches.append(title)
    return matches


@define_view
class SearchView(MainView):
    query: InputView = child(InputView)
    results: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.search = self.jobs.task(search_titles)
        self.query.text_changed.connect(self.search.start_latest)
        self.search.finished.connect(self.show_results)

    def show_results(self, titles: list[str]) -> None:
        self.results.text = ", ".join(titles) or "No matches"


main_view = SearchView()
for query in ("cat", "cats"):  # As the user types.
    main_view.query.text_changed.emit(query)
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert main_view.results.text == "Big cats"
```

- **It waits first.** A run waits `debounce` seconds before it calls the function: 0.2 by
  default, or the `debounce` that `jobs.task(work, debounce=...)` gives. A newer call in that
  time replaces the run before the function starts. Several quick keystrokes can lead to
  just one call to the function.
- **The latest wins.** A newer call asks the current run to stop and drops its progress
  and outcome. `finished` and `failed` do not emit for a replaced run. The worker can
  check `job.is_canceled` or call `job.raise_if_canceled()` to stop early. Replacing a
  run does not undo effects such as writes to a file.
- **Its state.** `start_latest` clears `progress` and `error`, and emits `changed` with
  `is_running` true. `result` keeps the last result until the outcome of the new run. It
  returns nothing. While its run is in progress, `start` returns `False`, as for a run of `start`.
- **Where to start.** As with `start`, call it from app setup or a callback. From the
  function of a job, it raises `CalledInJobError`.
- **From a reactive method.** A [reactive method](reactive-methods.md#slow-work-in-a-task) can
  call `start_latest` with the fields that it reads, and another one show the result.

### Show a task's state

`task.show_state(status, views=...)` shows the state of the task in `status`, a
`LabelView`, and shows `views` only once the task has a result. It replaces a `changed`
callback that shows the loading and the error:

```python
from composeui.core.jobs import Job
from composeui.core.view import ChartView, LabelView, MainView, child, define_view


def read_rows(_job: Job[int], count: int) -> int:
    return count


@define_view
class RowsView(MainView):
    status: LabelView = child(LabelView)
    chart: ChartView = child(ChartView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loader = self.jobs.task(read_rows)
        self.loader.show_state(
            self.status, views=[self.chart], failed_text="Can't read the rows: {error}"
        )


main_view = RowsView()
assert main_view.status.text == "Loading..."
assert not main_view.chart.is_visible
main_view.loader.start(3)
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert not main_view.status.is_visible
assert main_view.chart.is_visible
```

- **Its texts.** `status` shows `loading_text`, then `progress_text` once the run reports
  progress, or `failed_text` after a failure. By default, they are "Loading...",
  "Loading... ({progress})", and "Failed: {error}". `{progress}` and `{error}` take the
  task's `progress` and `error`, with a format if you give one, such as `{progress:,}`.
- **Translated.** The label translates the texts into the main view's language. ComposeUI's
  catalogs hold the default texts, and the app's catalogs hold the texts that it gives.
- **From now on.** It shows the state at once, also before the first run: `status` shows
  `loading_text`, and `views` are hidden. New, Open, and `jobs.drop()` clear the result:
  `views` hide again until the next run has a result.
- **As a reactive method.** It follows the state of the task as a
  [reactive method](reactive-methods.md#helpers-that-follow-their-inputs) of `status` does:
  after the event that changed the state, with the other methods.
- **With the other signals.** Connect `finished` to give the views their data. `changed`,
  `finished`, and `failed` keep their other callbacks.

The [Uber pickups example](../../src/examples/uberpickups.py) imports its CSV file in a
loading task. `show_state` shows the count of rows read or the error in a status line, and
the chart and the map once the task has a result. Its
[reactive methods](reactive-methods.md) give them their data.

### Disable views while a task runs

`task.disables(*views)` disables `views` while the task runs, such as the fields of its run
and its Run button. `task.cancel_with(*controls)` cancels the run when one of `controls` is
clicked: a `ButtonView`, or an `ActionView` of a menu or a toolbar, such as Stop. They replace
the callbacks that enable and disable the controls at each start and outcome:

```python
from composeui.core.jobs import Job
from composeui.core.view import (
    ButtonView,
    FormView,
    LabelRowInputView,
    MainView,
    child,
    define_view,
)


def solve(job: Job[str], study: str) -> str:
    while job.sleep(0.01):  # Solve the study here, a step at a time.
        pass
    return f"{study}: stopped"


@define_view
class SolverForm(FormView):
    study: LabelRowInputView = child(LabelRowInputView, label="Study", text="beam.comm")


@define_view
class SolverView(MainView):
    form: SolverForm = child(SolverForm)
    run: ButtonView = child(ButtonView, text="Run")
    stop: ButtonView = child(ButtonView, text="Stop")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.solver = self.jobs.task(solve)
        self.solver.disables(self.form.study, self.run)
        self.solver.cancel_with(self.stop)
        self.run.clicked.connect(lambda: self.solver.start(self.form.study.text))


main_view = SolverView()
assert not main_view.stop.is_enabled
main_view.run.clicked.emit()
assert not main_view.run.is_enabled
main_view.stop.clicked.emit()
assert not main_view.stop.is_enabled  # Asked to stop: it can't be asked again.
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert main_view.run.is_enabled
assert main_view.solver.result == "beam.comm: stopped"
```

- **From now on.** The task sets `is_enabled` at once, then at each start and outcome: a
  success, a failure, or the end of a canceled run. New, Open, and `jobs.drop()` end the
  run, and the views come back too.
- **Asked to stop.** `cancel_with`'s controls are enabled only while a run is in progress, until
  it is asked to stop. `task.cancel()` sets `is_canceled`, and `changed` emits: a
  `changed` callback can show "Stopping..." until the run is over.
- **The task's views.** The task alone sets their `is_enabled`: do not set it from another
  callback or a reactive method too. For a view with a condition of its own, give it to
  `disables` as `enabled_if`. The view is then enabled only while the task is not running
  and the condition is true:

  ```python
  self.solver.disables(self.run, enabled_if=lambda: self.form.study.text != "")
  ```

  The task checks the condition again each time a view field that it reads changes, as a
  [reactive method](reactive-methods.md) does. An empty study then disables Run, also after
  a run.

## Data shared by the sessions

`@shared_data`, from `composeui.core.shared`, loads data once per process, for every session
that asks for it. Use it for data that every user reads, such as a large CSV file of a
dashboard. On the web, 4 sessions then read the file once and keep one copy of its columns.

Give it a function that takes only its job. Then pass the decorated function to `jobs.task`, as
any function of a job:

```python
import polars as pl

from composeui.core.dashboard import DashboardView
from composeui.core.jobs import Job
from composeui.core.shared import shared_data
from composeui.core.view import LabelView, child, define_view

DATA_URL = "https://s3-us-west-2.amazonaws.com/streamlit-demo-data/uber-raw-data-sep14.csv.gz"


@shared_data
def read_pickups(_job: Job[pl.DataFrame]) -> pl.DataFrame:
    return pl.read_csv(DATA_URL)


@define_view
class PickupsView(DashboardView):
    status: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loader = self.jobs.task(read_pickups)
        self.loader.show_state(self.status)
        self.loader.start()
```

- **One load.** The first job starts the load in a thread of its own. The jobs that start
  meanwhile wait for it, and each gets its progress (`job.report_progress`). The jobs that
  start later get the value at once.
- **No arguments.** The function takes only its job, so a session's input can't reach it.
  Put fixed values, such as the file's address, in the function. Never load the private data
  of a user with it. A function that takes other arguments raises `TypeError`.
- **Read-only.** Each session gets a value that its changes can't spread from:
  - a Polars frame or series: a clone, which shares the columns, so it costs almost nothing.
  - a pandas frame or series: a copy that shares the columns, only when pandas' copy-on-write
    is on. It is always on from pandas 3. Before, set `pd.options.mode.copy_on_write = True`.
  - a NumPy array: a read-only view, without a copy. The arrays that it is a view of become
    read-only too, also an array that the app keeps: a later write to it raises `ValueError`.
    A memory-mapped file (`numpy.load(path, mmap_mode="r")`) stays in its file. An array over
    memory that can be written, such as a `bytearray` or a file opened with `mmap_mode="r+"`,
    is refused.
  - a lazy Polars frame, a PyArrow table or a chunked array: the value itself.
  - an immutable value, such as a number, a string, a date, `None`, an enum member, or a
    `tuple`, a `frozenset` or a frozen `attrs` class of them: the value itself. Each value
    that they hold is checked, at any depth. A frame in a tuple is refused.

  Any other value fails the jobs with `SharedDataError`, with the reason: for example a list,
  a dict, a pandas frame without copy-on-write, or a column of Python objects that a session
  could change, such as lists.
- **Canceled.** A job canceled stops waiting and raises `JobCanceledError`. When no job waits
  for the load any longer, its own job is canceled: the load reads `job.is_canceled` to stop
  early. Its value isn't kept, and the next job loads again.
- **Failures.** A load that fails fails every job that waits for it. Each job gets its own copy
  of the exception, whose traceback goes on into the load. The failure isn't kept: the next job
  loads again.
- **No main thread.** The load runs for every session, so `job.call_on_main_thread` raises
  `CalledInJobError` in it.
- **Until the process ends.** The value stays for the life of the process. On the web,
  `--reload` starts a new process. On Qt and Textual, a reload runs the modules of the
  program's folder again, which makes a new value. A `@shared_data` of a module outside that
  folder keeps its value. `read_pickups.forget()` drops the value, so that the next job loads
  again. The sessions keep their copies. A test that changes the data calls it.

The [Uber pickups example](../../src/examples/uberpickupsframe.py) and the
[first dashboard](../../src/examples/uberdashboard.py) read their CSV file this way.

## A limit on the jobs that run at once

`JobSlots`, from `composeui.core.jobs`, lets at most a number of jobs run a block at once. The
other jobs wait in line, in the order that they came. Use it for heavy work, such as a solver:
on the web, each session can start one, and 10 users would run 10 solvers at once.

Make it at the level of a module, so that every session of the process shares it. In the
function of a job, run the heavy work in `slot(job)`:

```python
import sys

from composeui.core.jobs import Job, JobSlots
from composeui.core.view import ConsoleView, MainView, child, define_view

SOLVER = "print('Done')"
SOLVER_RUNS = JobSlots(4)  # At most 4 solvers at once, for every session.


def run_solver(job: Job[int, str], command: list[str]) -> int:  # in its thread
    def show_place(place: int) -> None:
        job.report_progress(f"Waiting for a solver: place {place} in the line\n")

    with SOLVER_RUNS.slot(job, on_wait=show_place):
        return job.run_process(command, on_output=job.report_progress)


@define_view
class SolverView(MainView):
    output: ConsoleView = child(ConsoleView)

    def run(self) -> None:
        job = self.jobs.start(run_solver, [sys.executable, "-c", SOLVER])
        job.progress.connect(self.output.append)


main_view = SolverView()
main_view.run()
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert main_view.output.text == "Done\n"
```

- **In line.** When no slot is free, the job waits behind the jobs that came before it. A job
  that gets a slot at once doesn't wait.
- **Its place.** While the job waits, `on_wait` gets its place in the line, from 1, each time
  the place changes. It runs in the thread of the job: report the place with
  `job.report_progress`. Without `on_wait`, the job waits without a report.
- **Canceled.** A job canceled before it gets a slot raises `JobCanceledError`, also with a
  slot free. A job canceled while it waits leaves the line, and the jobs behind it move up.
  New, Open and closing the app cancel the jobs, and so does a session that ends on the web:
  their jobs leave the line too.
- **Freed.** The slot is free again when the block ends, also when it raises. Code before or
  after the block, such as preparing the files of a run, takes no slot. A job canceled in the
  block keeps its slot until the block ends, as its work may still run: `job.run_process`
  stops its program, other code reads `job.is_canceled`.
- **One slot per job.** A job that asks for a second slot raises `RuntimeError`, also from
  `on_wait` while it waits: without a slot left, it would wait for itself. Call `slot` in the
  function of its job only. Called on the main thread, it raises `RuntimeError`, as the app
  would freeze.
- **Per process.** The limit holds for the jobs of one process. On Qt and Textual, a process
  has one user, and the limit holds for the jobs of that user. On the web, nothing limits the
  share of one session: a user who starts many jobs can fill the line, and the jobs of the
  other users wait behind them.
- **Reload.** On Qt and Textual, a reload runs the modules of the program's folder again, which
  makes a new `JobSlots`. The jobs of the old one that still run don't count in the new one.

## How jobs behave

These rules hold for every job, and for the jobs of a task.

- **Where callbacks run.** Qt and Textual deliver job signals and callbacks on the UI thread.
  On the web, after the main view renders, they run on the job's thread under the session
  lock. This prevents a request and a job callback from changing the same session at the
  same time. Callbacks queued before rendering run as part of rendering.
- **Work and callbacks.** Call `jobs.start`, `jobs.cancel`, and `jobs.drop` from app setup
  or a callback. They raise `CalledInJobError` from the function of a job. To start another
  job, return what it needs, and start it from the callback that gets it. `job.cancel()`
  works from any thread.
- **Failures.** When a job fails, `failed` emits the exception. Connect it to show the
  error and clear the progress indicator. Do this in the callback, not in the job function.
  - A `RefusedError` (`composeui.core.model`) logs a warning with its message, without a
    traceback. Raise it for an expected refusal, for example of bad input or of a rule of
    the app.
  - A `JobCanceledError` (`composeui.core.jobs`) logs its message as information, without a
    traceback. Raise it from a function that stops without a result because it was canceled.
  - Another exception logs an error with its traceback, even when a `failed` callback
    shows it. Do not turn an unexpected error into a `RefusedError` to hide its traceback.
  - A `ValueError`, a `KeyError`, or an I/O error follows this path too, because external
    data can cause it.
- **Programming errors.** An uncaught `CalledInJobError`, `AssertionError`,
  `AttributeError`, `NameError`, `NotImplementedError`, or `TypeError` leaves the function
  of the job. The job chooses by the type of the exception, not by its cause.
  - Python reports its traceback through `threading.excepthook`. `failed` does not emit
    it, and a [task](#reusable-loading-tasks) does not keep it as its `error`.
  - The job no longer counts as running. Its task, if any, goes back to idle and emits
    `changed`. The other jobs go on.
  - Without a toolkit, `jobs.wait()` runs this clean-up. It does not raise the error again.
  - A dropped job reports its programming errors too.
- **New, Open, and closing the app** cancel the running jobs and drop their results,
  because the results belong to the study replaced. Closing does not wait for the jobs either.
  Open drops the jobs once the views' state in the file is checked, before the model's
  data changes. So an Open that fails still stops the jobs.
- **On the web,** while any job runs, the page asks the server every 300 ms for the changes
  of the jobs. It stops once they are over.
- **Tests.** When no toolkit shows a main view, its jobs emit their results when the test
  calls `main_view.jobs.wait()`, on the thread of the test (see
  [Test the jobs](testing.md#test-the-jobs)).
