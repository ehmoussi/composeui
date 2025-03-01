r"""Slots of a table."""

from composeui.commontypes import AnyModel
from composeui.core import selectfiles, tools
from composeui.core.tasks.tasks import Tasks
from composeui.items.core import pagination
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.table.exportfiletabletask import ExportFileTableTask
from composeui.items.table.importfiletabletask import ImportFileTableTask
from composeui.items.table.tableview import TableView
from composeui.mainview import progresspopup
from composeui.mainview.views.mainview import MainView

from typing_extensions import TypeAlias

from functools import partial
from typing import Any, Optional

AnyTableView: TypeAlias = TableView[AbstractTableItems[Any]]


def add_clicked(*, view: AnyTableView) -> None:
    r"""Add an item in the table."""
    if view.items is not None:
        new_selected_row: Optional[int] = None
        selected_rows = view.items.get_selected_rows()
        if len(selected_rows) > 0:
            row = selected_rows[-1]
        else:
            row = view.items.get_nb_rows() - 1
        new_selected_row = view.items.insert(row + 1)
        # update pagination
        # update the current page size to get the correct current page
        # the update of the current page need to be done before the update of the table
        # to display the correct rows for the new current page
        pagination.update_current_page_size(view=view.pagination_view, parent_view=view)
        if new_selected_row is not None:
            view.items.page_navigator.set_current_page_from_row(new_selected_row)
        else:
            view.items.page_navigator.set_current_page_from_row(row + 1)
        # update table
        tools.update_view_with_dependencies(view)
        if new_selected_row is not None:
            view.items.set_selected_rows([new_selected_row])


def remove_clicked(*, view: AnyTableView, main_view: MainView) -> None:
    r"""Remove an item in the table."""
    if view.items is not None and (
        view.items.get_confirmation_message() == ""
        or tools.ask_confirmation(main_view, view.items.get_confirmation_message())
    ):
        new_selected_row: Optional[int] = None
        for row in sorted(view.items.get_selected_rows(), reverse=True):
            new_selected_row = view.items.remove(row)
        # remove the selection to force the update of the current indices
        # of the linked table
        view.items.set_selected_rows([])
        # update pagination
        # update the current page size to get the correct current page
        # the update of the current page need to be done before the update of the table
        # to display the correct rows for the new current page
        pagination.update_current_page_size(view=view.pagination_view, parent_view=view)
        if new_selected_row is None:
            view.items.page_navigator.set_current_page_from_row(0)
        else:
            view.items.page_navigator.set_current_page_from_row(new_selected_row)
        # update table
        tools.update_view_with_dependencies(view)
        # select eventually the position given by the remove method
        if new_selected_row is not None:
            view.items.set_selected_rows([new_selected_row])


def import_clicked(*, view: AnyTableView, main_view: MainView, model: AnyModel) -> None:
    """Import values from a csv file in the table."""
    if view.items is not None:
        is_cleaning = view.items.get_nb_rows() != 0 and tools.ask_confirmation(
            main_view, "Do you want to delete all the rows of the table before the import ?"
        )
        filepath, filepath_extension = selectfiles.select_table_file(
            main_view, view.import_extensions
        )
        if filepath is not None and filepath_extension is not None:
            task = ImportFileTableTask[AbstractTableItems[Any]](
                view.items, filepath, is_cleaning, filepath_extension
            )
            task.is_debug = model.is_debug
            progresspopup.display_view(
                main_view,
                tasks=Tasks((task,), print_to_std=True),
                finished_slots=[partial(tools.update_view_with_dependencies, view)],
            )
    else:
        tools.display_error_message(
            main_view,
            "The items of the table is not defined.",
        )


def export_clicked(*, view: AnyTableView, main_view: MainView, model: AnyModel) -> None:
    """Import values from a csv file in the table."""
    if view.items is not None:
        filepath, filepath_extension = selectfiles.save_table_file(
            main_view, view.export_extensions
        )
        if filepath is not None and filepath_extension is not None:
            task = ExportFileTableTask(view.items, filepath, filepath_extension)
            task.is_debug = model.is_debug
            progresspopup.display_view(main_view, Tasks((task,), print_to_std=True))


def clear_items(*, view: AnyTableView) -> None:
    """Clear the data of the selected items."""
    if view.items is not None:
        for rows, columns in view.selected_items.items():
            for column in columns:
                row = rows[-1]
                view.items.set_data(row, column, "")
        tools.update_view_with_dependencies(view)


def check_all_items(*, view: AnyTableView) -> None:
    """Un/Check all the items."""
    items = view.items
    if items is not None:
        nb_rows = items.get_nb_rows()
        nb_columns = items.get_nb_columns()
        for column in range(nb_columns):
            if all(items.is_checked(row, column) is not None for row in range(nb_rows)):
                all_checked = all(items.is_checked(row, column) for row in range(nb_rows))
                for row in range(nb_rows):
                    items.set_checked(row, column, not all_checked)
        tools.update_view_with_dependencies(view)
