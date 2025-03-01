from composeui.commontypes import AnyModel
from composeui.items.simpletable.simpletableitems import SimpleTableItems
from composeui.items.table.itableview import ITableView

from dataclasses import dataclass, field
from typing import Generic, Optional


@dataclass(eq=False)
class ISimpleTableView(ITableView[SimpleTableItems[AnyModel]], Generic[AnyModel]):
    items: Optional[SimpleTableItems[AnyModel]] = field(init=False, default=None)
