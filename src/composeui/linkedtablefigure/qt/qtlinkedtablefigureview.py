from composeui.commontypes import AnyTableItems
from composeui.core.qt.qtview import QtView
from composeui.figure.qtfigureview import QtFigureView
from composeui.items.table.qt.qttableview import QtTableView
from composeui.linkedtablefigure.linkedtablefigureview import LinkedTableFigureView

from qtpy.QtWidgets import QSplitter

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtLinkedTableFigureView(QtView, LinkedTableFigureView[AnyTableItems]):
    view: QSplitter = field(init=False, repr=False)
    table: QtTableView[AnyTableItems] = field(init=False, repr=False)
    figure: QtFigureView = field(init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = QSplitter()
        self.table = QtTableView()
        self.view.addWidget(self.table.view)
        self.view.setStretchFactor(0, 3)
        self.figure = QtFigureView()
        self.figure.view.setMinimumWidth(400)
        self.view.addWidget(self.figure.view)
        self.view.setStretchFactor(1, 2)
