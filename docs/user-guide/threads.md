# Running work in threads

A long computation would freeze the app while it runs. `main_view.jobs.start(work, *args)`
runs `work(job, *args)` in a thread of its own instead.

The function must not touch a view, because the widgets of a toolkit belong to the main
thread. The function returns its result. The `finished` signal of its job emits the result
on the main thread, where the callbacks update the views:

```python
from composeui.core.jobs import Job
from composeui.core.view import MainView, define_view


def simulate(job: Job[float], radius: float) -> float:  # in its thread
    for step in range(100):
        if job.is_canceled:
            return float("nan")
        ...  # a step of the computation
    return stress


@define_view
class PipeMainView(MainView):
    ...
    def _run(self) -> None:
        job = self.jobs.start(simulate, self.form.radius.value)
        job.finished.connect(self._show_stress)  # on the main thread

    def _show_stress(self, stress: float) -> None:
        self.results.stress.text = f"{stress:g} MPa"
```

- **Errors.** When the function raises, the `failed` signal of its job emits the exception
  on the main thread, where a callback shows it (see [Failures](#how-jobs-behave)).
- **Callbacks** connected to the signals of a job get the `main_view` and `model` that they
  ask for, as for any signal.
- **Running or not.** `jobs.is_running` tells whether any job runs. `jobs.running_changed`
  emits it when it changes, for example to disable a Run button.

[`src/examples/taskview.py`](../../src/examples/taskview.py) runs 25 jobs at once, and cancels
them.

## Progress and canceling

- **Progress.** In the function, `job.report_progress(value)` reports a value of your
  choice, such as a count, a percentage, or a message. `job.progress` emits each value on
  the main thread, in the order of the reports, before `finished` or `failed`. Connect it
  as `finished` and `failed` are. Its callbacks can ask for `main_view` and `model` too.
  - Annotate the function's job as `Job[ResultT, ProgressT]`: the second type is the type
    of the values, and of the callbacks' argument. `Job[ResultT]` is a job without
    progress, its `ProgressT` `None`.
  - A dropped job emits none of the values that still wait.
  - `job.call_on_main_thread(callback)` runs any other callback on the main thread, in the
    same order and with the same rule for a dropped job.
- **Canceling.** `job.cancel()`, or `jobs.cancel()` for all the jobs, asks the functions to
  stop. Python can't stop a thread, so each function checks `job.is_canceled`, or waits with
  `job.sleep(seconds)`, which returns False once the job is canceled. The function still
  finishes, and `finished` emits what it returned.

To report rows processed, connect a handler right after starting the job:

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

## Reusable loading tasks

Use `main_view.jobs.task(work)` when a view repeatedly runs the same worker and shows its
loading state. Configure the task once, then call `task.start(*args, **kwargs)` for each run.
One `changed` signal reports starts, progress, success, failure, and resets on the main thread.
After it, `finished` emits the result of a run that succeeds, and `failed` the exception of a
run that fails, as the signals of a job do.

```python
from composeui.core.jobs import Job
from composeui.core.view import LabelView, MainView, child, define_view


def count_rows(job: Job[int, int], count: int) -> int:
    for completed in range(1, count + 1):
        if job.is_canceled:
            return completed - 1
        job.report_progress(completed)
    return count


@define_view
class LoadingView(MainView):
    status: LabelView = child(LabelView, text="Ready")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loader = self.jobs.task(count_rows)
        self.loader.changed.connect(self.show_progress)
        self.loader.finished.connect(self.show_rows)
        self.loader.failed.connect(self.show_error)

    def show_progress(self) -> None:
        if self.loader.is_running:
            self.status.text = f"Processed {self.loader.progress or 0} rows"

    def show_rows(self, rows: int) -> None:
        self.status.text = f"Done: {rows} rows"

    def show_error(self, error: Exception) -> None:
        self.status.text = f"Failed: {error}"


main_view = LoadingView()
main_view.loader.start(3)
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert main_view.status.text == "Done: 3 rows"
```

- **Its state.** These attributes are read-only.
  - `is_running` stays true until the outcome of the run comes to the main thread.
  - `progress` holds the last value reported, also once the run is over.
  - `result` holds the result of a run that succeeded, and `error` the exception of a run
    that failed. `progress`, `result`, and `error` are `None` while they have no value.
  - `has_result` tells a run that succeeded with a result of `None` from an idle task or a
    task that failed.
- **Start again.** `start` clears `progress`, `result`, and `error`, emits `changed` with
  `is_running` true, and returns `True`. While the task runs, another `start` returns
  `False`: it changes nothing and starts no function. Other tasks and jobs can run at the
  same time. A `finished` or `failed` callback can start the next run.
- **Cancel and drop.** `task.cancel()` asks only the current run of this task to stop. As
  `job.cancel()`, it works from any thread, and the function still returns its outcome.
  `jobs.cancel()` cancels every run. New, Open, closing the app, and `jobs.drop()` clear
  the state of every task and emit `changed`, also for a task that is over. The progress
  and the outcome of a dropped run never reach the task, so they can't overwrite a new run.
- **One callback per outcome.** Connect `finished` to show a result, and `failed` to show an
  error. Their callbacks get the result or the exception, so they read no state. `changed`
  then only shows that a run is going on. New, Open, and `jobs.drop()` emit neither.
- **Callbacks and types.** The callbacks of `changed`, `finished`, and `failed` can ask for
  `main_view` and `model`. The annotations of the function give the types of `result`,
  `progress`, and the arguments of `start`.
- **The main thread.** Create a task and call its `start` on the main thread. From the
  function of a job, both raise `CalledInJobError`.
- **Errors.** A task follows the [rules of a job](#how-jobs-behave) for failures and
  programming errors. After a programming error, `error` and `result` are `None`,
  `has_result` is false, and the task can start a new run.
- **Not study data.** Create the task in `__attrs_post_init__`, as an attribute of the
  instance, not as a view field. The study then does not save it. New and Open keep the
  same task, and clear its state with the jobs of the study.

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
- **With the other signals.** Connect `finished` to give the views their data. `changed`,
  `finished`, and `failed` keep their other callbacks.

The [Uber pickups example](../../src/examples/uberpickups.py) imports its CSV file in a
loading task. `show_state` shows the count of rows read or the error in a status line, and
the chart and the map once the task has a result. Its `finished` callback gives them their
data.

## How jobs behave

These rules hold for every job, and for the jobs of a task.

- **On the main thread only.** Call `jobs.start`, `jobs.cancel`, and `jobs.drop` from a
  callback, never from the function of a job. The jobs aren't locked, because only the main
  thread changes them (`job.cancel()` works from any thread). Called from the function of a
  job, they raise `CalledInJobError`. To start another job, return what it needs, and start
  it from the callback that gets it.
- **Failures.** When the function raises, the job's `failed` signal emits the exception on
  the main thread. Connect a callback to it to show the error, and to clear what shows
  that the work runs. Do not do it in the function of the job.
  - A `RefusedError` (`composeui.core.model`) logs a warning with its message, without a
    traceback. Raise it for an expected refusal, for example of bad input or of a rule of
    the app.
  - Another exception logs an error with its traceback, even when a `failed` callback
    shows it. Do not turn an unexpected error into a `RefusedError` to hide its traceback.
  - A `ValueError`, a `KeyError`, or an I/O error follows this path too, because external
    data can cause it.
- **Programming errors.** An uncaught `CalledInJobError`, `AssertionError`,
  `AttributeError`, `NameError`, `NotImplementedError`, or `TypeError` leaves the function
  of the job. The job chooses by the type of the exception, not by its cause.
  - Python reports its traceback through `threading.excepthook`. `failed` does not emit
    it, and a [task](#reusable-loading-tasks) does not keep it as its `error`.
  - The job still stops on the main thread: it no longer counts as running, and its task,
    if any, goes back to idle and emits `changed`. The other jobs go on.
  - Without a toolkit, `jobs.wait()` runs this clean-up. It does not raise the error again.
  - A dropped job reports its programming errors too.
- **New, Open, and closing the app** cancel the running jobs and drop their results,
  because the results belong to the study replaced. Closing doesn't wait for the jobs either.
  Open drops the jobs once the views' state in the file is checked, before the model's
  data changes. So an Open that fails still stops the jobs.
- **On the web,** while any job runs, the page asks the server every 300 ms for the changes
  of the jobs. It stops once they are over.
- **Tests.** When no toolkit shows a main view, its jobs emit their results when the test
  calls `main_view.jobs.wait()`, on the thread of the test (see
  [Test the jobs](testing.md#test-the-jobs)).
