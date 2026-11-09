"""The application classes of the Textual backend."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from composeui.core.application import (
    Application,
    ModelApplication,
    check_writable,
    logs_in_file,
)
from composeui.core.reload import (
    is_reloaded,
    load_reloaded_state,
    run_reloading,
    save_reloaded_state,
    take_changes,
)
from composeui.core.view import RendererType
from composeui.textualcore.textualrenderer import TextualMainRenderer

if TYPE_CHECKING:
    from collections.abc import Callable

    from composeui.core.model import Model
    from composeui.core.view import MainView


#: seconds between two looks, in a reloaded app, at whether files changed
_CHANGES_CHECK_INTERVAL = 0.2
#: where the log messages go while the app is shown: on the terminal, they'd cover the app
_LOG_FILE = Path("composeui.log")

LOGGER = logging.getLogger("COMPOSEUI")

MainViewT = TypeVar("MainViewT", bound="MainView")
ModelT = TypeVar("ModelT", bound="Model")


def _log_file(text: str) -> Path:
    """Get the file a user names, refused at once rather than losing its messages."""
    path = Path(text)
    try:
        check_writable(path)
    except OSError as error:
        message = f"can't write to it: {error}"
        raise argparse.ArgumentTypeError(message) from error
    return path


def _add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--reload",
        help="Run the app again when a Python file under the current directory changes.",
        action="store_true",
    )
    parser.add_argument(
        "--log-file",
        metavar="FILE",
        help=f"Write the log messages to FILE while the app is shown (default: {_LOG_FILE}).",
        type=_log_file,
        default=_LOG_FILE,
    )


def _exec(
    args: argparse.Namespace | None,
    main_view: MainView,
    model: Model | None,
    render: Callable[[RendererType], None],
) -> None:
    """Show the main view until the app exits, or run it again on every change.

    Then close `model`; a supervisor, which never shows it, closes it first.
    """
    assert args is not None
    if args.reload and not is_reloaded():
        # never shown here: closed first, as the child processes build and open their own
        if model is not None:
            model.close()
        run_reloading()
        return
    try:
        _show(main_view, model, render, args.log_file)
    finally:
        if model is not None:
            model.close()


def _show(
    main_view: MainView,
    model: Model | None,
    render: Callable[[RendererType], None],
    log_file: Path,
) -> None:
    if is_reloaded():
        load_reloaded_state(main_view, model)
    render(RendererType.TEXTUAL)
    renderer = main_view.renderer
    app = renderer.app if isinstance(renderer, TextualMainRenderer) else None
    assert app is not None
    if is_reloaded():
        # on a change, the app saves its state and exits, as only a new process imports the
        # changed code afresh: the supervisor runs it again, which opens the state
        def exit_on_changes() -> None:
            if take_changes() is not None:
                save_reloaded_state(main_view, model)
                app.exit()

        def follow_changes() -> None:
            app.set_interval(_CHANGES_CHECK_INTERVAL, exit_on_changes)

        app.mounted_callbacks.append(follow_changes)
    try:
        check_writable(log_file)
    except OSError as error:  # only the default: not worth refusing to run from such a folder
        LOGGER.warning("No log file while the app is shown, choose one with --log-file: %s", error)
    with logs_in_file(log_file):
        app.run()


class TextualApplication(Application[MainViewT]):
    """The Textual app: it shows the main view in the terminal."""

    backend = RendererType.TEXTUAL

    def __init__(self, *, build_main_view: Callable[[], MainViewT]) -> None:
        super().__init__(build_main_view=build_main_view)
        _add_arguments(self._parser)

    def run(self) -> None:
        super().run()
        _exec(self._args, self.main_view, None, self.render)


class TextualModelApplication(ModelApplication[MainViewT, ModelT]):
    """The Textual app with a model, which it closes once the app exits."""

    backend = RendererType.TEXTUAL

    def __init__(
        self,
        *,
        build_main_view: Callable[[], MainViewT],
        build_model: Callable[[], ModelT],
        setup_model: Callable[[MainViewT, ModelT], None] | None = None,
    ) -> None:
        super().__init__(
            build_main_view=build_main_view, build_model=build_model, setup_model=setup_model
        )
        _add_arguments(self._parser)

    def run(self) -> None:
        super().run()
        _exec(self._args, self.main_view, self.model, self.render)


#: the backend's applications, for `composeui.core.application.run`
APPLICATION = TextualApplication
MODEL_APPLICATION = TextualModelApplication
