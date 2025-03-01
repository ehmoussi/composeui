from composeui.commontypes import AnyTableItems
from composeui.core.views.iview import IView
from composeui.figure.ifigureview import IFigureView
from composeui.items.table.itableview import ITableView

from dataclasses import dataclass, field
from typing import Generic


@dataclass(eq=False)
class ILinkedTableFigureView(IView, Generic[AnyTableItems]):
    table: ITableView[AnyTableItems] = field(init=False, default_factory=ITableView)
    figure: IFigureView = field(init=False, default_factory=IFigureView)
    label: int = field(init=False, default=0)
    x: int = field(init=False, default=1)
    y: int = field(init=False, default=2)
