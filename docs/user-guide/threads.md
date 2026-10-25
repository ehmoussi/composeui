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

- **Failures.** The job's `failed` signal emits the exception on the main thread.
  Connect a handler to show the error and clear loading indicators there, not inside the
  worker function. A `RefusedError` (`composeui.core.model`) logs a warning with its
  message and no traceback. Other exceptions log an error with the full traceback,
  even when a `failed` handler shows them. Use `RefusedError` for an expected refusal;
  do not wrap unexpected programming errors just to hide their tracebacks.
- **Canceling.** `job.cancel()`, or `jobs.cancel()` for all the jobs, asks the functions to
  stop. Python can't stop a thread, so each function checks `job.is_canceled`, or waits with
  `job.sleep(seconds)`, which returns False once the job is canceled. The function still
  finishes, and `finished` emits what it returned.
- **On the main thread only.** Call `jobs.start`, `jobs.cancel`, and `jobs.drop` from a
  callback, never from the function of a job. The jobs aren't locked, because only the main
  thread changes them (`job.cancel()` works from any thread). Called from the function of a
  job, they raise `CalledInJobError`. To start another job, return what it needs, and start
  it from the callback that gets it.
- **Progress.** Connect `job.progress` to a handler, as with `job.finished` and `job.failed`.
  Annotate the worker's job as `Job[ResultT, ProgressT]`: the second type specifies progress
  values and handler arguments. `Job[ResultT]` defaults to `None` for jobs without progress.
  In the worker, call `job.report_progress(value)` with a count, percentage, message, or
  another application-defined value. The signal emits on the main thread, in report order,
  before `finished` or `failed`. Its callbacks can ask for `main_view` and `model` too.
  Dropped jobs do not emit progress that is still waiting. For an arbitrary UI callback,
  use `job.call_on_main_thread(callback)`; it follows the same ordering and drop rules.
- **Running or not.** `jobs.is_running` tells whether any job runs. `jobs.running_changed`
  emits it when it changes, for example to disable a Run button.
- **New, Open, and closing the app** cancel the running jobs and drop their results,
  because the results belong to the study replaced. Closing doesn't wait for the jobs either.
  Open drops the jobs once the views' state in the file is checked, before the model's
  data changes. So an Open that fails still stops the jobs.
- **Callbacks** connected to the signals of a job get the `main_view` and `model` that they
  ask for, as for any signal.
- **On the web,** while any job runs, the page asks the server every 300 ms for the changes
  of the jobs. It stops once they are over.
- **Tests.** When no toolkit shows a main view, its jobs emit their results when the test
  calls `main_view.jobs.wait()`, on the thread of the test.

[`src/examples/taskview.py`](../../src/examples/taskview.py) runs 25 jobs at once, and cancels
them.

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
        self.loader.changed.connect(self.show_loading)

    def show_loading(self) -> None:
        task = self.loader
        if task.is_running:
            self.status.text = f"Processed {task.progress or 0} rows"
        elif task.error is not None:
            self.status.text = f"Failed: {task.error}"
        elif task.has_result:
            self.status.text = f"Done: {task.result} rows"
        else:
            self.status.text = "Ready"


main_view = LoadingView()
main_view.loader.start(3)
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert main_view.status.text == "Done: 3 rows"
```

- **Read-only state.** `is_running` stays true until the outcome arrives on the main thread.
  `progress` holds the last reported value, including after completion. `result` holds the
  successful result; `error` holds the exception after failure. Unset values are `None`.
  `has_result` distinguishes a successful `None` result from an idle or failed task.
- **Starting again.** `start` clears progress, result, and error, then emits `changed` with
  `is_running=True`. It returns `True`. While the task runs, another `start` returns `False`
  without changing state or starting another worker. Other tasks and ordinary jobs can run
  at the same time. A success or failure handler can start the next run.
- **Canceling and dropping.** `task.cancel()` asks only this task's current run to stop.
  Like `job.cancel()`, it works from any thread, and the worker still returns its outcome.
  `jobs.cancel()` cancels all runs. New, Open, closing, and `jobs.drop()` clear every task's
  state and emit `changed`, even for completed tasks. Old queued progress and outcomes do
  not reach the task or overwrite a new run.
- **Callbacks and types.** `changed` callbacks can ask for `main_view` and `model`. The worker's
  annotations determine the types of `result`, `progress`, and the arguments of `start`.
  Create tasks and call `start` on the main thread; a job's worker raises `CalledInJobError`
  if it tries either operation. Task failures use the same logging rules as ordinary jobs.
- **Runtime state.** Create a task as an instance attribute in `__attrs_post_init__`, as above,
  not as a view field. It is then absent from saved view state. The same task is reused after
  New or Open; its state is cleared with the study's jobs.

The [Uber pickups example](../../src/examples/uberpickups.py) uses one task-state handler for
CSV progress, failures, and the completed table and chart. A separate visibility callback
reads `task.is_running`, `task.has_result`, and the checkbox state. Both `task.changed` and
the checkbox's `toggled` signal call it, so loading and checkbox changes use the same rules.
