from composeui.core import tools

from typing_extensions import TypeAlias

import typing
from typing import Any, Union

if typing.TYPE_CHECKING:
    from composeui.items.core.views.ipaginationview import PaginationView
    from composeui.items.table.abstracttableitems import AbstractTableItems
    from composeui.items.table.tableview import TableView
    from composeui.items.tree.abstracttreeitems import AbstractTreeItems
    from composeui.items.tree.treeview import TreeView

ITableTreeView: TypeAlias = Union[
    "TableView[AbstractTableItems[Any]]", "TreeView[AbstractTreeItems[Any]]"
]

# Positional only arguments are not available in python 3.6 and 3.7
# uncomment when the versions are not supported anymore
# def update_current_page_size(index: int, /, *, parent_view: ITableTreeView) -> bool:
#     assert parent_view.items is not None
#     return parent_view.items.page_navigator.update_current_page_size(index)


def update_current_page_size(*, view: "PaginationView", parent_view: ITableTreeView) -> bool:
    assert parent_view.items is not None
    return parent_view.items.page_navigator.update_current_page_size(
        view.current_page_size_index
    )


def update_status_buttons(*, view: "PaginationView", parent_view: ITableTreeView) -> None:
    assert parent_view.items is not None
    view.is_first_enabled = parent_view.items.page_navigator.can_move_backward()
    view.is_previous_enabled = parent_view.items.page_navigator.can_move_backward()
    view.is_next_enabled = parent_view.items.page_navigator.can_move_forward()
    view.is_last_enabled = parent_view.items.page_navigator.can_move_forward()


def move_to_first_page(*, parent_view: ITableTreeView) -> None:
    assert parent_view.items is not None
    parent_view.items.page_navigator.move_to_first_page()
    tools.update_view_with_dependencies(view=parent_view)


def move_to_previous_page(*, parent_view: ITableTreeView) -> None:
    assert parent_view.items is not None
    parent_view.items.page_navigator.move_to_previous_page()
    tools.update_view_with_dependencies(view=parent_view)


def move_to_next_page(*, parent_view: ITableTreeView) -> None:
    assert parent_view.items is not None
    parent_view.items.page_navigator.move_to_next_page()
    tools.update_view_with_dependencies(view=parent_view)


def move_to_last_page(*, parent_view: ITableTreeView) -> None:
    assert parent_view.items is not None
    parent_view.items.page_navigator.move_to_last_page()
    tools.update_view_with_dependencies(view=parent_view)


def update_row_summary(*, view: "PaginationView", parent_view: ITableTreeView) -> None:
    assert parent_view.items is not None
    view.row_summary = parent_view.items.page_navigator.get_row_summary()


def update_navigation_description(
    *, view: "PaginationView", parent_view: ITableTreeView
) -> None:
    assert parent_view.items is not None
    view.page_navigation_description = (
        parent_view.items.page_navigator.get_navigation_description()
    )


def update_page_size_values(*, view: "PaginationView", parent_view: ITableTreeView) -> None:
    assert parent_view.items is not None
    page_size_values = list(parent_view.items.page_navigator.iter_page_sizes())
    if page_size_values != view.page_size_values:
        view.page_size_values = page_size_values
