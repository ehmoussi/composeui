from composeui.commontypes import AnyModel
from composeui.core import tools
from composeui.items.core.copypasteitems import CopyPasteItems
from composeui.mainview.views.imainview import MainView

from typing_extensions import TypeAlias

import traceback
import typing
from typing import Any, Union

if typing.TYPE_CHECKING:
    from composeui.items.table.abstracttableitems import AbstractTableItems
    from composeui.items.table.itableview import TableView
    from composeui.items.tree.abstracttreeitems import AbstractTreeItems
    from composeui.items.tree.itreeview import TreeView


ITableTreeView: TypeAlias = Union[
    "TableView[AbstractTableItems[Any]]", "TreeView[AbstractTreeItems[Any]]"
]


def copy_items(*, view: ITableTreeView) -> None:
    """Copy the data of the selected items."""
    if view.items is not None:
        copy_paste_manager = CopyPasteItems(view.items)
        copy_paste_manager.copy()


def paste_items(*, view: ITableTreeView, main_view: MainView, model: AnyModel) -> None:
    """Paste the data of the selected items."""
    if view.items is not None and not is_sorting_enabled(view, main_view):
        copy_paste_manager = CopyPasteItems(view.items)
        try:
            copy_paste_manager.paste()
        except ValueError as e:
            error_message = str(e)
            if model.is_debug:
                error_message += "\n" + traceback.format_exc()
            tools.display_error_message(main_view, error_message)
        else:
            view.failed_highlight(copy_paste_manager.paste_failed)
            view.successful_highlight(copy_paste_manager.paste_successful)
            tools.update_view_with_dependencies(view)


def is_sorting_enabled(view: ITableTreeView, main_view: MainView) -> bool:
    r"""Check if the sorting is enabled."""
    is_enabled = view.sorting_enabled
    if view.sorting_enabled:
        tools.display_error_message(
            main_view, "The copy/paste is not available when the sorting is enabled."
        )
    return is_enabled


def update_filter_pattern(*, view: ITableTreeView) -> None:
    r"""Update the filter configuration of the given table view."""
    filter_view = view.filter_view
    # the filter is visible only if the filter button is checked
    filter_view.is_visible = view.is_filtered
    if view.items is not None:
        # update the options selected
        view.items.filter_manager.match_case = filter_view.match_case
        view.items.filter_manager.match_whole_word = filter_view.match_whole_word
        view.items.filter_manager.use_regex = filter_view.use_regex
        # column indices
        view.items.filter_column_indices = filter_view.selected_column_indices
        # update the pattern of the filter
        if view.is_filtered:
            view.items.filter_manager.pattern = filter_view.text
            if not view.items.filter_manager.is_regex_valid:
                filter_view.info_text = "The pattern is not valid"
            elif not view.items.filter_manager.is_comparison_valid:
                filter_view.info_text = "Misuse of operators {'>=', '<=', '>', '<'}"
            else:
                filter_view.info_text = ""
        else:
            view.items.filter_manager.pattern = ""
        # update the table
        tools.update_view_with_dependencies(view)
