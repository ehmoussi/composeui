from composeui.commontypes import AnyTableItems
from composeui.core.views.iview import IGroupView
from composeui.items.core.views.iitemsview import IItemsView

from dataclasses import dataclass, field
from typing import Generic, Optional


@dataclass(eq=False)
class ITableView(IItemsView, Generic[AnyTableItems]):
    items: Optional[AnyTableItems] = field(init=False, default=None)


@dataclass(eq=False)
class ITableGroupView(ITableView[AnyTableItems], IGroupView): ...
