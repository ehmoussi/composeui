"""Work run in threads, its results given back on the main thread (see `Jobs`)."""

from __future__ import annotations

import functools
import logging
import queue
import threading
import time
import weakref
from typing import TYPE_CHECKING, Any, Callable, Generic

from typing_extensions import Concatenate, ParamSpec, TypeVar, TypeVarTuple, Unpack

from composeui.core.model import RefusedError
from composeui.core.signal import Signal, SignalNoArgs

if TYPE_CHECKING:
    from composeui.core.model import Model
    from composeui.core.renderer import Renderer, RendererContainer
    from composeui.core.view import MainView

__all__ = ["CalledInJobError", "Job", "Jobs", "Task"]

LOGGER = logging.getLogger("COMPOSEUI")

R = TypeVar("R")
ProgressT = TypeVar("ProgressT", default=None)
P = ParamSpec("P")
Ts = TypeVarTuple("Ts")

#: the job a thread runs, in a job's thread (see `Jobs.start`)
_CURRENT = threading.local()


class CalledInJobError(RuntimeError):
    """A job's function tried to start or change jobs instead of using a main-thread callback."""


def current_job() -> Job[Any, Any] | None:
    """Get the job whose function runs on this thread; None on any other thread."""
    job: Job[Any, Any] | None = getattr(_CURRENT, "job", None)
    return job


def _check_main_thread(method: str) -> None:
    """Raise `CalledInJobError` in a job's thread: `Jobs` is only changed on the main one."""
    if current_job() is not None:
        msg = (
            f"{method} must be called on the main thread, not by a job's function: call it"
            " from a callback of the job's finished signal instead"
        )
        raise CalledInJobError(msg)


class Job(Generic[R, ProgressT]):
    """A function running in a thread of its own, started by `Jobs.start`.

    The function gets its job first: it calls `sleep`, or reads `is_canceled`, to stop
    early once canceled. Its result, or what it raised, is emitted on the main thread.
    Programming errors instead escape the worker after dispatching cleanup; see `Jobs`.
    """

    def __init__(self, hand_over: Callable[[Job[Any, Any], Callable[[], None]], None]) -> None:
        # `Jobs._hand_over`, giving a callback to the main thread
        self._hand_over = hand_over
        #: the function's return value, on the main thread
        self.finished = Signal[R]()
        #: a non-programming exception, on the main thread (logged too; see `Jobs`)
        self.failed = Signal[Exception]()
        #: progress values reported by the worker, on the main thread
        self.progress = Signal[ProgressT]()
        self._canceled = threading.Event()

    @property
    def is_canceled(self) -> bool:
        return self._canceled.is_set()

    def cancel(self) -> None:
        """Ask the function to stop; it still finishes, as soon as it notices."""
        self._canceled.set()

    def sleep(self, seconds: float) -> bool:
        """Wait `seconds`, in the job's thread; False if it was canceled meanwhile."""
        return not self._canceled.wait(seconds)

    def call_on_main_thread(self, callback: Callable[[], None]) -> None:
        """Call `callback` on the main thread, e.g. to show how far the function has gone.

        Called in order, before the job's outcome is emitted; not at all once the job is
        dropped (New, Open, closing the app). Without a toolkit, `Jobs.wait` calls it.
        """
        self._hand_over(self, callback)

    def report_progress(self, value: ProgressT) -> None:
        """Emit `progress` on the main thread, in order and before the job's outcome.

        Pass a count, percentage, message, or another application-defined value.
        Dropped jobs do not emit queued progress, as with `call_on_main_thread`.
        """
        self.call_on_main_thread(functools.partial(self.progress.emit, value))


