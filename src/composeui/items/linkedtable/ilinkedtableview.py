from composeui.commontypes import AnyDetailTableItems, AnyMasterTableItems
from composeui.core.basesignal import BaseSignal
from composeui.core.views.iview import IView
from composeui.items.core.views.iitemsview import FormatExtension
from composeui.items.table.itableview import ITableGroupView
from composeui.items.tree.itreeview import ExportTreeOptions

from dataclasses import dataclass, field
from typing import Generic


@dataclass(eq=False)
class ILinkedTableView(IView, Generic[AnyMasterTableItems, AnyDetailTableItems]):
    title: str = field(init=False, default="")
    has_import: bool = field(init=False, default=False)
    has_export: bool = field(init=False, default=False)
    import_clicked: BaseSignal = field(init=False, default=BaseSignal())
    export_clicked: BaseSignal = field(init=False, default=BaseSignal())
    master_table: ITableGroupView[AnyMasterTableItems] = field(
        init=False, default_factory=ITableGroupView[AnyMasterTableItems]
    )
    detail_table: ITableGroupView[AnyDetailTableItems] = field(
        init=False, default_factory=ITableGroupView[AnyDetailTableItems]
    )
    import_extensions: FormatExtension = field(
        init=False, default=FormatExtension.IMPORT_EXTENSIONS
    )
    export_extensions: FormatExtension = field(init=False, default=FormatExtension.ALL)
    export_options: ExportTreeOptions = field(init=False, default=ExportTreeOptions.EXPORT_ALL)
