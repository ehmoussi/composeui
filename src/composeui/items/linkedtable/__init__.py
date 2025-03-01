from composeui.commontypes import AnyDetailTableItems, AnyMasterTableItems
from composeui.items.core.initialize import initialize_items_view
from composeui.items.core.views.iitemsview import FormatExtension
from composeui.items.linkedtable import linkedtable
from composeui.items.linkedtable.ilinkedtableview import LinkedTableView
from composeui.items.table import connect_table
from composeui.items.table.itableview import TableGroupView
from composeui.items.tree.itreeview import ExportTreeOptions

from functools import partial

# IMTa = TypeVar("IMTa", bound=AbstractTableItems[Any])
# IDTa = TypeVar("IDTa", bound=AbstractTableItems[Any])


def initialize_linked_table(
    view: LinkedTableView[AnyMasterTableItems, AnyDetailTableItems],
) -> bool:
    r"""Initialize the select/modify view."""
    view.title = ""
    view.has_import = False
    view.has_export = False
    view.import_extensions = FormatExtension.IMPORT_EXTENSIONS
    view.export_extensions = FormatExtension.ALL
    view.export_options = ExportTreeOptions.EXPORT_ALL
    initialize_items_view(view.master_table)
    initialize_items_view(view.detail_table)
    view.master_table.has_add = True
    view.master_table.has_remove = True
    view.master_table.dependencies.append(view.detail_table)
    view.detail_table.has_add = True
    view.detail_table.has_remove = True
    view.detail_table.is_enabled = False
    return False


def connect_linked_table_view(
    table: LinkedTableView[AnyMasterTableItems, AnyDetailTableItems],
) -> bool:
    table.import_clicked = [linkedtable.import_clicked]
    table.export_clicked = [linkedtable.export_clicked]
    return False


def connect_linked_table(
    master_table: TableGroupView[AnyMasterTableItems],
    detail_table: TableGroupView[AnyDetailTableItems],
) -> bool:
    r"""Connect the callbacks for two linked tables."""
    master_table.selection_changed = [
        [
            partial(linkedtable.update_status_detail_table, detail_table),
            partial(linkedtable.update_title_detail_table, detail_table),
        ]
    ]
    connect_table(master_table)
    connect_table(detail_table)
    return False