class Task(Generic[R, P, ProgressT]):
    """A reusable worker with read-only loading state, built by `Jobs.task`.

    `changed` emits on the main thread when a run starts, reports progress, finishes,
    fails, or is dropped. After it, `finished` emits a run's result, and `failed` its
    exception, as a `Job`'s do. Their callbacks can ask for ``main_view`` and ``model``.
    Starting an already running task does nothing. Dropping the owner's jobs resets
    the task and discards queued progress and outcomes, as with ordinary jobs.
    """

    def __init__(self, jobs: Jobs, work: Callable[Concatenate[Job[R, ProgressT], P], R]) -> None:
        self._jobs = jobs
        self._work = work
        self.changed = SignalNoArgs()
        #: the result of a run that succeeded, on the main thread
        self.finished = Signal[R]()
        #: the exception of a run that failed, on the main thread
        self.failed = Signal[Exception]()
        self._job: Job[R, ProgressT] | None = None
        self._reset()

    @property
    def is_running(self) -> bool:
        """Get whether this task is waiting for its current run's outcome."""
        return self._job is not None

    @property
    def progress(self) -> ProgressT | None:
        """Get the last progress value, or None before the run reports one."""
        return self._progress

    @property
    def result(self) -> R | None:
        """Get the successful result, or None before success; see `has_result`."""
        return self._result

    @property
    def error(self) -> Exception | None:
        """Get the run's exception, or None before failure."""
        return self._error

    @property
    def has_result(self) -> bool:
        """Get whether the last run succeeded, including a result of None."""
        return self._has_result

    def start(self, *args: P.args, **kwargs: P.kwargs) -> bool:
        """Start the worker with fresh state; return False if it is already running."""
        _check_main_thread("Task.start")
        if self.is_running:
            return False
        self._reset()
        job = self._jobs._new_job(self._work)  # noqa: SLF001 (shared job lifecycle)
        self._job = job
        job.progress.connect(self._report_progress)
        job.finished.connect(self._finish)
        job.failed.connect(self._fail)
        self._jobs._start_job(job, self._work, args, kwargs)  # noqa: SLF001 (shared job lifecycle)
        self.changed.emit()
        return True

    def cancel(self) -> None:
        """Ask the current run to stop; it still emits its outcome, as with `Job.cancel`."""
        job = self._job
        if job is not None:
            job.cancel()

    def _reset(self) -> None:
        self._job = None
        self._progress: ProgressT | None = None
        self._result: R | None = None
        self._error: Exception | None = None
        self._has_result = False

    def _report_progress(self, value: ProgressT) -> None:
        self._progress = value
        self.changed.emit()

    def _finish(self, result: R) -> None:
        self._job = None
        self._result = result
        self._has_result = True
        self.changed.emit()
        self.finished.emit(result)

    def _fail(self, error: Exception) -> None:
        self._job = None
        self._error = error
        self.changed.emit()
        self.failed.emit(error)


