r"""Initialization of views."""

from composeui.core.tasks import progresstask
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.core.views.actionview import ActionView
from composeui.core.views.popuptextview import DialogChoices, PopupTextView
from composeui.core.views.progressview import ProgressView
from composeui.core.views.selectpathview import SelectPathView
from composeui.core.views.view import GroupView, View
from composeui.figure import initialize_figure_view
from composeui.figure.figureview import FigureView
from composeui.form import initialize_form_view
from composeui.form.formview import FormView
from composeui.items.core.initialize import initialize_items_view
from composeui.items.linkedtable import initialize_linked_table
from composeui.items.linkedtable.linkedtableview import LinkedTableView
from composeui.items.table.tableview import TableView
from composeui.items.tree import initialize_tree_view
from composeui.items.tree.treeview import TreeView
from composeui.mainview import (
    initialize_file_menu,
    initialize_file_toolbar,
    initialize_file_view,
    initialize_main_view,
    initialize_message_view,
    initialize_progress_popup_view,
)
from composeui.mainview.views.fileview import FileView
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.menu import FileMenu
from composeui.mainview.views.messageview import MessageView
from composeui.mainview.views.progresspopupview import ProgressPopupView
from composeui.mainview.views.toolbar import FileToolBar
from composeui.vtk import initialize_vtk_view
from composeui.vtk.vtkview import VTKView

from functools import wraps
from typing import Callable, TypeVar

T = TypeVar("T", bound=AbstractTask)


def initialize_explorer(initialize_view: Callable[[View], bool]) -> Callable[[View], None]:
    r"""Explore and initialize the view and its children."""

    @wraps(initialize_view)
    def _initialize(view: View) -> None:
        keep_exploring = initialize_view(view)
        if keep_exploring:
            for child_view in view.children.values():
                _initialize(child_view)

    return _initialize


@initialize_explorer
def initialize_default_view(view: View) -> bool:
    # global initialization
    if isinstance(view, View):
        view.dependencies.clear()
        # don't modify is_visible here because the visibility
        # depend of the parent visibility unless the visibility has been
        # modified explicitly
        view.is_enabled = True
    if isinstance(view, GroupView):
        initialize_group_view(view)
    # specific initialization
    if isinstance(view, MainView):
        return initialize_main_view(view)
    elif isinstance(view, FileMenu):
        return initialize_file_menu(view)
    elif isinstance(view, FileToolBar):
        return initialize_file_toolbar(view)
    elif isinstance(view, ActionView):
        view.visible_views.clear()
    elif isinstance(view, LinkedTableView):
        return initialize_linked_table(view)
    elif isinstance(view, TreeView):
        return initialize_tree_view(view)
    elif isinstance(view, TableView):
        return initialize_items_view(view)
    elif isinstance(view, FormView):
        return initialize_form_view(view)
    elif isinstance(view, SelectPathView):
        return initialize_select_path_view(view)
    elif isinstance(view, PopupTextView):
        return initialize_popup_text_view(view)
    elif isinstance(view, MessageView):
        return initialize_message_view(view)
    elif isinstance(view, ProgressView):
        return initialize_progress_view(view, with_tasks=False)
    elif isinstance(view, ProgressPopupView):
        return initialize_progress_popup_view(view, with_tasks=False)
    elif isinstance(view, FileView):
        return initialize_file_view(view)
    elif isinstance(view, FigureView):
        return initialize_figure_view(view)
    elif isinstance(view, VTKView):
        return initialize_vtk_view(view)
    return True


def initialize_group_view(view: GroupView) -> bool:
    """Initialize the group view."""
    view.title = ""
    view.is_checkable = False
    view.is_checked = False
    return True


def initialize_select_path_view(view: SelectPathView) -> bool:
    """Initialize the select path view."""
    view.path = ""
    view.label = ""
    view.button_name = "..."
    view.filter_path = ""
    view.mode = "open_file"
    return False


def initialize_popup_text_view(view: PopupTextView) -> bool:
    view.text = ""
    view.title = ""
    view.confirm_button_text = ""
    view.choice = DialogChoices.rejected
    return False


def initialize_progress_view(view: ProgressView[T], with_tasks: bool = True) -> bool:
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
