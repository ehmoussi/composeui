from composeui.salomewrapper.core.qt.salomeview import SalomeView

from qtpy.QtWidgets import QVBoxLayout, QWidget

from dataclasses import dataclass, field


@dataclass(eq=False)
class SalomeCentralView(SalomeView):
    view: QWidget = field(init=False)
    layout: QVBoxLayout = field(init=False)

    def __post_init__(self) -> None:
        self.view = QWidget()
        self.layout = QVBoxLayout()
        self.view.setLayout(self.layout)
        super().__post_init__()
