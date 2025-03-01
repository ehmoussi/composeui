from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.basemodel import BaseModel
from examples.multipleviews.component1.view1 import initialize_component1
from examples.multipleviews.component2.view2 import initialize_component2
from examples.multipleviews.component3.view3 import initialize_component3
from examples.multipleviews.example import IExampleMainView, initialize_dockviews


class MultipleViewsApp(QtBaseApp[IExampleMainView, BaseModel]):
    def __init__(self, main_view: IExampleMainView) -> None:
        super().__init__(BaseModel("example", get_version("composeui")), main_view)

    def initialize_app(self) -> None:
        initialize_dockviews(self.main_view)
        initialize_component1(
            self.main_view.toolbar.navigation.view_1,
            self.main_view.view_1,
            self.main_view.left_dock.view_1,
            self.main_view,
        )
        initialize_component2(
            self.main_view.toolbar.navigation.view_2,
            self.main_view.view_2,
            self.main_view.right_dock.view_2,
            self.main_view,
        )
        initialize_component3(
            self.main_view.toolbar.navigation.view_3,
            self.main_view.view_3,
            self.main_view,
        )

    def connect_app(self) -> None: ...
