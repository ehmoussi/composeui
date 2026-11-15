"""Shared data: one load for every job that asks, its value protected from their changes."""

from __future__ import annotations

import contextlib
import importlib.metadata
import threading
import traceback
from typing import TYPE_CHECKING, Any, Callable, cast

import attrs
import pytest

from composeui.core.jobs import CalledInJobError, Job, JobCanceledError
from composeui.core.shared import SharedData, SharedDataError, shared_data
from composeui.core.view import MapPoint

if TYPE_CHECKING:
    from pathlib import Path

pl = pytest.importorskip("polars")

#: seconds a test waits for a thread before it fails
_TIMEOUT = 10


def _pandas_major() -> int:
    try:
        return int(importlib.metadata.version("pandas").split(".")[0])
    except importlib.metadata.PackageNotFoundError:
        return 0


#: pandas 3 always copies on write, and reading its option warns
_ALWAYS_COPIES_ON_WRITE = _pandas_major() >= 3


class _Session:
    """A session's job asking for shared data in a thread, as a session's `Jobs` does."""

    def __init__(self, shared: SharedData[Any, Any]) -> None:
        # the progress callbacks run in the job's thread, as on the web
        self.job: Job[Any, Any] = Job(lambda _job, callback: callback())
        self.progress: list[object] = []
        self.joined = threading.Event()
        self.job.progress.connect(self._report)
        self.outcome: object = None
        self._thread = threading.Thread(target=self._run, args=(shared,), daemon=True)
        self._thread.start()

    def _report(self, value: object) -> None:
        self.progress.append(value)
        self.joined.set()

    def _run(self, shared: SharedData[Any, Any]) -> None:
        try:
            self.outcome = shared(self.job)
        except Exception as error:  # noqa: BLE001 (the test reads it)
            self.outcome = error

    def result(self) -> Any:
        self._thread.join(_TIMEOUT)
        assert not self._thread.is_alive()
        return self.outcome


class _Gated:
    """A load that reports its first progress, then waits until the test opens its gate.

    Canceled, it returns a part, as a real load would: never its value, which another run
    of it may be taking at the same time.
    """

    def __init__(self, value: Callable[[], object]) -> None:
        self.value = value
        self.gate = threading.Event()
        self.calls = 0
        self.canceled: list[bool] = []
        # two runs can go on at once; a canceled one ends after its session stopped waiting
        self._ended = threading.Condition()

    def __call__(self, job: Job[Any, Any]) -> object:
        with self._ended:
            self.calls += 1
            call = self.calls
        job.report_progress(call)
        # until the gate opens, or every session stops waiting
        while not self.gate.wait(0.01) and not job.is_canceled:
            pass
        with self._ended:
            self.canceled.append(job.is_canceled)
            self._ended.notify_all()
        return ("part",) if job.is_canceled else self.value()

    def wait_until_ended(self, runs: int) -> None:
        """Wait until that many runs have ended."""
        with self._ended:
            assert self._ended.wait_for(lambda: len(self.canceled) == runs, _TIMEOUT)


def _joined(*sessions: _Session) -> None:
    """Wait until each session waits for the load: it got the load's progress."""
    for session in sessions:
        assert session.joined.wait(_TIMEOUT)


def test_sessions_waiting_together_share_one_load_each_with_its_own_clone() -> None:
    load = _Gated(lambda: pl.DataFrame({"a": [1, 2, 3]}))
    pickups = shared_data(load)
    sessions = [_Session(pickups) for _ in range(4)]
    _joined(*sessions)  # the last one joined after the progress: it gets it as it joins
    load.gate.set()
    frames = [session.result() for session in sessions]

    assert load.calls == 1
    assert [session.progress for session in sessions] == [[1]] * 4
    frames[0].insert_column(1, pl.Series("b", [0, 0, 0]))
    assert [frame.columns for frame in frames] == [["a", "b"], *[["a"]] * 3]
    # a session after the load gets the value at once: the one before any change
    later = _Session(pickups)
    assert later.result().columns == ["a"]
    assert later.progress == []
    assert load.calls == 1


def test_a_session_canceled_stops_waiting_and_the_others_still_get_the_load() -> None:
    load = _Gated(lambda: (1, 2))
    shared = shared_data(load)
    canceled, waiting = _Session(shared), _Session(shared)
    _joined(canceled, waiting)

    canceled.job.cancel()

    assert isinstance(canceled.result(), JobCanceledError)
    load.gate.set()
    assert waiting.result() == (1, 2)
    assert load.canceled == [False]


