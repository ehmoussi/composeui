r"""Connect the signals to the default slots."""

from composeui.commontypes import AnyModel
from composeui.core import selectfiles
from composeui.core.interfaces.iprogressview import IProgressView
from composeui.core.interfaces.iselectpathview import ISelectPathView
from composeui.core.interfaces.iview import IView
from composeui.core.tasks import progresstask
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.form import connect_apply_form_view, connect_form_view
from composeui.form.iformview import IApplyFormView, IFormView
from composeui.items.linkedtable import connect_linked_table, connect_linked_table_view
from composeui.items.linkedtable.ilinkedtableview import ILinkedTableView
from composeui.items.table import connect_table
from composeui.items.table.itableview import ITableView
from composeui.items.tree import connect_tree
from composeui.items.tree.itreeview import ITreeView
from composeui.linkedtablefigure import connect_table_figure_view
from composeui.linkedtablefigure.ilinkedtablefigureview import ILinkedTableFigureView
from composeui.mainview import (
    connect_checkable_toolbar,
    connect_file_menu,
    connect_file_menu_toolbar,
    connect_main_view,
)
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.imenu import IFileMenu
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar, IFileToolBar
from composeui.vtk import connect_vtk_view
from composeui.vtk.ivtkview import IVTKView

from typing_extensions import Concatenate, ParamSpec

from functools import wraps
from typing import Callable, Optional, TypeVar

Ttask = TypeVar("Ttask", bound=AbstractTask)

P = ParamSpec("P")


def connect_explorer(
    connect_by_keys: Callable[Concatenate[IView, P], bool],
) -> Callable[Concatenate[IView, P], None]:
    r"""Explore the view and its children to apply connections."""

    @wraps(connect_by_keys)
    def _connect(view: IView, *args: P.args, **kwargs: P.kwargs) -> None:
        keep_exploring = connect_by_keys(view, *args, **kwargs)
        if keep_exploring:
            for child_view in view.children.values():
                _connect(child_view, *args, **kwargs)

    # see: https://github.com/python/mypy/issues/17166
    return _connect  # type: ignore[return-value]


@connect_explorer
def connect_by_default(
    view: IView,
    main_view: IMainView,
    model: AnyModel,
    parent_view: Optional[IView] = None,
) -> bool:
    r"""Apply default connections to the view.

    Returns True if it needs to explore also its children.
    """
    if isinstance(view, IMainView):
        return connect_main_view(view)
    elif isinstance(view, (IFileMenu, IFileToolBar)):
        connect_file_menu_toolbar(view, main_view)
        if isinstance(view, IFileMenu):
            connect_file_menu(view)
        return False
    elif isinstance(view, ICheckableToolBar):
        return connect_checkable_toolbar(view)
    elif isinstance(view, ILinkedTableView):
        keep_exploring = connect_linked_table(view.master_table, view.detail_table)
        keep_exploring &= connect_linked_table_view(view)
        return keep_exploring
    elif isinstance(view, ILinkedTableFigureView):
        return connect_table_figure_view(view)
    elif isinstance(view, ITreeView):
        return connect_tree(view)
    elif isinstance(view, ITableView):
        return connect_table(view)
    elif isinstance(view, IApplyFormView):
        return connect_apply_form_view(view)
    elif isinstance(view, IFormView):
        return connect_form_view(view)
    elif isinstance(view, IProgressView):
        return connect_progress_view(view)
    elif isinstance(view, ISelectPathView):
        return connect_select_path_view(view)
    elif isinstance(view, IVTKView):
        return connect_vtk_view(view)
    return True


def connect_progress_view(view: IProgressView[Ttask]) -> bool:
    r"""Connect the slots for the progress view."""
    view.button_clicked = [progresstask.run]
    view.progress = [progresstask.progress]
    view.finished = [[progresstask.finished, progresstask.check]]
    return False


def connect_select_path_view(view: ISelectPathView) -> bool:
    view.select_clicked = [selectfiles.select_path]
    return False
