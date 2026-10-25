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
- **Progress.** The function gives the main thread a callback with
  `job.call_on_main_thread(callback)`, for example to move a progress bar while it works.
  The callbacks are called in order, before the job emits its outcome. When the job is
  dropped, the callbacks that are still waiting are not called.
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
