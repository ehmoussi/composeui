from composeui.linkedtablefigure.qt.qtlinkedtablefigureview import QtLinkedTableFigureView
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.linkedtablefigureview.example import ExampleMainToolBar, ExampleMainView

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from examples.linkedtablefigureview.example import PointsItems


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, ExampleMainToolBar): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, ExampleMainView):
    toolbar: QtExampleMainToolBar = field(init=False)
    points: QtLinkedTableFigureView["PointsItems"] = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.toolbar = QtExampleMainToolBar(self.view)
        # points
        self.points = QtLinkedTableFigureView()
        self.central_layout.addWidget(self.points.view)
