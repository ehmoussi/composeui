r"""Slots functions for the progress popup view."""

from composeui import mainview
from composeui.core import tools
from composeui.core.basesignal import Callback
from composeui.core.tasks.abstracttask import AbstractTask, TaskStatus
from composeui.core.tasks.tasks import Tasks
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.progresspopupview import ProgressPopupView

from functools import partial
from typing import Iterable, Optional


def display_view(
    main_view: MainView,
    tasks: Tasks[AbstractTask],
    progress_slots: Optional[Iterable[Callback]] = None,
    finished_slots: Optional[Iterable[Callback]] = None,
    canceled_slots: Optional[Iterable[Callback]] = None,
) -> None:
    r"""Progress view."""
    main_view.progress_popup_view.tasks = tasks
    mainview.initialize_progress_popup_view(main_view.progress_popup_view)
    if progress_slots is not None:
        main_view.progress_popup_view.progress += progress_slots
    main_view.progress_popup_view.finished = [partial(check, main_view)]
    if finished_slots is not None:
        main_view.progress_popup_view.finished += finished_slots
    main_view.progress_popup_view.canceled += [
        partial(display_cancelling_text, main_view.progress_popup_view)
    ]
    if canceled_slots is not None:
        main_view.progress_popup_view.canceled += canceled_slots
    main_view.progress_popup_view.run()


def check(main_view: MainView) -> None:
    r"""Check if the save task has not failed."""
    tasks = main_view.progress_popup_view.tasks
    if tasks is not None:
        if tasks.status == TaskStatus.FAILED:
            tools.display_error_message(main_view, tasks.join_error_messages())
        elif tasks.status == TaskStatus.WARNING:
            tools.display_warning_message(main_view, tasks.join_warning_messages())


def display_cancelling_text(view: ProgressPopupView) -> None:
    r"""Display a cancelling text."""
    tasks = view.tasks
    if tasks is not None:
        view.label_text = (
            "Can't cancel a running task ..." if tasks.is_sequential else "Cancelling ..."
        )