class Jobs:
    """The jobs of a main view (`MainView.jobs`): functions run in threads.

    A job's function runs in a thread, so that the app stays responsive. It must not touch
    a view, because a toolkit's widgets belong to the main thread. It returns its result
    instead, and its job's `finished` emits the result on the main thread. There,
    callbacks update the views. Like the callbacks of any signal, they get the `main_view`
    and `model` they ask for. `Job.report_progress` emits the job's `progress` signal on
    the main thread. `Job.call_on_main_thread` hands it an arbitrary callback instead.
    A `SqliteModel` hands it the `changed` signals of the job's writes.

    `task` configures a reusable worker with progress, result and error state. Its
    ``changed`` signal shows the loading state, and its ``finished`` and ``failed``
    signals the outcome of each run.

    Call `start`, `cancel` and `drop` on the main thread, e.g. from a callback. Never call
    them from a job's function: the jobs aren't locked, as the main thread alone changes
    them. `Job.cancel` is the exception: any thread can call it. Called from a job's
    function, they raise `CalledInJobError`. To start another job, return what it needs
    instead, and start it from the callback that gets it.

    Uncaught `CalledInJobError`, `AssertionError`, `AttributeError`, `NameError`,
    `NotImplementedError` and `TypeError` escape the worker to Python's thread exception
    handler. Cleanup is dispatched to the main thread, without emitting `failed` or
    setting a task's `error`. The affected task returns to its idle state.

    New, Open and closing the app cancel the jobs running, and drop their results: the
    results belong to the study replaced.
    """

    def __init__(self, main_view: MainView) -> None:
        self._main_view = weakref.ref(main_view)
        self._model: weakref.ReferenceType[Model] | None = None
        #: True as the first job starts, False once the last one is over
        self.running_changed = Signal[bool]()
        self.running_changed.set_main_view(main_view)
        # the jobs started and not over yet: only changed on the main thread
        self._running: set[Job[Any, Any]] = set()
        self._tasks: list[Task[Any, Any, Any]] = []
        # the results handed back while the main view isn't rendered, for `wait`, or for its
        # renderer once it has one (`hand_over_to`)
        self._results: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        # whether the queued results went to the renderer: the jobs' threads queue theirs
        # until then, so none waits forever or overtakes one queued before it
        self._handed_over = False
        self._results_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return len(self._running) > 0

    def set_model(self, model: Model) -> None:
        """Give `model` to the callbacks asking for it (the app does)."""
        self._model = weakref.ref(model)
        self.running_changed.set_model(model)
        for task in self._tasks:
            for signal in (task.changed, task.finished, task.failed):
                signal.set_model(model)

    def task(self, work: Callable[Concatenate[Job[R, ProgressT], P], R]) -> Task[R, P, ProgressT]:
        """Build a reusable task for `work`, without starting it; call on the main thread."""
        _check_main_thread("Jobs.task")
        task = Task(self, work)
        name = getattr(work, "__name__", "task")
        self._bind_signal(task.changed, f"{name}.changed")
        self._bind_signal(task.finished, f"{name}.finished")
        self._bind_signal(task.failed, f"{name}.failed")
        self._tasks.append(task)
        return task

    def start(
        self,
        work: Callable[Concatenate[Job[R, ProgressT], P], R],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> Job[R, ProgressT]:
        """Run ``work(job, *args, **kwargs)`` in a thread; call it on the main thread.

        Connect to the job's signals right away: its outcome is emitted on the main
        thread, so no sooner than the code calling `start` is done. Raises
        `CalledInJobError` in a job's thread.
        """
        _check_main_thread("Jobs.start")
        job = self._new_job(work)
        self._start_job(job, work, args, kwargs)
        return job

    def _bind_signal(self, signal: Signal[Unpack[Ts]], name: str) -> None:
        signal.set_name(name)
        main_view = self._main_view()
        model = None if self._model is None else self._model()
        # Jobs and tasks are created while their main view lives.
        if main_view is not None:  # pragma: no branch
            signal.set_main_view(main_view)
        if model is not None:
            signal.set_model(model)

    def _new_job(self, work: Callable[Concatenate[Job[R, ProgressT], P], R]) -> Job[R, ProgressT]:
        job: Job[R, ProgressT] = Job(self._hand_over)
        name = getattr(work, "__name__", "job")
        self._bind_signal(job.finished, f"{name}.finished")
        self._bind_signal(job.failed, f"{name}.failed")
        self._bind_signal(job.progress, f"{name}.progress")
        return job

    def _start_job(
        self,
        job: Job[R, ProgressT],
        work: Callable[..., R],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        self._running.add(job)
        if len(self._running) == 1:
            self.running_changed.emit(True)  # noqa: FBT003
        # a daemon: closing the app doesn't wait for it
        thread = threading.Thread(target=self._run, args=(job, work, args, kwargs), daemon=True)
        thread.start()

    def cancel(self) -> None:
        """Cancel every job running; each still finishes, as soon as it notices.

        Raises `CalledInJobError` in a job's thread: a job cancels itself with `Job.cancel`.
        """
        _check_main_thread("Jobs.cancel")
        for job in self._running:
            job.cancel()

    def drop(self) -> None:
        """Cancel every job running and forget it: its result won't be emitted.

        Reset all tasks, including completed ones, before emitting their ``changed``.
        Raises `CalledInJobError` in a job's thread.
        """
        _check_main_thread("Jobs.drop")
        self.cancel()
        was_running = self.is_running
        self._running.clear()
        tasks = tuple(self._tasks)
        for task in tasks:
            task._reset()  # noqa: SLF001 (reset all tasks before notifying their callbacks)
        if was_running:
            self.running_changed.emit(False)  # noqa: FBT003
        for task in tasks:
            task.changed.emit()

    def wait(self, timeout: float = 10.0) -> None:
        """Wait for every job to be over, and emit the results here: for a main view not rendered.

        Use it for a main view that no toolkit shows, e.g. in a test. Its jobs' results wait
        for this call, which emits them on its own thread, as a toolkit would on its main one.
        Raises `TimeoutError` if jobs are still running after `timeout` seconds.
        """
        main_view = self._main_view()
        if main_view is not None and main_view.renderer is not None:
            msg = "Jobs.wait is for a main view no toolkit shows: its event loop emits them"
            raise RuntimeError(msg)
        deadline = time.monotonic() + timeout
        while self.is_running:
            remaining = deadline - time.monotonic()
            try:
                emit = self._results.get(timeout=max(remaining, 0))
            except queue.Empty:
                msg = f"{len(self._running)} jobs still running after {timeout} s"
                raise TimeoutError(msg) from None
            emit()

    def _run(
        self,
        job: Job[R, ProgressT],
        work: Callable[..., R],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        """Run `work` in the job's thread, and hand its outcome to the main thread."""
        _CURRENT.job = job  # for the thread's life: a thread of its own per job
        try:
            result = work(job, *args, **kwargs)
        except (
            CalledInJobError,
            AssertionError,
            AttributeError,
            NameError,
            NotImplementedError,
            TypeError,
        ):
            self._on_main_thread(functools.partial(self._abort, job))
            raise
        except Exception as error:  # the app's code: whatever it raises, the job is over
            name = getattr(work, "__name__", "job")
            if isinstance(error, RefusedError):
                LOGGER.warning("The job %s was refused: %s", name, error)
            else:
                LOGGER.exception("The job %s failed", name)
            self._on_main_thread(functools.partial(self._end, job, job.failed, error))
        else:
            self._on_main_thread(functools.partial(self._end, job, job.finished, result))

    def _on_main_thread(self, callback: Callable[[], None]) -> None:
        main_view = self._main_view()
        if main_view is None:
            return  # the app is gone
        with self._results_lock:
            renderer = main_view.renderer if self._handed_over else None
            if renderer is None:
                self._results.put(callback)
                return
        # outside the lock: a web session's renderer takes the session's lock
        renderer.call_on_main_thread(callback)

    def hand_over_to(self, renderer: Renderer[Any, Any] | RendererContainer[Any]) -> None:
        """Hand the results queued before the main view was rendered to `renderer`, its own.

        In order, before any later one: a job started as the app is built, e.g. by
        `setup_model`, may be over before its main view is shown. `MainView.render` calls it.
        """
        while True:
            with self._results_lock:
                if self._results.empty():
                    self._handed_over = True
                    return
                callback = self._results.get()
            renderer.call_on_main_thread(callback)

    def _hand_over(self, job: Job[Any, Any], callback: Callable[[], None]) -> None:
        self._on_main_thread(functools.partial(self._call, job, callback))

    def _call(self, job: Job[Any, Any], callback: Callable[[], None]) -> None:
        """Call a job's `callback`, on the main thread; unless the job was dropped."""
        if job in self._running:
            callback()

    def _end(self, job: Job[Any, Any], signal: Signal[Any], outcome: object) -> None:
        """Emit the outcome of a job, on the main thread; unless it was dropped."""
        if job not in self._running:
            return
        self._running.discard(job)
        signal.emit(outcome)
        if not self.is_running:
            self.running_changed.emit(False)  # noqa: FBT003

    def _abort(self, job: Job[Any, Any]) -> None:
        """Clear a programming error's runtime state without emitting a business failure."""
        if job not in self._running:
            return
        self._running.discard(job)
        try:
            for task in self._tasks:
                if task._job is job:  # noqa: SLF001 (shared job lifecycle)
                    task._reset()  # noqa: SLF001 (shared job lifecycle)
                    task.changed.emit()
        finally:
            if not self.is_running:
                self.running_changed.emit(False)  # noqa: FBT003
