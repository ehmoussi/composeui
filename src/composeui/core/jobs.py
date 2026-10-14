"""Work run in threads, its results given back on the main thread (see `Jobs`)."""

from __future__ import annotations

import functools
import logging
import queue
import threading
import time
import weakref
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar

from typing_extensions import Concatenate, ParamSpec

from composeui.core.signal import Signal

if TYPE_CHECKING:
    from composeui.core.model import Model
    from composeui.core.view import MainView

LOGGER = logging.getLogger("COMPOSEUI")

R = TypeVar("R")
P = ParamSpec("P")


class Job(Generic[R]):
    """A function running in a thread of its own, started by `Jobs.start`.

    The function gets its job first: it calls `sleep`, or reads `is_canceled`, to stop
    early once canceled. Its result, or what it raised, is emitted on the main thread.
    """

    def __init__(self) -> None:
        #: the function's return value, on the main thread
        self.finished = Signal[R]()
        #: what the function raised, on the main thread (logged too)
        self.failed = Signal[Exception]()
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


class Jobs:
    """The jobs of a main view (`MainView.jobs`): functions run in threads.

    A job's function runs in a thread, so that the app stays responsive, and must not
    touch a view: a toolkit's widgets belong to the main thread. It returns its result
    instead, which its job's `finished` emits on the main thread, where callbacks update
    the views. Connected like any signal's, they get the `main_view` and `model` they ask
    for.

    New, Open and closing the app cancel the jobs running, and drop their results: they
    belong to the study replaced.
    """

    def __init__(self, main_view: MainView) -> None:
        self._main_view = weakref.ref(main_view)
        self._model: weakref.ReferenceType[Model] | None = None
        #: True as the first job starts, False once the last one is over
        self.running_changed = Signal[bool]()
        self.running_changed.set_main_view(main_view)
        # the jobs started and not over yet: only changed on the main thread
        self._running: set[Job[Any]] = set()
        # the results handed back while the main view isn't rendered, for `wait`
        self._results: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()

    @property
    def is_running(self) -> bool:
        return len(self._running) > 0

    def set_model(self, model: Model) -> None:
        """Give `model` to the callbacks asking for it (the app does)."""
        self._model = weakref.ref(model)
        self.running_changed.set_model(model)

    def start(
        self, work: Callable[Concatenate[Job[R], P], R], *args: P.args, **kwargs: P.kwargs
    ) -> Job[R]:
        """Run `work(job, *args, **kwargs)` in a thread; call it on the main thread.

        Connect to the job's signals right away: its outcome is emitted on the main
        thread, so no sooner than the code calling `start` is done.
        """
        job: Job[R] = Job()
        name = getattr(work, "__name__", "job")
        main_view = self._main_view()
        model = None if self._model is None else self._model()
        for signal_name, signal in (("finished", job.finished), ("failed", job.failed)):
            signal.set_name(f"{name}.{signal_name}")
            if main_view is not None:
                signal.set_main_view(main_view)
            if model is not None:
                signal.set_model(model)
        self._running.add(job)
        if len(self._running) == 1:
            self.running_changed.emit(True)  # noqa: FBT003
        # a daemon: closing the app doesn't wait for it
        thread = threading.Thread(target=self._run, args=(job, work, args, kwargs), daemon=True)
        thread.start()
        return job

    def cancel(self) -> None:
        """Cancel every job running; each still finishes, as soon as it notices."""
        for job in self._running:
            job.cancel()

    def drop(self) -> None:
        """Cancel every job running and forget it: its result won't be emitted."""
        self.cancel()
        was_running = self.is_running
        self._running.clear()
        if was_running:
            self.running_changed.emit(False)  # noqa: FBT003

    def wait(self, timeout: float = 10.0) -> None:
        """Wait for every job to be over, emitting the results here; not rendered only.

        For a main view no toolkit shows, e.g. in a test: its jobs' results wait for
        this call, which emits them on its thread, as a toolkit would on its main one.
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
        job: Job[R],
        work: Callable[..., R],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        """Run `work` in the job's thread, and hand its outcome to the main thread."""
        try:
            result = work(job, *args, **kwargs)
        except Exception as error:  # the app's code: whatever it raises, the job is over
            LOGGER.exception("The job %s failed", getattr(work, "__name__", "job"))
            self._on_main_thread(functools.partial(self._end, job, job.failed, error))
        else:
            self._on_main_thread(functools.partial(self._end, job, job.finished, result))

    def _on_main_thread(self, callback: Callable[[], None]) -> None:
        main_view = self._main_view()
        if main_view is None:
            return  # the app is gone
        if main_view.renderer is None:
            self._results.put(callback)
        else:
            main_view.renderer.call_on_main_thread(callback)

    def _end(self, job: Job[Any], signal: Signal[Any], outcome: object) -> None:
        """Emit the outcome of a job, on the main thread; unless it was dropped."""
        if job not in self._running:
            return
        self._running.discard(job)
        signal.emit(outcome)
        if not self.is_running:
            self.running_changed.emit(False)  # noqa: FBT003
