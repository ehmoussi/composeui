"""Data loaded once per process and shared by its sessions, read-only (see `shared_data`)."""

from __future__ import annotations

import copy
import enum
import functools
import inspect
import threading
from datetime import date, time, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Callable, Generic, NoReturn

import attrs
from narwhals.stable.v2 import dependencies
from typing_extensions import TypeVar, override

from composeui.core import jobs
from composeui.core.jobs import CalledInJobError, Job, JobCanceledError

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["SharedData", "SharedDataError", "shared_data"]

R = TypeVar("R")
ProgressT = TypeVar("ProgressT", default=None)

#: seconds between two looks of a waiting job at whether it was canceled
_POLL = 0.1


class SharedDataError(Exception):
    """A shared load returned a value that a session could change, so it isn't shared."""


class SharedData(Generic[R, ProgressT]):
    """A value loaded once per process, given to each session's job: see `shared_data`.

    Pass it to `Jobs.task` or `Jobs.start` as the job's function. The first job starts the
    load in a thread of its own, the jobs that come meanwhile wait for it, and later jobs
    get the value at once. Each job reports the load's progress. A job canceled stops
    waiting and raises `JobCanceledError`; the load stops once no job waits for it. A
    failed load is not kept: the next job loads again.
    """

    def __init__(self, load: Callable[[Job[R, ProgressT]], R]) -> None:
        parameters = [
            parameter
            for parameter in inspect.signature(load).parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}
        ]
        if len(parameters) != 1:
            # an argument could come from a session, and its data would be shared
            msg = (
                f"shared_data needs a function of its job alone, but {load!r} takes"
                f" {len(parameters)} arguments: put fixed values in the function instead"
            )
            raise TypeError(msg)
        functools.update_wrapper(self, load)
        #: the load's name, so a task of it is named after it
        self.__name__: str = getattr(load, "__name__", "shared_data")
        self._load = load
        self._condition = threading.Condition()
        # the run whose value is kept: None when none is loading
        self._run: _Run[R, ProgressT] | None = None
        self._has_value = False
        self._value: R | None = None
        self._share: Callable[[R], R] = _as_is

    def __call__(self, job: Job[R, ProgressT]) -> R:
        """Get the value, loaded once, as this session's own copy; in a job's thread."""
        with self._condition:
            if self._has_value:
                value, share = self._value, self._share
            else:
                run = self._run
                if run is None:
                    run = self._run = _Run(self)
                    run.start()
                run.waiters += 1
                return self._wait(job, run)
        return share(value)  # type: ignore[arg-type]  # None only while it isn't loaded

    def forget(self) -> None:
        """Drop the value, so that the next job loads it again, e.g. after its data changed.

        The sessions keep their copies. A load going on still gives its value to the jobs
        that wait for it, but the next job loads again.
        """
        with self._condition:
            self._run = None
            self._has_value = False
            self._value = None
            self._share = _as_is

    def _wait(self, job: Job[R, ProgressT], run: _Run[R, ProgressT]) -> R:
        """Wait for `run`'s outcome, under the condition, reporting its progress to `job`."""
        reported = 0
        # its last progress too: the load may end while the job reports the one before
        while not run.is_over or reported != run.reports:
            if reported != run.reports:
                reported, progress = run.reports, run.progress
                # outside the lock: on the web, a session's lock takes the progress
                self._condition.release()
                try:
                    job.report_progress(progress)  # type: ignore[arg-type]  # reported once
                finally:
                    self._condition.acquire()
            elif job.is_canceled:
                break
            else:
                self._condition.wait(_POLL)
        run.waiters -= 1
        if not run.is_over:  # canceled
            if run.waiters == 0:
                # nobody else waits: stop it, and the next job loads again
                run.job.cancel()
                if self._run is run:  # not one forgotten: the current run is another's
                    self._run = None
            msg = f"The job stopped waiting for {self.__name__}: it was canceled"
            raise JobCanceledError(msg)
        if run.error is not None:
            raise _own_copy(run.error)
        return run.share(run.value)  # type: ignore[arg-type]  # set when it didn't fail

    def _settle(self, run: _Run[R, ProgressT]) -> None:
        """Keep `run`'s value if it's still the current run, and wake its waiters."""
        with self._condition:
            run.is_over = True
            if self._run is run:
                self._run = None
                if run.error is None:
                    self._has_value = True
                    self._value = run.value
                    self._share = run.share
            self._condition.notify_all()


