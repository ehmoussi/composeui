from composeui.commontypes import AnyModel
from composeui.items.simpletable.simpletableitems import SimpleTableItems
from composeui.items.table.itableview import TableView

from dataclasses import dataclass, field
from typing import Generic, Optional


@dataclass(eq=False)
class SimpleTableView(TableView[SimpleTableItems[AnyModel]], Generic[AnyModel]):
    items: Optional[SimpleTableItems[AnyModel]] = field(init=False, default=None)
