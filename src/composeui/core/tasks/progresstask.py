r"""Slots for the progress view."""

from composeui.core import tools
from composeui.core.interfaces.iprogressview import IProgress, IProgressView
from composeui.core.tasks.abstracttask import AbstractTask, TaskStatus
from composeui.mainview.interfaces.imainview import IMainView

from typing import TypeVar

T = TypeVar("T", bound=AbstractTask)


def run(*, view: IProgressView[T]) -> None:
    update_progress_range(view, is_about_to_run=True)
    tasks = view.tasks
    if tasks is not None:
        view.button_enabled = False
        if tasks.is_running and not tasks.is_sequential:
            view.cancel()
        else:
            tasks.clear()
            view.run()
            if not tasks.is_sequential:
                view.button_enabled = True
                view.button_text = view.cancel_text


def progress(*, view: IProgressView[T]) -> None:
    if view.tasks is not None:
        view.value = view.tasks.count_finished()


def finished(*, view: IProgressView[T]) -> None:
    view.button_enabled = view.tasks is not None and len(view.tasks) > 0
    view.button_text = view.run_text
    if view.tasks is not None and view.tasks.is_sequential:
        view.value = view.maximum = 1


def update_progress_range(view: IProgress[T], is_about_to_run: bool = False) -> None:
    r"""Update the range of the progress bar of a progress view."""
    view.value = 0
    view.minimum = 0
    if view.tasks is None:
        raise ValueError("The tasks must be set first.")
    elif len(view.tasks) > 1:
        view.is_percentage_visible = True
        view.maximum = len(view.tasks)
    else:
        view.is_percentage_visible = False
        view.maximum = int(not is_about_to_run)


def check(*, view: IProgressView[T], main_view: IMainView) -> None:
    r"""Check if the save task has not failed."""
    tasks = view.tasks
    if tasks is not None:
        if tasks.status == TaskStatus.FAILED:
            tools.display_error_message(main_view, tasks.join_error_messages())
        elif tasks.status == TaskStatus.WARNING:
            tools.display_warning_message(main_view, tasks.join_warning_messages())


# def notify_task_errors(main_view: IProgressView[T], view_path: Tuple[str, ...]) -> None:
#     r"""Notify the error message of the task."""
#     view = tools.find_view(main_view, view_path)
#     warning_message = view["task"].warning_message
#     if warning_message != "":
#         tools.display_warning_message(main_view, warning_message)
#     error_message = view["task"].error_message
#     if error_message != "":
#         tools.display_error_message(main_view, error_message)
