from composeui.salomewrapper.core.qt.qtsalomeview import QtSalomeView

from qtpy.QtWidgets import QVBoxLayout, QWidget

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtSalomeCentralView(QtSalomeView):
    view: QWidget = field(init=False)
    layout: QVBoxLayout = field(init=False)

    def __post_init__(self) -> None:
        self.view = QWidget()
        self.layout = QVBoxLayout()
        self.view.setLayout(self.layout)
        super().__post_init__()
