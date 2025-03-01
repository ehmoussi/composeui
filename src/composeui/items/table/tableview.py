from composeui.commontypes import AnyTableItems
from composeui.core.views.view import GroupView
from composeui.items.core.views.itemsview import ItemsView

from dataclasses import dataclass, field
from typing import Generic, Optional


@dataclass(eq=False)
class TableView(ItemsView, Generic[AnyTableItems]):
    items: Optional[AnyTableItems] = field(init=False, default=None)


@dataclass(eq=False)
class TableGroupView(TableView[AnyTableItems], GroupView): ...
