from composeui.core import tools
from composeui.items.core import pagination
from composeui.items.core.views.iitemsview import IItemsView
from composeui.items.core.views.ipaginationview import IPaginationView

from functools import partial


def connect_pagination(*, view: IPaginationView, parent_view: IItemsView) -> bool:
    view.size_changed = [
        pagination.update_page_size_values,
        pagination.update_status_buttons,
        pagination.update_row_summary,
        pagination.update_navigation_description,
    ]
    view.current_page_changed = [
        pagination.update_status_buttons,
        pagination.update_row_summary,
        pagination.update_navigation_description,
    ]
    view.current_page_size_changed = [
        [
            pagination.update_current_page_size,
            partial(tools.update_view_with_dependencies, view=parent_view),
        ]
    ]
    view.first_clicked += [pagination.move_to_first_page]
    view.previous_clicked += [pagination.move_to_previous_page]
    view.next_clicked += [pagination.move_to_next_page]
    view.last_clicked += [pagination.move_to_last_page]
    return False