def shared_data(load: Callable[[Job[R, ProgressT]], R]) -> SharedData[R, ProgressT]:
    """Load `load`'s value once per process, and share it with every session, read-only.

    A decorator, e.g. of a function reading a large CSV, which each session's job then
    gets without reading it again. `load` takes only its job: its value can't depend on a
    session's input, which would share private data. The value is protected once loaded,
    or refused (`SharedDataError`) if a session could change it:

    - a Polars frame or series: each session gets a clone, which shares its columns;
    - a pandas frame or series, with pandas' copy-on-write on: a copy per session;
    - a NumPy array: read-only, with the arrays it's a view of, but not one over memory that
      can be written, e.g. a ``bytearray``;
    - a Polars lazy frame, a PyArrow table or chunked array: as it is;
    - an immutable value: a number, a string, a date, None, an enum member, or a tuple,
      frozenset or frozen attrs class of them.
    """
    return SharedData(load)


class _Run(Generic[R, ProgressT]):
    """A run of a shared load, in a thread of its own; its fields change under the condition."""

    def __init__(self, shared: SharedData[R, ProgressT]) -> None:
        self.shared = shared
        self.job: Job[R, ProgressT] = _LoadJob(self)
        #: the jobs waiting for it
        self.waiters = 0
        #: the last progress the load reported, and how many it reported
        self.progress: ProgressT | None = None
        self.reports = 0
        self.is_over = False
        self.value: R | None = None
        self.error: BaseException | None = None
        self.share: Callable[[R], R] = _as_is

    def start(self) -> None:
        # a daemon, as a job's: closing the app doesn't wait for it
        threading.Thread(target=self._load, daemon=True).start()

    def report(self, value: ProgressT) -> None:
        with self.shared._condition:  # noqa: SLF001 (its own run)
            self.progress = value
            self.reports += 1
            self.shared._condition.notify_all()  # noqa: SLF001 (its own run)

    def _load(self) -> None:
        # so the load can't start jobs, as a job's function
        jobs._CURRENT.job = self.job  # noqa: SLF001 (the load's thread runs a job too)
        try:
            value = self.shared._load(self.job)  # noqa: SLF001 (its own run)
            self.value, self.share = _sharer(value, self.shared.__name__)
        except BaseException as error:  # noqa: BLE001 (each waiter raises it in its own thread)
            self.error = error
        finally:
            # a canceled load's part isn't kept: its last waiter left, detaching it
            self.shared._settle(self)  # noqa: SLF001 (its own run)


class _LoadJob(Job[R, ProgressT]):
    """The job of a shared load: its progress goes to every job waiting for it."""

    def __init__(self, run: _Run[R, ProgressT]) -> None:
        super().__init__(_no_main_thread)
        self._run = run

    @override
    def report_progress(self, value: ProgressT) -> None:
        self._run.report(value)


def _own_copy(error: BaseException) -> BaseException:
    """Get a copy of `error` for one waiting job, its traceback continuing into the load's.

    Raised in each job's thread, one exception would gather the frames of every thread, and
    each session's task would keep the others' frames.
    """
    try:
        copied = copy.copy(error)
    except Exception:  # noqa: BLE001 (a class that can't be made again from its arguments)
        return error
    copied.__cause__, copied.__context__ = error.__cause__, error.__context__
    copied.__suppress_context__ = error.__suppress_context__
    return copied.with_traceback(error.__traceback__)


def _no_main_thread(_job: Job[Any, Any], _callback: Callable[[], None]) -> None:
    # several sessions wait for the load: there's no one main thread to call
    msg = "A shared load runs for every session: it can't call one's main thread"
    raise CalledInJobError(msg)


def _as_is(value: R) -> R:
    return value


def _sharer(value: R, name: str) -> tuple[R, Callable[[R], R]]:
    """Get the value to keep, and how each session gets it; refuse one it could change."""
    if dependencies.is_polars_dataframe(value) or dependencies.is_polars_series(value):
        import polars as pl  # noqa: PLC0415 (only when the value is one)

        dtypes = value.dtypes if dependencies.is_polars_dataframe(value) else [value.dtype]
        if any(dtype == pl.Object for dtype in dtypes):
            _refuse(name, "a Polars frame with a column of Python objects")
        return value, _clone  # shares the columns: a session's change stays in its clone
    if (
        dependencies.is_polars_lazyframe(value)
        or dependencies.is_pyarrow_table(value)
        or dependencies.is_pyarrow_chunked_array(value)
    ):
        return value, _as_is
    if dependencies.is_numpy_array(value):
        return _shared_array(value, name), _view
    if dependencies.is_pandas_dataframe(value) or dependencies.is_pandas_series(value):
        _check_pandas(value, name)
        return value, _shallow_copy
    _check_immutable([value], name)
    return value, _as_is


