from composeui.commontypes import AnyDetailTableItems, AnyMasterTableItems
from composeui.core.basesignal import BaseSignal
from composeui.core.views.view import View
from composeui.items.core.views.itemsview import FormatExtension
from composeui.items.table.tableview import TableGroupView
from composeui.items.tree.treeview import ExportTreeOptions

from dataclasses import dataclass, field
from typing import Generic


@dataclass(eq=False)
class LinkedTableView(View, Generic[AnyMasterTableItems, AnyDetailTableItems]):
    title: str = field(init=False, default="")
    has_import: bool = field(init=False, default=False)
    has_export: bool = field(init=False, default=False)
    import_clicked: BaseSignal = field(init=False, default=BaseSignal())
    export_clicked: BaseSignal = field(init=False, default=BaseSignal())
    master_table: TableGroupView[AnyMasterTableItems] = field(
        init=False, repr=False, default_factory=TableGroupView[AnyMasterTableItems]
    )
    detail_table: TableGroupView[AnyDetailTableItems] = field(
        init=False, repr=False, default_factory=TableGroupView[AnyDetailTableItems]
    )
    import_extensions: FormatExtension = field(
        init=False, default=FormatExtension.IMPORT_EXTENSIONS
    )
    export_extensions: FormatExtension = field(init=False, default=FormatExtension.ALL)
    export_options: ExportTreeOptions = field(init=False, default=ExportTreeOptions.EXPORT_ALL)
