from composeui.linkedtablefigure.qt.linkedtablefigureview import LinkedTableFigureView
from composeui.mainview.qt.maintoolbar import MainToolBar
from composeui.mainview.qt.mainview import MainView
from examples.linkedtablefigureview.example import IExampleMainToolBar, IExampleMainView

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from examples.linkedtablefigureview.example import PointsItems


@dataclass(eq=False)
class ExampleMainToolBar(MainToolBar, IExampleMainToolBar): ...


@dataclass(eq=False)
class ExampleMainView(MainView, IExampleMainView):
    toolbar: ExampleMainToolBar = field(init=False)
    points: LinkedTableFigureView["PointsItems"] = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.toolbar = ExampleMainToolBar(self.view)
        # points
        self.points = LinkedTableFigureView()
        self.central_layout.addWidget(self.points.view)