def _shared_array(array: Any, name: str) -> Any:
    """Make `array` read-only, to give each session a view of it, which can't be made writeable.

    Not a copy: the arrays it is a view of are made read-only too, the app's own included,
    and a memory-mapped file stays in its file.
    """
    if array.dtype.kind == "O":
        _check_immutable(array.ravel().tolist(), name)
    numpy = dependencies.get_numpy()
    base = array
    while isinstance(base, numpy.ndarray):
        base.flags.writeable = False
        base = base.base
    if _can_be_made_writeable(array):
        _refuse(
            name,
            "a NumPy array over memory that can be written, e.g. a bytearray or a file opened"
            " with mmap_mode='r+': return a copy, or a file opened with mmap_mode='r'",
        )
    return array


def _can_be_made_writeable(array: Any) -> bool:
    """Tell whether a view of `array` can be made writeable: its memory can be written."""
    try:
        array.view().flags.writeable = True
    except ValueError:
        return False
    return True


def _check_pandas(value: Any, name: str) -> None:
    """Refuse a pandas value that a session's shallow copy could change."""
    # not on pandas 3, which always copies on write: the tests of Python 3.11+ install it
    if not _copies_on_write():  # pragma: no cover
        _refuse(
            name,
            "a pandas frame without copy-on-write: turn it on"
            " (pd.options.mode.copy_on_write = True), or return a Polars or PyArrow frame",
        )
    frame = value.to_frame() if dependencies.is_pandas_series(value) else value
    # by position: a name can be that of several columns
    for position, dtype in enumerate(frame.dtypes):
        if dtype.kind == "O":
            # copy-on-write copies a column, not the objects in its cells
            _check_immutable(frame.iloc[:, position].tolist(), name)


def _clone(value: Any) -> Any:
    return value.clone()


def _view(value: Any) -> Any:
    return value.view()


def _shallow_copy(value: Any) -> Any:
    return value.copy(deep=False)


#: the first major version of pandas that always copies on write
_ALWAYS_COPIES_ON_WRITE = 3


def _copies_on_write() -> bool:
    """Tell whether pandas copies a frame's columns on write, so a shallow copy is safe."""
    import pandas as pd  # noqa: PLC0415 (only when the value is a pandas one)

    major = int(pd.__version__.split(".", maxsplit=1)[0])
    # pandas 3 always does, and reading the option warns there; the option doesn't exist
    # before pandas 1.5, and its "warn" keeps the old behavior
    return major >= _ALWAYS_COPIES_ON_WRITE or (
        getattr(pd.options.mode, "copy_on_write", False) is True
    )


@attrs.frozen
class _Frozen:
    """A frozen attrs class: frozen ones, subclasses included, share its `__setattr__`."""


_IMMUTABLE = (
    type(None),
    bool,
    int,
    float,
    complex,
    str,
    bytes,
    Decimal,
    Fraction,
    date,  # a datetime too
    time,
    timedelta,
    range,
    enum.Enum,
)


def _check_immutable(values: Iterable[object], name: str) -> None:
    """Raise `SharedDataError` unless every value, and all it holds, is immutable."""
    pending = list(values)
    while pending:
        value = pending.pop()
        if isinstance(value, _IMMUTABLE) or _is_numpy_scalar(value):
            continue
        if isinstance(value, (tuple, frozenset)):
            pending.extend(value)
        elif attrs.has(cls := type(value)) and cls.__setattr__ is _Frozen.__setattr__:
            pending.extend(getattr(value, field.name) for field in attrs.fields(cls))
        else:
            _refuse(name, f"a {type(value).__name__}")


def _is_numpy_scalar(value: object) -> bool:
    numpy = dependencies.get_numpy()
    return numpy is not None and isinstance(value, numpy.generic)


def _refuse(name: str, what: str) -> NoReturn:
    msg = (
        f"shared_data {name} returned {what}, which a session could change: return a"
        " Polars or PyArrow frame, a NumPy array, or immutable values (a tuple or a frozen"
        " attrs class of them)"
    )
    raise SharedDataError(msg)
