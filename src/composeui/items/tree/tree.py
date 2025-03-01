from composeui.commontypes import AnyModel
from composeui.core import selectfiles, tools
from composeui.core.tasks.tasks import Tasks
from composeui.items.core import pagination
from composeui.items.tree.abstracttreeitems import AbstractTreeItems
from composeui.items.tree.exportfiletreetask import ExportFileTreeTask
from composeui.items.tree.importfiletreetask import ImportFileTreeTask
from composeui.items.tree.itreeview import ExportTreeOptions, TreeView
from composeui.mainview import progresspopup
from composeui.mainview.views.imainview import MainView

from typing_extensions import TypeAlias

from collections import defaultdict
from functools import partial
from typing import Any, Dict, List, Optional, Sequence, Tuple

AnyTreeView: TypeAlias = TreeView[AbstractTreeItems[Any]]


def import_clicked(*, view: AnyTreeView, main_view: MainView, model: AnyModel) -> None:
    """Import values from a csv file in the tree."""
    if view.items is not None:
        if view.items.get_nb_rows() == 0:
            is_cleaning = False
        else:
            is_cleaning = tools.ask_confirmation(main_view, "Do you want to clean the table ?")
        filepath, filepath_extension = selectfiles.select_table_file(
            main_view, view.import_extensions
        )
        if filepath is not None and filepath_extension is not None:
            task = ImportFileTreeTask(view.items, filepath, is_cleaning, filepath_extension)
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


def export_clicked(*, view: AnyTreeView, main_view: MainView, model: AnyModel) -> None:
    """Export values of the tree to a csv/excel/markdown/html file."""
    if view.items is not None:
        filepath, filepath_extension = selectfiles.save_table_file(
            main_view, view.export_extensions
        )
        if filepath is not None and filepath_extension is not None:
            if (
                ExportTreeOptions.EXPORT_ASK in view.export_options
                and len(view.selected_items) > 0
            ):
                export_only_from_selection = tools.ask_confirmation(
                    main_view, "Export only from the current selection ?"
                )
            else:
                export_only_from_selection = (
                    ExportTreeOptions.EXPORT_ONLY_SELECTION in view.export_options
                )
            if export_only_from_selection:
                selected_positions = view.items.get_selected_positions()
            else:
                selected_positions = []
            task = ExportFileTreeTask(
                view.items,
                selected_positions,
                filepath,
                filepath_extension,
                view.export_options,
            )
            task.is_debug = model.is_debug
            progresspopup.display_view(main_view, Tasks((task,), print_to_std=True))


def add_clicked(*, view: AnyTreeView) -> None:
    r"""Add an item in the table."""
    if view.items is not None:
        selected_positions = view.items.get_selected_positions()
        parent_rows: Sequence[int]
        if len(selected_positions) > 0:
            parent_rows = selected_positions[-1]
        else:
            parent_rows = ()
        if len(parent_rows) == (view.items.depth + 1):
            *parent_rows, row = parent_rows
        else:
            row = view.items.get_nb_rows(parent_rows) - 1
        position = view.items.insert(row + 1, tuple(parent_rows))
        view.items.set_expanded(row + 1, True, tuple(parent_rows))
        # update the pagination
        # update the current page size to get the correct current page
        # the update of the current page need to be done before the update of the table
        # to display the correct rows for the new current page
        pagination.update_current_page_size(view=view.pagination_view, parent_view=view)
        if position is not None:
            view.items.page_navigator.set_current_page_from_row(position[0])
        elif len(parent_rows) > 0:
            view.items.page_navigator.set_current_page_from_row(parent_rows[0])
        else:
            view.items.page_navigator.set_current_page_from_row(row + 1)
        # update the tree
        tools.update_view_with_dependencies(view)
        # update the selection
        if position is not None and position != ():
            view.items.set_selected_positions([tuple(position)])
        else:
            view.items.set_selected_positions(selected_positions)


def remove_clicked(*, view: AnyTreeView, main_view: MainView) -> None:
    r"""Remove an item in the tree."""
    if view.items is not None and (
        view.items.get_confirmation_message() == ""
        or tools.ask_confirmation(main_view, view.items.get_confirmation_message())
    ):
        position: Optional[Tuple[int, ...]] = None
        positions: Dict[Sequence[int], List[int]] = defaultdict(list)
        parent_rows: Sequence[int]
        for *parent_rows, row in sorted(
            view.items.get_selected_positions(), key=lambda p: len(p), reverse=True
        ):
            positions[tuple(parent_rows)].append(row)
        for parent_rows, rows in positions.items():
            for row in sorted(rows, reverse=True):
                position = view.items.remove(row, tuple(parent_rows))
        # remove the selection to force the update of the current indices
        # of the linked tables
        view.items.set_selected_positions([])
        # update the pagination
        # update the current page size to get the correct current page
        # the update of the current page need to be done before the update of the table
        # to display the correct rows for the new current page
        pagination.update_current_page_size(view=view.pagination_view, parent_view=view)
        if position is not None:
            view.items.page_navigator.set_current_page_from_row(position[0])
        else:
            view.items.page_navigator.set_current_page_from_row(0)
        # update the tree
        tools.update_view_with_dependencies(view)
        # select eventually the position given by the remove method
        if position is not None:
            view.items.set_selected_positions([position])


def clear_items(*, view: AnyTreeView) -> None:
    """Clear the data of the selected items."""
    items = view.items
    if items is not None:
        selected_items = view.selected_items
        for rows, columns in selected_items.items():
            for column in columns:
                row = rows[-1]
                parent_rows = rows[:-1]
                items.set_data(row, column, "", parent_rows)
        tools.update_view_with_dependencies(view)


def check_all_items(*, view: AnyTreeView) -> None:
    r"""Un/Check all the items."""
    # TODO: Update to manage the trees properly
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
