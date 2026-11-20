"""Tests of `Job.run_process`: a process run by a job, its output, and how it stops."""

from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Callable

import pytest

from composeui.core.jobs import JobCanceledError
from composeui.core.view import MainView

if TYPE_CHECKING:
    from pathlib import Path

    from composeui.core.jobs import Job

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="Windows has no session to stop")

#: prints its process id, then sleeps
_WAITS = "import os, time; print(f'pid={os.getpid()}', flush=True); time.sleep(60)"
#: the same, its process id written on the errors
_WAITS_ON_ERRORS = (
    "import os, sys, time; sys.stderr.write(f'pid={os.getpid()}\\n'); sys.stderr.flush();"
    " time.sleep(60)"
)


def _outcome(work: Callable[[Job[int]], int]) -> int | Exception:
    """Run `work` as a job; get what it returned, or the exception it failed with."""
    main_view = MainView()
    outcome: list[int | Exception] = []
    job = main_view.jobs.start(work)
    job.finished.connect(outcome.append)
    job.failed.connect(outcome.append)
    main_view.jobs.wait(timeout=20)
    (value,) = outcome
    return value


def _pid(text: str) -> int:
    found = re.search(r"pid=(\d+)", text)
    assert found is not None, text
    return int(found.group(1))


def _is_running(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes  # noqa: PLC0415 (Windows only)

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # noqa: FBT003 (SYNCHRONIZE)
        if not handle:
            return False
        try:
            return bool(kernel32.WaitForSingleObject(handle, 0) == 0x102)  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _ends(pid: int) -> bool:
    """Tell whether process `pid` ends soon, once stopped.

    A stopped orphan waits for its new parent's reaping. On Windows, a virtual environment's
    Python is a launcher: the Python it started ends once the launcher is killed, not at once.
    """
    deadline = time.monotonic() + 10
    while _is_running(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def _kill_left(pid: int) -> None:
    """Kill process `pid` if a failed test left it running."""
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGTERM)


def test_a_process_s_output_and_errors_reach_on_output_and_its_exit_code_is_returned() -> None:
    output: list[str] = []
    script = "import sys; print('Step 1', flush=True); sys.stderr.write('warning\\n'); sys.exit(3)"

    def work(job: Job[int]) -> int:
        return job.run_process([sys.executable, "-c", script], on_output=output.append)

    assert _outcome(work) == 3
    assert "".join(output).replace("\r\n", "\n") == "Step 1\nwarning\n"


def test_with_on_errors_the_errors_go_apart_from_the_output() -> None:
    # e.g. a program that writes its results as data, and its warnings
    script = (
        "import sys\n"
        "print('x,y', flush=True)\n"
        "sys.stderr.write('warning\\n'); sys.stderr.flush()\n"
        "print('1,2', flush=True)\n"
    )
    output: list[str] = []
    errors: list[str] = []

    def work(job: Job[int]) -> int:
        command = [sys.executable, "-c", script]
        return job.run_process(command, on_output=output.append, on_errors=errors.append)

    assert _outcome(work) == 0
    assert "".join(output).replace("\r\n", "\n") == "x,y\n1,2\n"
    assert "".join(errors).replace("\r\n", "\n") == "warning\n"


def test_a_character_whose_bytes_come_in_two_reads_reaches_on_output_whole(
    tmp_path: Path,
) -> None:
    # the process writes the last byte of "é" only once on_output got the text before it
    first_part = tmp_path / "first-part"
    script = (
        "import pathlib, sys, time\n"
        "sys.stdout.buffer.write(b'caf\\xc3'); sys.stdout.flush()\n"
        "deadline = time.monotonic() + 20\n"
        "while not pathlib.Path(sys.argv[1]).exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "sys.stdout.buffer.write(b'\\xa9\\n')\n"
    )
    output: list[str] = []

    def on_output(text: str) -> None:
        output.append(text)
        if "caf" in "".join(output):
            first_part.touch()

    def work(job: Job[int]) -> int:
        command = [sys.executable, "-c", script, str(first_part)]
        return job.run_process(command, on_output=on_output)

    assert _outcome(work) == 0
    assert "".join(output).replace("\r\n", "\n") == "café\n"


@pytest.mark.parametrize(
    ("encoding", "text"),
    [("utf-8", "caf\ufffd\n"), ("cp1252", "caf\u00e9\n")],
    ids=["a byte UTF-8 can't decode", "the encoding of the program"],
)
def test_the_output_is_decoded_from_the_encoding_given(encoding: str, text: str) -> None:
    script = "import sys; sys.stdout.buffer.write(b'caf\\xe9\\n')"  # "café" in cp1252
    output: list[str] = []

    def work(job: Job[int]) -> int:
        command = [sys.executable, "-c", script]
        return job.run_process(command, on_output=output.append, encoding=encoding)

    assert _outcome(work) == 0
    assert "".join(output) == text


def test_an_unknown_encoding_starts_nothing() -> None:
    def work(job: Job[int]) -> int:
        # a program that doesn't exist: starting it would raise `FileNotFoundError`
        return job.run_process(["composeui-no-such-program"], encoding="no-such-encoding")

    assert isinstance(_outcome(work), LookupError)


@pytest.mark.parametrize(
    ("stop", "error"),
    [("cancel", JobCanceledError), ("raise", ValueError), ("raise errors", ValueError)],
    ids=["the job canceled", "on_output raising", "on_errors raising"],
)
def test_a_process_is_stopped_when_its_job_stops(stop: str, error: type[Exception]) -> None:
    output: list[str] = []

    def work(job: Job[int]) -> int:
        def on_text(text: str) -> None:
            output.append(text)
            if "pid=" in "".join(output):
                if stop == "cancel":
                    job.cancel()
                else:
                    raise ValueError(stop)

        if stop == "raise errors":
            command = [sys.executable, "-c", _WAITS_ON_ERRORS]
            return job.run_process(command, on_errors=on_text)
        return job.run_process([sys.executable, "-c", _WAITS], on_output=on_text)

    assert isinstance(_outcome(work), error)
    pid = _pid("".join(output))
    try:
        assert _ends(pid)
    finally:
        _kill_left(pid)


def test_a_process_running_past_its_timeout_is_stopped() -> None:
    def work(job: Job[int]) -> int:
        return job.run_process([sys.executable, "-c", _WAITS], timeout=0.5)

    # it would sleep 60 s: `_outcome` waits 20 s at most
    assert isinstance(_outcome(work), subprocess.TimeoutExpired)


def test_a_job_canceled_before_its_process_starts_doesn_t_start_it() -> None:
    def work(job: Job[int]) -> int:
        job.cancel()
        # a program that doesn't exist: starting it would raise `FileNotFoundError`
        return job.run_process(["composeui-no-such-program"])

    assert isinstance(_outcome(work), JobCanceledError)


def test_a_process_left_holding_the_output_doesn_t_hold_the_job() -> None:
    # a process in a session of its own: no stop reaches it, on any platform
    script = (
        "import subprocess, sys\n"
        "left = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],"
        " start_new_session=True)\n"
        "print(f'pid={left.pid}', flush=True)\n"
    )
    output: list[str] = []

    def work(job: Job[int]) -> int:
        return job.run_process([sys.executable, "-c", script], on_output=output.append)

    # it holds the output for 60 s: `_outcome` waits 20 s at most
    assert _outcome(work) == 0
    _kill_left(_pid("".join(output)))


def test_a_process_still_running_when_python_exits_is_stopped() -> None:
    # an app that exits while its job runs a process: the job's thread doesn't stop it
    app = (
        "import sys, threading\n"
        "from composeui.core.view import MainView\n"
        "started = threading.Event()\n"
        "def show(text):\n"
        "    print(text, end='', flush=True)\n"
        "    started.set()\n"
        "def work(job):\n"
        f"    return job.run_process([sys.executable, '-c', {_WAITS!r}], on_output=show)\n"
        "MainView().jobs.start(work)\n"
        "assert started.wait(20)\n"
    )
    command = [sys.executable, "-c", app]
    done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)  # noqa: S603
    pid = _pid(done.stdout)
    try:
        assert done.returncode == 0, done.stderr
        assert _ends(pid)
    finally:
        _kill_left(pid)