def test_the_load_stops_when_its_last_session_cancels_and_the_next_one_loads_again() -> None:
    load = _Gated(lambda: ("all",))
    shared = shared_data(load)
    session = _Session(shared)
    _joined(session)

    session.job.cancel()
    assert isinstance(session.result(), JobCanceledError)

    # the canceled load's part isn't kept: the next session loads it all
    load.gate.set()
    assert _Session(shared).result() == ("all",)
    assert load.calls == 2
    load.wait_until_ended(2)  # the canceled one ends when it notices, maybe after the other
    assert sorted(load.canceled) == [False, True]


def test_a_failed_load_is_not_kept_and_the_next_session_loads_again() -> None:
    outcomes: list[Callable[[], int]] = [lambda: 1, _raise_os_error]

    @shared_data
    def load(_job: Job[int]) -> int:
        return outcomes.pop()()

    failed = _Session(load).result()
    assert isinstance(failed, OSError)
    assert _Session(load).result() == 1


def _raise_os_error() -> int:
    msg = "unreachable"
    raise OSError(msg)


def test_sessions_waiting_for_a_failed_load_each_get_their_own_exception() -> None:
    load = _Gated(_raise_os_error)
    shared = shared_data(load)
    sessions = [_Session(shared) for _ in range(3)]
    _joined(*sessions)
    load.gate.set()

    errors = [session.result() for session in sessions]
    assert [type(error) for error in errors] == [OSError] * 3
    assert [str(error) for error in errors] == ["unreachable"] * 3
    # one object raised in each thread would gather every session's frames
    assert len({id(error) for error in errors}) == 3
    for error in errors:
        frames = traceback.extract_tb(error.__traceback__)
        assert [frame.name for frame in frames].count("_run") == 1  # its own session's
        assert frames[-1].name == "_raise_os_error"  # then the load's


class _KeywordError(Exception):
    """An exception that can't be made again from its arguments, so can't be copied."""

    def __init__(self, *, reason: str) -> None:
        super().__init__(f"failed: {reason}")


def test_an_exception_that_can_t_be_copied_still_reaches_the_session() -> None:
    error = _KeywordError(reason="no luck")

    @shared_data
    def load(_job: Job[int]) -> int:
        raise error

    assert _Session(load).result() is error


def test_forget_makes_the_next_session_load_again_and_keeps_the_copies_given() -> None:
    values = iter([pl.DataFrame({"a": [1]}), pl.DataFrame({"a": [2]})])

    @shared_data
    def load(_job: Job[Any]) -> Any:
        return next(values)

    before = _Session(load).result()
    load.forget()

    assert _Session(load).result().item() == 2
    assert before.item() == 1


def test_a_load_going_on_when_forgotten_gives_its_waiters_its_value_but_not_later_ones() -> None:
    values = iter([("old",), ("new",)])
    load = _Gated(lambda: next(values))
    shared = shared_data(load)
    waiting = _Session(shared)
    _joined(waiting)

    shared.forget()
    load.gate.set()

    assert waiting.result() == ("old",)
    assert _Session(shared).result() == ("new",)


def test_a_forgotten_load_canceled_leaves_the_load_that_replaced_it() -> None:
    load = _Gated(lambda: ("value",))
    shared = shared_data(load)
    forgotten = _Session(shared)
    _joined(forgotten)
    shared.forget()
    waiting = _Session(shared)
    _joined(waiting)

    forgotten.job.cancel()
    assert isinstance(forgotten.result(), JobCanceledError)
    load.gate.set()

    assert waiting.result() == ("value",)
    assert _Session(shared).result() == ("value",)
    assert load.calls == 2
    load.wait_until_ended(2)  # the canceled one ends when it notices, maybe after the other
    assert sorted(load.canceled) == [False, True]


def test_a_shared_load_can_t_call_a_session_s_main_thread() -> None:
    @shared_data
    def load(job: Job[int]) -> int:
        job.call_on_main_thread(lambda: None)
        return 1

    assert isinstance(_Session(load).result(), CalledInJobError)


def test_a_function_taking_more_than_its_job_can_t_be_shared() -> None:
    def load(_job: Job[str], url: str) -> str:
        return url

    with pytest.raises(TypeError, match="fixed values"):
        shared_data(cast("Any", load))  # a type checker refuses it too


@attrs.define
class _Mutable:
    value: int


def _polars_objects() -> object:
    return pl.DataFrame({"a": [object()]}, schema={"a": pl.Object})


def _numpy_lists() -> object:
    numpy = pytest.importorskip("numpy")
    array = numpy.empty(1, dtype=object)
    array[0] = [1]
    return array


def _numpy_over_a_bytearray() -> object:
    numpy = pytest.importorskip("numpy")
    return numpy.frombuffer(bytearray(8), dtype="int64")


