r"""Initialization of views."""

from composeui.core.tasks import progresstask
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.core.views.iactionview import IActionView
from composeui.core.views.ipopuptextview import DialogChoices, IPopupTextView
from composeui.core.views.iprogressview import IProgressView
from composeui.core.views.iselectpathview import ISelectPathView
from composeui.core.views.iview import IGroupView, IView
from composeui.figure import initialize_figure_view
from composeui.figure.ifigureview import IFigureView
from composeui.items.core.initialize import initialize_items_view
from composeui.items.linkedtable import initialize_linked_table
from composeui.items.linkedtable.ilinkedtableview import ILinkedTableView
from composeui.items.table.itableview import ITableView
from composeui.items.tree import initialize_tree_view
from composeui.items.tree.itreeview import ITreeView
from composeui.mainview import (
    initialize_file_menu,
    initialize_file_toolbar,
    initialize_file_view,
    initialize_main_view,
    initialize_message_view,
    initialize_progress_popup_view,
)
from composeui.mainview.interfaces.ifileview import IFileView
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.imenu import IFileMenu
from composeui.mainview.interfaces.imessageview import IMessageView
from composeui.mainview.interfaces.iprogresspopupview import IProgressPopupView
from composeui.mainview.interfaces.itoolbar import IFileToolBar
from composeui.vtk import initialize_vtk_view
from composeui.vtk.ivtkview import IVTKView

from functools import wraps
from typing import Callable, TypeVar

T = TypeVar("T", bound=AbstractTask)


def initialize_explorer(initialize_view: Callable[[IView], bool]) -> Callable[[IView], None]:
    r"""Explore and initialize the view and its children."""

    @wraps(initialize_view)
    def _initialize(view: IView) -> None:
        keep_exploring = initialize_view(view)
        if keep_exploring:
            for child_view in view.children.values():
                _initialize(child_view)

    return _initialize


@initialize_explorer
def initialize_default_view(view: IView) -> bool:
    # global initialization
    if isinstance(view, IView):
        view.dependencies.clear()
        # don't modify is_visible here because the visibility
        # depend of the parent visibility unless the visibility has been
        # modified explicitly
        view.is_enabled = True
    if isinstance(view, IGroupView):
        initialize_group_view(view)
    # specific initialization
    if isinstance(view, IMainView):
        return initialize_main_view(view)
    elif isinstance(view, IFileMenu):
        return initialize_file_menu(view)
    elif isinstance(view, IFileToolBar):
        return initialize_file_toolbar(view)
    elif isinstance(view, IActionView):
        view.visible_views.clear()
    elif isinstance(view, ILinkedTableView):
        return initialize_linked_table(view)
    elif isinstance(view, ITreeView):
        return initialize_tree_view(view)
    elif isinstance(view, ITableView):
        return initialize_items_view(view)
    elif isinstance(view, ISelectPathView):
        return initialize_select_path_view(view)
    elif isinstance(view, IPopupTextView):
        return initialize_popup_text_view(view)
    elif isinstance(view, IMessageView):
        return initialize_message_view(view)
    elif isinstance(view, IProgressView):
        return initialize_progress_view(view, with_tasks=False)
    elif isinstance(view, IProgressPopupView):
        return initialize_progress_popup_view(view, with_tasks=False)
    elif isinstance(view, IFileView):
        return initialize_file_view(view)
    elif isinstance(view, IFigureView):
        return initialize_figure_view(view)
    elif isinstance(view, IVTKView):
        return initialize_vtk_view(view)
    return True


def initialize_group_view(view: IGroupView) -> bool:
    """Initialize the group view."""
    view.title = ""
    view.is_checkable = False
    view.is_checked = False
    return True


def initialize_select_path_view(view: ISelectPathView) -> bool:
    """Initialize the select path view."""
    view.path = ""
    view.label = ""
    view.button_name = "..."
    view.filter_path = ""
    view.mode = "open_file"
    return False


def initialize_popup_text_view(view: IPopupTextView) -> bool:
    view.text = ""
    view.title = ""
    view.confirm_button_text = ""
    view.choice = DialogChoices.rejected
    return False


def initialize_progress_view(view: IProgressView[T], with_tasks: bool = True) -> bool:
    r"""Initialize the progress view."""
    view.is_percentage_visible = False
    view.minimum = 0
    view.maximum = 100
    view.value = 0
    view.run_text = "Run"
    view.cancel_text = "Cancel"
    view.button_enabled = True
    view.button_text = view.run_text
    if with_tasks:
        progresstask.update_progress_range(view, is_about_to_run=False)
    else:
        view.tasks = None
    return False
