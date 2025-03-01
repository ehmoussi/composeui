"""Table/Tree component.

Contains the table and the tree components and its derivatives.

    - TableView: A table which needs a class inherited of AbstractTableItems
    - SimpleTableView: A table that works with SqliteModel/SqliteData and implements directly
        an items using the name of a table defined in the sqlite database of SqliteData.
    - LinkedTableView: Two tables that works together to display complex data.
        The first table is the master table the selection of an item in the master table
        update the contents automatically of the second table called detail table.
        Each of the tables need to implement its own AbstractTableItems.
"""

from composeui.items.core import itemsslots
from composeui.items.core.connect import connect_pagination
from composeui.items.table import table
from composeui.items.table.itableview import ITableView

from typing import Any


def connect_table(view: ITableView[Any]) -> bool:
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
