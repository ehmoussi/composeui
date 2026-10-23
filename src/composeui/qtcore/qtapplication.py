"""The application classes of the Qt backend."""

from __future__ import annotations

import logging
import signal
import sys
from typing import TYPE_CHECKING, NamedTuple, TypeVar

from qtpy.QtCore import QThread, QTimer
from qtpy.QtWidgets import QApplication, QMainWindow, QWidget

from composeui.core.application import Application, ModelApplication
from composeui.core.reload import (
    acknowledge_changes,
    can_reload_in_place,
    is_reloaded,
    keep_rerun,
    load_reloaded_state,
    rerun_program,
    run_reloading,
    save_reloaded_state,
    take_changes,
)
from composeui.core.view import RendererType
from composeui.qtcore.qtrenderer import QtMainRenderer

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable
    from pathlib import Path

    from composeui.core.model import Model
    from composeui.core.view import MainView, View


LOGGER = logging.getLogger("COMPOSEUI")

#: milliseconds between two looks, in a reloaded app, at whether files changed
_CHANGES_CHECK_INTERVAL = 200

MainViewT = TypeVar("MainViewT", bound="MainView")
ModelT = TypeVar("ModelT", bound="Model")


class _Run(NamedTuple):
    """An app ready to show its main view, its command line parsed."""

    args: argparse.Namespace
    main_view: MainView
    model: Model | None
    render: Callable[[RendererType], None]


def _add_reload_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--reload",
        help="Run the app again when a Python file under the current directory changes.",
        action="store_true",
    )


def _exec(run: _Run) -> int:
    """Show the main view until its window is closed, or run it again on every change."""
    if run.args.reload and not is_reloaded():
        # never shown here: closed first, as the child processes build and open their own
        if run.model is not None:
            run.model.close()
        # the app runs in a child process, which a new one replaces when it can't run the
        # changed code itself
        return run_reloading()
    app = QApplication(sys.argv)
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # kill the program when Ctr+c
    if not is_reloaded():
        run.render(RendererType.QT)
        try:
            return app.exec()
        finally:
            if run.model is not None:
                run.model.close()
    reloads = _Reloads(run)
    try:
        return app.exec()
    finally:
        reloads.close()


class _Reloads:
    """The window of a reloaded app, which shows the app the changed code builds."""

    def __init__(self, run: _Run) -> None:
        self._run = run
        #: the files changed, taken, whose code the app runs once it can
        self._changed: list[Path] | None = None
        load_reloaded_state(run.main_view, run.model)
        run.render(RendererType.QT)
        self._timer = QTimer()
        self._timer.timeout.connect(self._follow_changes)
        self._timer.start(_CHANGES_CHECK_INTERVAL)

    def close(self) -> None:
        """Close the model of the app shown last."""
        if self._run.model is not None:
            self._run.model.close()

    def _follow_changes(self) -> None:
        if self._changed is None:
            self._changed = take_changes()
        # The timer also fires in a nested event loop, e.g. a file dialog's that a callback
        # opened: the callback goes on with the app once it returns. Not a check of the
        # modal dialog, which its loop outlives for a last event once it's closed.
        if self._changed is None or QThread.currentThread().loopLevel() > 1:
            return
        changed, self._changed = self._changed, None
        save_reloaded_state(self._run.main_view, self._run.model)
        if not can_reload_in_place(changed):
            # the supervisor runs the program in a new process, which opens the state saved
            self._timer.stop()
            QApplication.quit()
            return
        try:
            run = rerun_program()
        except Exception:
            LOGGER.exception("The changed code fails: the window keeps the previous code")
            acknowledge_changes()
            return
        try:
            self._show(run)
        except Exception:
            # the window may be half replaced: a new process shows the state saved
            LOGGER.exception("The changed app can't show: it runs again in a new process")
            if run.model is not None and run.model is not self._run.model:
                run.model.close()
            self._timer.stop()
            QApplication.quit()
            return
        acknowledge_changes()

    def _show(self, run: _Run) -> None:
        """Show `run`'s main view in the window, in place of the previous one."""
        previous = self._run
        renderer = previous.main_view.renderer
        window = renderer.qt_object if isinstance(renderer, QtMainRenderer) else None
        assert window is not None
        load_reloaded_state(run.main_view, run.model)
        previous.main_view.jobs.drop()
        _forget_widgets(previous.main_view, window)
        run.main_view.renderer = QtMainRenderer(run.main_view, window)
        run.render(RendererType.QT)
        self._run = run
        if previous.model is not None and previous.model is not run.model:
            previous.model.close()


def _forget_widgets(view: View, window: QMainWindow) -> None:
    """Detach `view` and its children from their widgets, which the window drops.

    So a late change of a view, e.g. a status bar clearing its message, reaches no widget;
    the windows of its own, e.g. a dialog's, close.
    """
    for child in view.children_views:
        _forget_widgets(child, window)
    widget = getattr(view.renderer, "qt_object", None)
    if isinstance(widget, QWidget) and widget.isWindow() and widget is not window:
        widget.close()
        widget.deleteLater()
    # not through the view's `on_setattr`: it would show the change on the renderer
    object.__setattr__(view, "renderer", None)


class QtApplication(Application[MainViewT]):
    """The Qt app: it shows the main view in a window."""

    def __init__(self, *, build_main_view: Callable[[], MainViewT]) -> None:
        super().__init__(build_main_view=build_main_view)
        _add_reload_argument(self._parser)

    def run(self) -> None:
        super().run()
        assert self._args is not None
        run = _Run(self._args, self.main_view, None, self.render)
        keep_rerun(run)
        sys.exit(_exec(run))


class QtModelApplication(ModelApplication[MainViewT, ModelT]):
    """The Qt app with a model, which it closes once the window is closed."""

    def __init__(
        self,
        *,
        build_main_view: Callable[[], MainViewT],
        build_model: Callable[[], ModelT],
        setup_model: Callable[[MainViewT, ModelT], None] | None = None,
    ) -> None:
        try:
            super().__init__(
                build_main_view=build_main_view, build_model=build_model, setup_model=setup_model
            )
        except BaseException:
            # built first: e.g. a reload of a program whose `setup_model` now fails
            model: Model | None = getattr(self, "_model", None)
            if model is not None:
                model.close()
            raise
        _add_reload_argument(self._parser)

    def run(self) -> None:
        try:
            super().run()
        except BaseException:
            self.model.close()
            raise
        assert self._args is not None
        run = _Run(self._args, self.main_view, self.model, self.render)
        keep_rerun(run)
        sys.exit(_exec(run))


#: the backend's applications, for `composeui.core.application.run`
APPLICATION = QtApplication
MODEL_APPLICATION = QtModelApplication
