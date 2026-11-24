"""The ``composeui`` command: ``composeui run app.py`` starts an app, reloading on a change.

The file runs as ``__main__``, as with ``python app.py``, so a file that calls ``run`` keeps
its model and its wiring. A file that starts no app needs only its one `MainView` class.

``composeui translations app.py`` checks the app's catalogs against the text it translates, as
``python -m composeui.core.translationcheck`` does.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import logging
import os
import sys
import types
from pathlib import Path

from composeui.core import translationcheck
from composeui.core.application import _Running, run
from composeui.core.view import MainView

LOGGER = logging.getLogger("COMPOSEUI")

#: environment variable naming the app's file: ``--reload`` runs this module again in other
#: processes, with a command line that is the app's only
_APP_FILE_VARIABLE = "COMPOSEUI_APP_FILE"


def _find_main_view(
    path: Path, program: types.ModuleType, *, if_none: str, if_several: str
) -> type[MainView]:
    """Get the one `MainView` class that the file defines, or stop and say why.

    `if_none` and `if_several` end the message: what the command does, or what to do.
    """
    views = [
        value
        for value in vars(program).values()
        if isinstance(value, type)
        and issubclass(value, MainView)
        and value.__module__ == program.__name__
    ]
    if len(views) == 0:
        sys.exit(f"{path.name} defines no MainView class{if_none}")
    if len(views) > 1:
        names = ", ".join(view.__name__ for view in views)
        sys.exit(f"{path.name} defines several MainView classes ({names}){if_several}")
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
        exec(code, program.__dict__)  # noqa: S102 (runs the app's file, as python does)
        if _Running.backend is None:
            run(
                _find_main_view(
                    path, program, if_none=" and starts no app", if_several=": call run with one"
                )
            )
    except BaseException:
        # the running app keeps its backend if the changed code fails
        _Running.backend = previous_backend
        raise


def _import_file(path: Path) -> types.ModuleType:
    """Import the file as a module, not as ``__main__``: it starts no app under that guard.

    A file in a package is imported by its full name, so that its relative imports work.
    """
    folder, names = path.parent, [path.stem]
    while (folder / "__init__.py").is_file():
        folder, names = folder.parent, [folder.name, *names]
    sys.path.insert(0, str(folder))
    name = ".".join(names)
    module = importlib.import_module(name)
    # a module of that name imported before, such as the standard library's `types`
    if Path(getattr(module, "__file__", None) or "").resolve() != path:
        sys.exit(f"{path.name} has the name of another module, {name}: rename the file")
    return module


def _translations(
    parser: argparse.ArgumentParser, app: str, languages: list[str], *, strict: bool
) -> int:
    """Check the catalogs of the app, given by its file or as module:Class."""
    if app.endswith(".py"):
        path = Path(app).resolve()
        if not path.is_file():
            parser.error(f"no such file: {app}")
        main_view_class = _find_main_view(
            path, _import_file(path), if_none="", if_several=": check one as module:Class"
        )
    else:
        # the modules of the current folder, as with `python -m`: a console script lacks them
        sys.path.insert(0, str(Path.cwd()))
        try:
            main_view_class = translationcheck.main_view_class_of(app)
        except argparse.ArgumentTypeError as error:
            parser.error(str(error))
    return translationcheck.check_and_report(main_view_class, languages, strict=strict)


def main() -> None:
    """Run the ``composeui`` command."""
    parser = argparse.ArgumentParser(
        prog="composeui", description="Run ComposeUI apps, and check their translations."
    )
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
    translations_parser = commands.add_parser(
        "translations",
        help="check an app's translation catalogs",
        description=(
            "Check an app's catalogs against the text its code translates. APP is the app's "
            "Python file, as for run, or module:MainViewClass."
        ),
    )
    translations_parser.add_argument(
        "app",
        metavar="APP",
        help="the app's Python file, which defines one MainView class, or module:MainViewClass",
    )
    translationcheck.add_options(translations_parser)
    args = parser.parse_args()
    if args.command == "translations":
        sys.exit(_translations(translations_parser, args.app, args.write, strict=args.strict))
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
