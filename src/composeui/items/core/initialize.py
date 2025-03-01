from composeui.items.core.iitemsview import FormatExtension, IItemsView
from composeui.items.core.ipaginationview import IPaginationView

from collections import OrderedDict


def initialize_items_view(view: IItemsView) -> bool:
    """Initialize the table/tree view."""
    view.has_add = False
    view.has_remove = False
    view.is_single_selection = False
    view.can_select_items = False
    view.has_focus = False
    view.has_context_menu = False
    view.has_check_all = False
    view.sorting_enabled = False
    view.is_filtered = False
    view.drag_drop_enabled = False
    view.help_text = (
        "Add        Ctrl + Alt + N\n"
        "Delete    Del\n"
        "Clear      Ctrl + Del\n"
        "Copy      Ctrl + C\n"
        "Paste     Ctrl + V"
    )
    view.import_extensions = FormatExtension.IMPORT_EXTENSIONS
    view.export_extensions = FormatExtension.ALL
    view.selected_items = OrderedDict()
    # filter view
    view.filter_view.text = ""
    view.filter_view.info_text = ""
    view.filter_view.match_case = False
    view.filter_view.match_whole_word = False
    view.filter_view.use_regex = False
    initialize_pagination(view.pagination_view)
    return False


def initialize_pagination(view: IPaginationView) -> bool:
    view.is_first_enabled = False
    view.is_previous_enabled = False
    view.is_next_enabled = False
    view.is_last_enabled = False
    view.row_summary = "0 to 0 of 0"
    view.page_navigation_description = "Page 0 of 0"
    return False
