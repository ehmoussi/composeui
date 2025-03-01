r"""Slots of the study management."""

from composeui.commontypes import AnyModel
from composeui.core import selectfiles, tools
from composeui.core.tasks.tasks import Tasks
from composeui.mainview import progresspopup
from composeui.mainview.filetask import OpenTask, SaveTask
from composeui.mainview.views.mainview import MainView

from functools import partial
from pathlib import Path


def new(*, main_view: MainView, model: AnyModel) -> None:
    r"""Create a new study after asking a confirmation."""
    if ask_confirmation(main_view, "clear"):
        clear(main_view, model)


def open_file(*, main_view: MainView, model: AnyModel) -> None:
    r"""Open the study."""
    filepath = selectfiles.select_study_file(main_view)
    if filepath is not None:
        progresspopup.display_view(
            main_view,
            Tasks([OpenTask(model, filepath)], print_to_std=True, name="Open Study"),
            finished_slots=[partial(tools.update_all_views, main_view)],
        )


def open_file_without_update(*, main_view: MainView, model: AnyModel) -> None:
    r"""Open the study without an update of the views.

    Useful for example with Salome where opening a study destroy some views.
    So the update may raise a RuntimError.
    """
    filepath = selectfiles.select_study_file(main_view)
    if filepath is not None:
        progresspopup.display_view(
            main_view,
            Tasks([OpenTask(model, filepath)], print_to_std=True, name="Open Study"),
        )


def save(*, main_view: MainView, model: AnyModel) -> None:
    r"""Save the study."""
    save_study(main_view, model, ask_filepath=False)


def save_as(*, main_view: MainView, model: AnyModel) -> None:
    r"""Save the study as."""
    save_study(main_view, model, ask_filepath=True)


def save_before_exit(*, main_view: MainView, model: AnyModel) -> None:
    r"""Save before exiting the application."""
    save_study(main_view, model, ask_filepath=False, force_close=True)


def forced_exit(*, main_view: MainView, force_close: bool) -> None:
    r"""Force the exit of the application."""
    main_view.force_close = force_close


def exit_app(*, main_view: MainView) -> None:
    r"""Exit the application."""
    main_view.closed = True


def save_study(
    main_view: MainView,
    model: AnyModel,
    ask_filepath: bool = True,
    force_close: bool = False,
) -> None:
    r"""Save the study."""
    if ask_filepath or model.filepath is None:
        filepath = selectfiles.save_study_file(main_view)
    elif force_close or ask_confirmation(main_view, "save"):
        filepath = Path(model.filepath)
    else:
        filepath = None
    if filepath is not None:
        model.filepath = filepath
        tasks = Tasks([SaveTask(model, filepath)], print_to_std=True, name="Save Study")
        progresspopup.display_view(
            main_view,
            tasks,
            finished_slots=[partial(forced_exit, force_close=force_close)],
        )


def clear(main_view: MainView, model: AnyModel) -> None:
    r"""Clear datas."""
    model.new()
    tools.update_all_views(main_view)


def ask_confirmation(main_view: MainView, action: str) -> bool:
    r"""Ask a confirmation before an action on the study."""
    return tools.ask_confirmation(
        main_view, f"Are you sure you want to {action} the current study ?"
    )
