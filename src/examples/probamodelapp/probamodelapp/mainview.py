from composeui.mainview.views.mainview import MainView


class ProbaModelMainView(MainView):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.title = "ProbaModelApp"
