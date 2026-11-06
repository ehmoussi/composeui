"""The ``composeui`` command: ``composeui run app.py`` starts an app, reloading on a change.

The file runs as ``__main__``, as with ``python app.py``, so a file that calls ``run`` keeps
its model and its wiring. A file that starts no app needs only its one `MainView` class.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
import types
from pathlib import Path

from composeui.core.application import _Running, run
from composeui.core.view import MainView

LOGGER = logging.getLogger("COMPOSEUI")

#: environment variable naming the app's file: ``--reload`` runs this module again in other
#: processes, with a command line that is the app's only
_APP_FILE_VARIABLE = "COMPOSEUI_APP_FILE"


def _find_main_view(path: Path, program: types.ModuleType) -> type[MainView]:
    """Get the one `MainView` class that the file defines, or stop and say why."""
    views = [
        value
        for value in vars(program).values()
        if isinstance(value, type)
        and issubclass(value, MainView)
        and value.__module__ == program.__name__
    ]
    if len(views) == 0:
        sys.exit(f"{path.name} defines no MainView class and starts no app")
    if len(views) > 1:
        names = ", ".join(view.__name__ for view in views)
        sys.exit(f"{path.name} defines several MainView classes ({names}): call run with one")
    return views[0]


def _run_file(path: Path) -> None:
    """Run the file as the program, then its main view if the file started no app."""
    code = compile(path.read_bytes(), str(path), "exec")
    sys.argv[0] = str(path)
    if str(path.parent) not in sys.path:  # the file's imports, as with `python app.py`
        sys.path.insert(0, str(path.parent))
    program = types.ModuleType("__main__")
    program.__file__ = str(path)
    # what `--reload` runs again: this module, which runs the file again
    program.__spec__ = importlib.util.find_spec("composeui.cli")
    # for good: the classes' string annotations resolve through `sys.modules[cls.__module__]`
    sys.modules["__main__"] = program
    # a reload in place runs this in the app's process, where the backend is already set
    previous_backend = _Running.backend
    _Running.backend = None
    try:
        exec(code, program.__dict__)  # noqa: S102
        if _Running.backend is None:
            run(_find_main_view(path, program))
    except BaseException:
        # the running app keeps its backend if the changed code fails
        _Running.backend = previous_backend
        raise


def main() -> None:
    """Run the ``composeui`` command."""
    parser = argparse.ArgumentParser(prog="composeui", description="Run ComposeUI apps.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser(
        "run",
        help="run an app from a Python file",
        description=(
            "Run an app from a Python file, and reload it when a Python file under the current "
            "directory changes."
        ),
        allow_abbrev=False,
    )
    run_parser.add_argument("--no-reload", action="store_true", help="don't reload on a change")
    run_parser.add_argument("file", metavar="FILE", type=Path, help="the app's Python file")
    run_parser.add_argument(
        "app_arguments",
        metavar="...",
        nargs=argparse.REMAINDER,
        help="the app's options, e.g. --backend qt or --port 8080 (`FILE --help` lists them)",
    )
    args = parser.parse_args()
    path = args.file.resolve()
    if not path.is_file():
        run_parser.error(f"no such file: {args.file}")
    app_arguments = args.app_arguments
    if not args.no_reload:
        app_arguments = [*app_arguments, "--reload"]
        if Path.cwd().resolve() not in path.parents:
            LOGGER.warning("%s isn't under the current directory: it won't reload", path.name)
    os.environ[_APP_FILE_VARIABLE] = str(path)
    sys.argv = [str(path), *app_arguments]
    _run_file(path)


if __name__ == "__main__":
    _run_file(Path(os.environ[_APP_FILE_VARIABLE]))
