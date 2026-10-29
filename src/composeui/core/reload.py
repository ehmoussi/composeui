"""``--reload`` for a desktop app: a supervisor runs the program in a child process.

On a change, the supervisor sends the app the files changed. The app saves its views'
state and its model's data (a study), runs the program's changed code again in place
(`rerun_program`), and opens the study in the new app, so its window stays as it was left.
When the app can't, e.g. ComposeUI itself changed, it exits instead, and the supervisor
runs the program again in a new child process, which opens the study.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import logging
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time
import types
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any

from composeui.core.model import InvalidStateError
from composeui.core.study import open_study, save_study

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Sequence
    from types import FrameType

    from composeui.core.model import Model
    from composeui.core.view import MainView

__all__ = [
    "acknowledge_changes",
    "can_reload_in_place",
    "has_change_events",
    "is_reloaded",
    "keep_rerun",
    "load_reloaded_state",
    "program_command",
    "rerun_program",
    "run_reloading",
    "save_reloaded_state",
    "take_changes",
    "watch_changes",
]

LOGGER = logging.getLogger("COMPOSEUI")

#: environment variable set in the child process, so it runs the app, not another
#: supervisor: the directory where the runs leave their state to the next
RELOADED_VARIABLE = "COMPOSEUI_RELOADED"
#: the files of that directory: the last study saved; what the study doesn't hold, its
#: file's path and the language shown (JSON); the files changed, one per line, which the
#: app renames once it takes them, and removes once it runs their code
_STUDY_NAME = "study"
_SESSION_NAME = "session.json"
_CHANGES_NAME = "changes"
_TAKEN_NAME = "taken"
#: seconds a running app has to take the files changed, or to exit, before it is
#: terminated; once taken, running their code may take as long as it does
_RELOAD_TIMEOUT = 5.0
#: seconds a terminated app has to exit before it is killed
_STOP_TIMEOUT = 5.0
#: ComposeUI's own package: its code is never imported again in a running app
_COMPOSEUI_DIRECTORY = Path(__file__).resolve().parent.parent
#: set while `rerun_program` runs the program: the apps it ran, unrun
_RERUNS: ContextVar[list[Any] | None] = ContextVar("composeui_reruns", default=None)
#: seconds between two looks at the files, and at whether the app has exited
_STEP = 0.5
#: seconds a change is let settle before its files are read: a save can be reported as it
#: is written, e.g. once the file is truncated, which the app wouldn't run
_SETTLE = 0.1
#: directories never watched: tools' caches and environments, not the app's code
_IGNORED_DIRECTORIES = frozenset({"__pycache__", "node_modules", "site-packages"})


def is_reloaded() -> bool:
    """Tell whether this process is the app a ``--reload`` supervisor runs."""
    return RELOADED_VARIABLE in os.environ


def _state_directory() -> Path:
    return Path(os.environ[RELOADED_VARIABLE])


def take_changes() -> list[Path] | None:
    """Take the files changed, if the supervisor asks the app to run their code.

    Taken, they tell the supervisor to wait for the app, until `acknowledge_changes`.
    """
    directory = _state_directory()
    try:
        (directory / _CHANGES_NAME).replace(directory / _TAKEN_NAME)
    except FileNotFoundError:
        return None
    text = (directory / _TAKEN_NAME).read_text()
    return [Path(line) for line in text.splitlines()]


def acknowledge_changes() -> None:
    """Tell the supervisor the app runs the changed code, so it keeps the app running."""
    (_state_directory() / _TAKEN_NAME).unlink(missing_ok=True)


def can_reload_in_place(changed: Sequence[Path]) -> bool:
    """Tell whether the app can run the code of the files `changed` without a new process.

    Not when ComposeUI's own code changed: the running app's objects keep its old classes.
    """
    return not any(_COMPOSEUI_DIRECTORY in path.resolve().parents for path in changed)


class _AppKept(BaseException):  # not an error: the program's end
    """Ends the program `rerun_program` runs, at the app's ``run``, which it keeps."""


def keep_rerun(run: object) -> None:
    """Keep `run`, an app ready to run, if `rerun_program` runs the program, and end it.

    An app's ``run`` calls it before it runs. The program ends there, as when the app
    runs, so the code after ``run`` doesn't run on a reload either.
    """
    reruns = _RERUNS.get()
    if reruns is not None:
        reruns.append(run)
        # not an `Exception`, which the program might catch
        raise _AppKept


