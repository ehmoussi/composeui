r"""Connect the signals to the default slots."""

from composeui.commontypes import AnyModel, AnyMainView
from composeui.core import selectfiles
from composeui.core.tasks import progresstask
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.core.views.progressview import ProgressView
from composeui.core.views.selectpathview import SelectPathView
from composeui.core.views.view import View
from composeui.form import connect_apply_form_view, connect_form_view
from composeui.form.formview import ApplyFormView, FormView
from composeui.items.linkedtable import connect_linked_table, connect_linked_table_view
from composeui.items.linkedtable.linkedtableview import LinkedTableView
from composeui.items.table import connect_table
from composeui.items.table.tableview import TableView
from composeui.items.tree import connect_tree
from composeui.items.tree.treeview import TreeView
from composeui.linkedtablefigure import connect_table_figure_view
from composeui.linkedtablefigure.linkedtablefigureview import LinkedTableFigureView
from composeui.mainview import (
    connect_checkable_toolbar,
    connect_file_menu,
    connect_file_menu_toolbar,
    connect_main_view,
)
from composeui.mainview.views.mainview import MainView
from composeui.mainview.views.menu import FileMenu
from composeui.mainview.views.toolbar import CheckableToolBar, FileToolBar
from composeui.vtk import connect_vtk_view
from composeui.vtk.vtkview import VTKView

from typing_extensions import Concatenate, ParamSpec

from functools import wraps
from typing import Callable, TypeVar


Ttask = TypeVar("Ttask", bound=AbstractTask)

P = ParamSpec("P")


def connect_explorer(
    connect_by_keys: Callable[Concatenate[View, P], bool],
) -> Callable[Concatenate[View, P], None]:
    r"""Explore the view and its children to apply connections."""

    @wraps(connect_by_keys)
    def _connect(view: View, *args: P.args, **kwargs: P.kwargs) -> None:
        keep_exploring = connect_by_keys(view, *args, **kwargs)
        if keep_exploring:
            for child_view in view.children.values():
                _connect(child_view, *args, **kwargs)

    # see: https://github.com/python/mypy/issues/17166
    return _connect  # type: ignore[return-value]


@connect_explorer
def connect_by_default(view: View, main_view: MainView) -> bool:
    r"""Apply default connections to the view.

    Returns True if it needs to explore also its children.
    """
    if isinstance(view, MainView):
        return connect_main_view(view)
    elif isinstance(view, (FileMenu, FileToolBar)):
        connect_file_menu_toolbar(view, main_view)
        if isinstance(view, FileMenu):
            connect_file_menu(view)
        return False
    elif isinstance(view, CheckableToolBar):
        return connect_checkable_toolbar(view)
    elif isinstance(view, LinkedTableView):
        keep_exploring = connect_linked_table(view.master_table, view.detail_table)
        keep_exploring &= connect_linked_table_view(view)
        return keep_exploring
    elif isinstance(view, LinkedTableFigureView):
        return connect_table_figure_view(view)
    elif isinstance(view, TreeView):
        return connect_tree(view)
    elif isinstance(view, TableView):
        return connect_table(view)
    elif isinstance(view, ApplyFormView):
        return connect_apply_form_view(view)
    elif isinstance(view, FormView):
        return connect_form_view(view)
    elif isinstance(view, ProgressView):
        return connect_progress_view(view)
    elif isinstance(view, SelectPathView):
        return connect_select_path_view(view)
    elif isinstance(view, VTKView):
        return connect_vtk_view(view)
    return True


def connect_progress_view(view: ProgressView[Ttask]) -> bool:
    r"""Connect the slots for the progress view."""
    view.button_clicked = [progresstask.run]
    view.progress = [progresstask.progress]
    view.finished = [[progresstask.finished, progresstask.check]]
    return False


def connect_select_path_view(view: SelectPathView) -> bool:
    view.select_clicked = [selectfiles.select_path]
    return False