def _pandas_without_copy_on_write() -> object:
    pd = pytest.importorskip("pandas")
    return pd.DataFrame({"a": [1]})


@pytest.mark.parametrize(
    "value",
    [
        lambda: [1],
        lambda: {"a": 1},
        lambda: (1, [2]),
        lambda: _Mutable(1),
        _polars_objects,
        _numpy_lists,
        _numpy_over_a_bytearray,
        pytest.param(
            _pandas_without_copy_on_write,
            marks=pytest.mark.skipif(_ALWAYS_COPIES_ON_WRITE, reason="pandas 3 always copies"),
        ),
    ],
    ids=[
        "list",
        "dict",
        "tuple-of-list",
        "mutable-attrs",
        "polars-objects",
        "numpy-lists",
        "numpy-bytearray",
        "pandas",
    ],
)
def test_a_value_a_session_could_change_is_refused(value: Callable[[], object]) -> None:
    made = value()  # here: a skip in the load's thread would fail the load instead
    shared = shared_data(lambda _job: made)

    assert isinstance(_Session(shared).result(), SharedDataError)


def _numpy_scalars() -> object:
    numpy = pytest.importorskip("numpy")
    return (numpy.int64(1), numpy.bool_(True))  # noqa: FBT003 (a value)


def _pyarrow_table() -> object:
    pa = pytest.importorskip("pyarrow")
    return pa.table({"a": [1]})


@pytest.mark.parametrize(
    "value",
    [
        lambda: (None, "a", b"b", 1.5, frozenset({MapPoint(latitude=1, longitude=2)})),
        lambda: pl.LazyFrame({"a": [1]}),
        _numpy_scalars,
        _pyarrow_table,
    ],
    ids=["immutable", "polars-lazy", "numpy-scalars", "pyarrow"],
)
def test_values_no_session_can_change_are_shared_as_they_are(value: Callable[[], object]) -> None:
    made = value()
    shared = shared_data(lambda _job: made)

    assert _Session(shared).result() is _Session(shared).result()


@pytest.mark.parametrize("shape", [(6,), (2, 3)], ids=["its-own-data", "a-view-of-another"])
def test_a_numpy_array_is_shared_read_only(shape: tuple[int, ...]) -> None:
    numpy = pytest.importorskip("numpy")
    owner = numpy.arange(6)
    # a reshape is a view of the app's array: making it writeable again would write there
    shared = shared_data(lambda _job: owner.reshape(shape) if len(shape) > 1 else owner)
    array = _Session(shared).result()

    with pytest.raises(ValueError, match="read-only"):
        array.flat[0] = 9
    with pytest.raises(ValueError, match="WRITEABLE"):
        array.flags.writeable = True
    # shared without a copy: the app's own array is read-only too
    with pytest.raises(ValueError, match="read-only"):
        owner[0] = 9


def test_a_memory_mapped_array_is_shared_from_its_file(tmp_path: Path) -> None:
    numpy = pytest.importorskip("numpy")
    numpy.save(tmp_path / "values.npy", numpy.arange(6))
    mapped = numpy.load(tmp_path / "values.npy", mmap_mode="r")
    shared = shared_data(lambda _job: mapped[::2])

    array = _Session(shared).result()

    assert array.tolist() == [0, 2, 4]
    assert numpy.shares_memory(array, mapped)  # not copied into memory


def _copy_on_write() -> contextlib.AbstractContextManager[object]:
    """Turn pandas' copy-on-write on: always on from pandas 3, where the option warns."""
    pd = pytest.importorskip("pandas")
    if _ALWAYS_COPIES_ON_WRITE:
        return contextlib.nullcontext()
    return pd.option_context("mode.copy_on_write", True)  # noqa: FBT003 (pandas' API)


def test_a_pandas_frame_with_copy_on_write_is_a_copy_per_session() -> None:
    pd = pytest.importorskip("pandas")
    with _copy_on_write():
        shared = shared_data(lambda _job: pd.DataFrame({"a": [3, 1, 2], "s": ["x", "y", "z"]}))
        first = _Session(shared).result()
        first["a"] = [9, 9, 9]
        first.loc[0, "s"] = "changed"

        assert _Session(shared).result().to_dict("list") == {
            "a": [3, 1, 2],
            "s": ["x", "y", "z"],
        }


def test_a_pandas_frame_holding_lists_is_refused_even_with_copy_on_write() -> None:
    pd = pytest.importorskip("pandas")
    with _copy_on_write():
        # two columns of one name: each is checked
        frame = pd.DataFrame([[1, [1]]], columns=["a", "a"])
        shared = shared_data(lambda _job: frame)

        assert isinstance(_Session(shared).result(), SharedDataError)