def _is_program_module(module: object) -> bool:
    """Tell whether `module` is the program's own code: under the directory, not ComposeUI's."""
    file = getattr(module, "__file__", None)
    if file is None:
        return False
    path = Path(file).resolve()
    return _is_program_file(path, Path.cwd().resolve()) and _COMPOSEUI_DIRECTORY not in path.parents


def rerun_program() -> Any:
    """Run the program again in this process, its code imported afresh; return its app.

    The modules of its code (`_is_program_module`) are imported again. The app the
    program runs is kept, unrun (`keep_rerun`). On an error, e.g. a syntax error, or
    when no app is kept, the program's previous modules come back and the error is raised.
    """
    previous = {
        name: module
        for name, module in sys.modules.items()
        if name == "__main__" or _is_program_module(module)
    }
    main = previous["__main__"]
    for name in previous:
        del sys.modules[name]
    reruns: list[Any] = []
    token = _RERUNS.set(reruns)
    # an empty cache of compiled code: Python checks a module's by its source's size and
    # modification time in seconds, so an edit keeping the size within that second would
    # run the previous code
    pycache_prefix = sys.pycache_prefix
    importlib.invalidate_caches()  # the directories' listings, e.g. for a new module
    try:
        with tempfile.TemporaryDirectory(prefix="composeui-pycache-") as cache:
            sys.pycache_prefix = cache
            _run_as_main(main)
    except _AppKept:
        pass
    except SystemExit as error:
        sys.modules.update(previous)
        msg = "the program exited instead of running an app"
        raise RuntimeError(msg) from error
    except BaseException:
        sys.modules.update(previous)
        raise
    finally:
        sys.pycache_prefix = pycache_prefix
        _RERUNS.reset(token)
    if len(reruns) == 0:
        sys.modules.update(previous)
        msg = "the program didn't run an app"
        raise RuntimeError(msg)
    return reruns[0]


def _run_as_main(previous_main: types.ModuleType) -> None:
    """Run the program that `previous_main` ran, its code read afresh, as a new ``__main__``."""
    spec = getattr(previous_main, "__spec__", None)
    if spec is not None:  # `python -m package.module`: found again, its package imported anew
        spec = importlib.util.find_spec(spec.name)
    elif getattr(previous_main, "__file__", None) is not None:  # `python script.py`
        spec = importlib.util.spec_from_file_location("__main__", previous_main.__file__)
    if spec is None or not isinstance(spec.loader, importlib.abc.InspectLoader):
        msg = "can't find the program to run it again"
        raise RuntimeError(msg)
    code = spec.loader.get_code(spec.name)
    # none only for a compiled extension, which Python can't start as a program
    assert code is not None
    # as `__main__` for good, as the program's classes resolve their string annotations
    # through `sys.modules[cls.__module__]`
    program = types.ModuleType("__main__")
    program.__spec__ = spec
    program.__file__ = spec.origin
    program.__loader__ = spec.loader
    program.__package__ = spec.parent
    sys.modules["__main__"] = program
    exec(code, program.__dict__)  # noqa: S102


def save_reloaded_state(
    main_view: MainView, model: Model | None, directory: Path | None = None
) -> None:
    """Save the views' state and the model's data, for the next run to open.

    Into `directory`, an existing one, else the one the supervisor shares with the app.
    """
    directory = _state_directory() if directory is None else directory
    state_filepath = main_view.state_filepath
    save_study(main_view, model, directory / _STUDY_NAME)
    # the user's study is still the file they opened, not this scratch one
    main_view.state_filepath = state_filepath
    session = {
        "state_filepath": None if state_filepath is None else str(state_filepath),
        "language": main_view.language,
    }
    (directory / _SESSION_NAME).write_text(json.dumps(session))


def load_reloaded_state(
    main_view: MainView, model: Model | None, directory: Path | None = None
) -> None:
    """Open the state the previous run saved, if any and if it still fits the app.

    From `directory`, else the one the supervisor shares with the app.
    """
    directory = _state_directory() if directory is None else directory
    if not (directory / _STUDY_NAME).exists():
        return
    session = _read_session(directory / _SESSION_NAME)
    language = main_view.language
    # first: the study's text was saved in it
    saved_language = session.get("language")
    if isinstance(saved_language, str) and saved_language != language:
        main_view.set_language(saved_language)
    try:
        open_study(main_view, model, directory / _STUDY_NAME)
    except InvalidStateError as error:
        LOGGER.warning("The state of the previous run is dropped: %s", error)
        if main_view.language != language:
            main_view.set_language(language)
        return
    state_filepath = session.get("state_filepath")
    main_view.state_filepath = Path(state_filepath) if isinstance(state_filepath, str) else None