@posix_only
def test_a_process_s_children_left_when_it_exits_are_stopped() -> None:
    script = (
        "import subprocess, sys\n"
        "left = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(f'pid={left.pid}', flush=True)\n"
    )
    output: list[str] = []

    def work(job: Job[int]) -> int:
        return job.run_process([sys.executable, "-c", script], on_output=output.append)

    assert _outcome(work) == 0
    pid = _pid("".join(output))
    try:
        assert _ends(pid)
    finally:
        _kill_left(pid)


@posix_only
def test_a_process_stopping_on_sigterm_gets_its_last_output_to_on_output() -> None:
    script = (
        "import os, signal, sys, time\n"
        "def save(*_):\n"
        # not `print`: SIGTERM can come while the print of 'ready' still flushes
        "    os.write(sys.stdout.fileno(), b'saved\\n')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, save)\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n"
    )
    output: list[str] = []

    def work(job: Job[int]) -> int:
        def on_output(text: str) -> None:
            output.append(text)
            if "ready" in "".join(output):
                job.cancel()

        return job.run_process([sys.executable, "-c", script], on_output=on_output)

    assert isinstance(_outcome(work), JobCanceledError)
    assert "".join(output) == "ready\nsaved\n"


@posix_only
def test_a_child_ignoring_sigterm_is_killed_after_the_grace_time() -> None:
    ignoring = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print(f'pid={os.getpid()}', flush=True)\n"
        "time.sleep(60)\n"
    )
    script = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {ignoring!r}])\n"
        "time.sleep(60)\n"
    )
    output: list[str] = []

    def work(job: Job[int]) -> int:
        def on_output(text: str) -> None:
            output.append(text)
            if "pid=" in "".join(output):
                job.cancel()

        command = [sys.executable, "-c", script]
        return job.run_process(command, on_output=on_output, grace=1.0)

    assert isinstance(_outcome(work), JobCanceledError)
    pid = _pid("".join(output))
    try:
        assert _ends(pid)
    finally:
        _kill_left(pid)
