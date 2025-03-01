from composeui.commontypes import AnyTreeItems
from composeui.core.views.iview import GroupView
from composeui.items.core.views.iitemsview import ItemsView

import enum
from dataclasses import dataclass, field
from typing import Generic, Optional


class ExportTreeOptions(enum.Flag):
    EXPORT_ALL = 1
    EXPORT_ONLY_SELECTION = 2
    # Ask to choose between exporting all or according to the current selection
    EXPORT_ASK = EXPORT_ALL | EXPORT_ONLY_SELECTION
    # Use the parent as the sheet names
    USE_PARENT_SHEET_NAMES = 4
    ALL_WITH_PARENT_SHEET_NAMES = EXPORT_ALL | USE_PARENT_SHEET_NAMES
    SELECTION_WITH_PARENT_SHEET_NAMES = EXPORT_ONLY_SELECTION | USE_PARENT_SHEET_NAMES
    ASK_WITH_PARENT_SHEET_NAMES = EXPORT_ASK | USE_PARENT_SHEET_NAMES


@dataclass(eq=False)
class TreeView(ItemsView, Generic[AnyTreeItems]):
    items: Optional[AnyTreeItems] = field(init=False, default=None)
    is_expansion_animated: bool = field(init=False, default=False)
    export_options: ExportTreeOptions = field(init=False, default=ExportTreeOptions.EXPORT_ALL)


@dataclass(eq=False)
class TreeGroupView(TreeView[AnyTreeItems], GroupView): ...