def _read_session(path: Path) -> dict[str, Any]:
    """Read what the study doesn't hold; nothing if it's missing or damaged, e.g. by a crash."""
    try:
        session = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return session if isinstance(session, dict) else {}


def program_command() -> list[str]:
    """Build the command running this program again: the script, or the ``-m`` module."""
    main = sys.modules["__main__"]
    spec = getattr(main, "__spec__", None)
    if spec is not None:  # `python -m package.module`
        return [sys.executable, "-m", spec.name, *sys.argv[1:]]
    path = getattr(main, "__file__", None)
    if path is not None:  # `python script.py`
        return [sys.executable, str(Path(path).resolve()), *sys.argv[1:]]
    msg = "--reload runs the program again: start it as a script or with -m"
    raise ValueError(msg)


def _environments(directory: Path) -> set[Path]:
    """Get the running Python's directories under `directory`, e.g. a conda environment's.

    Its standard library may be there, outside a ``site-packages``.
    """
    prefixes = {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}
    resolved = {Path(prefix).resolve() for prefix in prefixes}
    return {prefix for prefix in resolved if directory in prefix.parents}


def _is_ignored_directory(name: str) -> bool:
    return name.startswith(".") or name in _IGNORED_DIRECTORIES


def _is_program_file(path: Path, directory: Path) -> bool:
    """Tell whether `path` is a Python file of the program's code, both paths resolved.

    Under `directory`, not in a hidden or ignored directory, nor in a Python environment.
    """
    try:
        relative = path.relative_to(directory)
    except ValueError:
        return False
    return (
        path.suffix == ".py"
        and not any(_is_ignored_directory(part) for part in relative.parts[:-1])
        and not any(environment in path.parents for environment in _environments(directory))
    )


def _modification_times(directory: Path) -> dict[Path, int]:
    times: dict[Path, int] = {}
    environments = _environments(directory)
    for root, directories, files in os.walk(directory):
        # pruned, not walked and filtered: a virtual environment holds thousands of files
        directories[:] = [
            name
            for name in directories
            if not _is_ignored_directory(name) and Path(root, name) not in environments
        ]
        for name in files:
            if name.endswith(".py"):
                path = Path(root, name)
                with contextlib.suppress(OSError):  # removed while walking
                    times[path] = path.stat().st_mtime_ns
    return times


def has_change_events(directory: Path) -> bool:
    """Tell whether the system reports the changes under `directory`.

    On WSL, it doesn't for a Windows drive's files, under ``/mnt``: they're polled.
    """
    uname = platform.uname()
    is_wsl = uname.system == "Linux" and "microsoft" in uname.release.lower()
    return not (is_wsl and Path("/mnt") in directory.resolve().parents)


