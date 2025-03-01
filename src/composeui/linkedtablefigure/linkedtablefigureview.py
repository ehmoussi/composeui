from composeui.commontypes import AnyTableItems
from composeui.core.views.view import View
from composeui.figure.figureview import FigureView
from composeui.items.table.tableview import TableView

from dataclasses import dataclass, field
from typing import Generic


@dataclass(eq=False)
class LinkedTableFigureView(View, Generic[AnyTableItems]):
    table: TableView[AnyTableItems] = field(init=False, default_factory=TableView)
    figure: FigureView = field(init=False, default_factory=FigureView)
    label: int = field(init=False, default=0)
    x: int = field(init=False, default=1)
    y: int = field(init=False, default=2)
