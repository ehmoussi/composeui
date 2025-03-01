from composeui.commontypes import AnyTableItems
from composeui.core.qt.view import View
from composeui.figure.figureview import FigureView
from composeui.items.table.qt.tableview import TableView
from composeui.linkedtablefigure.ilinkedtablefigureview import ILinkedTableFigureView

from qtpy.QtWidgets import QSplitter

from dataclasses import dataclass, field


@dataclass(eq=False)
class LinkedTableFigureView(View, ILinkedTableFigureView[AnyTableItems]):
    view: QSplitter = field(init=False)
    table: TableView[AnyTableItems] = field(init=False)
    figure: FigureView = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = QSplitter()
        self.table = TableView()
        self.view.addWidget(self.table.view)
        self.view.setStretchFactor(0, 3)
        self.figure = FigureView()
        self.figure.view.setMinimumWidth(400)
        self.view.addWidget(self.figure.view)
        self.view.setStretchFactor(1, 2)