def _poll_changes(directory: Path, before: dict[Path, int]) -> Generator[set[Path], None, None]:
    """Yield the Python files changed under `directory` every step, often none."""
    while True:
        time.sleep(_STEP)
        after = _modification_times(directory)
        yield {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
        before = after


def _filtered_changes(
    directory: Path, batches: Generator[set[tuple[Any, str]], None, None]
) -> Generator[set[Path], None, None]:
    """Yield the Python files changed under `directory` in each batch of watchfiles'."""
    try:
        for batch in batches:
            changed = {Path(path) for _, path in batch}
            yield {path for path in changed if _is_program_file(path, directory)}
    finally:
        batches.close()


def watch_changes(directory: Path) -> Generator[set[Path], None, None]:
    """Watch the Python files under `directory` from now on, and yield those changed.

    The generator yields every step, often none, the files' paths resolved. With
    watchfiles installed, the system tells about changes; else, or when it can't, the files
    are polled. Close it to stop watching.
    """
    # the paths reported are the real ones, e.g. under a symbolic link's target
    directory = directory.resolve()
    try:
        from watchfiles import PythonFilter, watch  # noqa: PLC0415
    except ImportError:
        return _poll_changes(directory, _modification_times(directory))
    if not has_change_events(directory):
        return _poll_changes(directory, _modification_times(directory))
    batches = watch(
        directory,
        watch_filter=PythonFilter(),
        rust_timeout=int(_STEP * 1000),
        yield_on_timeout=True,
        # watchfiles polls anywhere on WSL by default, and misses changes so
        force_polling=False,
    )
    next(batches)  # set up: the changes from now on are kept until asked for
    return _filtered_changes(directory, batches)


def run_reloading(
    command: Sequence[str] | None = None, changes: Iterator[set[Path]] | None = None
) -> int:
    """Run `command`, the program by default, and run it again whenever a Python file changes.

    It returns once the app exits by itself without an error, e.g. its window is closed.
    An app that fails, e.g. on a syntax error, runs again only on the next change. On a
    change, the running app is asked to run the changed code (`take_changes`); if it exits
    instead, or doesn't take the files changed, it runs again in a new process.
    """
    command = program_command() if command is None else list(command)
    directory = Path.cwd().resolve()
    changes = watch_changes(directory) if changes is None else changes
    LOGGER.info("Watching the Python files under %s", directory)
    # a supervisor told to stop, e.g. by `kill`, stops its app too, which would else go on
    previous_handler = signal.signal(signal.SIGTERM, _exit)
    child: subprocess.Popen[bytes] | None = None
    # the content of each file changed, as last run: a system may report one write twice,
    # e.g. macOS, which would else run the same code twice
    contents: dict[Path, bytes | None] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="composeui-reload-") as state_directory:
            env = {**os.environ, RELOADED_VARIABLE: state_directory}
            child = subprocess.Popen(command, env=env)  # noqa: S603
            for batch in changes:
                changed = _new_contents(batch, contents, is_running=child is not None)
                if len(changed) > 0:
                    in_place = _reload_in_place(child, changed, Path(state_directory))
                    if not in_place:
                        _stop(child)
                    # once the app exited, if it did: a terminal app draws over the terminal
                    names = ", ".join(sorted(os.path.relpath(p, directory) for p in changed))
                    LOGGER.info("Reloading: %s changed", names)
                    if not in_place:
                        child = subprocess.Popen(command, env=env)  # noqa: S603
                else:
                    code = None if child is None else child.poll()
                    if code == 0:
                        return 0
                    if code is not None:
                        LOGGER.info("The app exited with code %s: waiting for a change", code)
                        child = None
    except KeyboardInterrupt:
        pass
    finally:
        _stop(child)
        if isinstance(changes, types.GeneratorType):
            changes.close()
        signal.signal(signal.SIGTERM, previous_handler)
    return 0


def _new_contents(
    batch: set[Path], contents: dict[Path, bytes | None], *, is_running: bool
) -> set[Path]:
    """Get the files of `batch` changed since the app ran them, and keep their contents.

    An app that exited runs again on any change, even one that leaves a file as it was.
    """
    if len(batch) > 0:
        time.sleep(_SETTLE)
    digests = {path: _digest(path) for path in batch}
    changed = {
        path
        for path, digest in digests.items()
        if not is_running or path not in contents or contents[path] != digest
    }
    contents.update(digests)
    return changed


def _digest(path: Path) -> bytes | None:
    """Get a digest of `path`'s content, None once it is removed."""
    try:
        return hashlib.sha256(path.read_bytes()).digest()
    except OSError:
        return None


def _exit(signum: int, _frame: FrameType | None) -> None:
    raise SystemExit(128 + signum)  # posix only: Windows' terminate sends no signal


def _reload_in_place(
    child: subprocess.Popen[bytes] | None, changed: set[Path], state_directory: Path
) -> bool:
    """Ask `child` to run the code of the files `changed`; tell whether it did, still running."""
    if child is None or child.poll() is not None:
        return False
    request = state_directory / _CHANGES_NAME
    taken = state_directory / _TAKEN_NAME
    # written whole, then renamed: the app never reads half the list
    partial = state_directory / f".{_CHANGES_NAME}.partial"
    partial.write_text("".join(f"{path}\n" for path in sorted(changed)))
    partial.replace(request)
    deadline = time.monotonic() + _RELOAD_TIMEOUT
    try:
        while True:
            if child.poll() is not None:  # it saved its state and exited for a new process
                return False
            if not request.exists() and not taken.exists():
                return True
            if request.exists() and time.monotonic() > deadline:
                LOGGER.warning("The app didn't answer: it runs again, its state since then lost")
                return False
            time.sleep(0.05)
    finally:
        # none left for the next app, whichever runs
        request.unlink(missing_ok=True)
        taken.unlink(missing_ok=True)


def _stop(child: subprocess.Popen[bytes] | None) -> None:
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=_STOP_TIMEOUT)
    except subprocess.TimeoutExpired:  # posix only: Windows' terminate can't be ignored
        child.kill()
        child.wait()
