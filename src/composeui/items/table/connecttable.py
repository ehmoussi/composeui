from composeui.items.core import itemsslots
from composeui.items.core.connect import connect_pagination
from composeui.items.table import table
from composeui.items.table.tableview import TableView

from typing import Any


def connect_table(view: TableView[Any]) -> bool:
    r"""Connect the slots for the table view."""
    view.shortcut_add = [table.add_clicked]
    view.shortcut_delete = [table.remove_clicked]
    view.shortcut_clear = [table.clear_items]
    view.shortcut_paste = [itemsslots.paste_items]
    view.shortcut_copy = [itemsslots.copy_items]
    view.filter_changed = [itemsslots.update_filter_pattern]
    view.filter_view.filter_changed = [itemsslots.update_filter_pattern]
    view.check_all = [table.check_all_items]
    view.import_clicked = [table.import_clicked]
    view.export_clicked = [table.export_clicked]
    view.add_clicked = [table.add_clicked]
    view.remove_clicked = [table.remove_clicked]
    connect_pagination(view=view.pagination_view, parent_view=view)
    return False
