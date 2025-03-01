r"""View for a worker progress."""

from composeui.core.qt.qtworkerview import QtWorkerView
from composeui.core.qt.widgets.progressdialog import ProgressDialog
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.mainview.views.progresspopupview import ProgressPopupView

from qtpy.QtWidgets import QWidget

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtProgressPopupView(QtWorkerView[AbstractTask], ProgressPopupView):
    r"""View for the worker progress."""

    view: ProgressDialog = field(init=False)
    parent: QWidget

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = ProgressDialog(self.parent)
        self.view.setModal(True)
        self.worker.progress.connect(self.view.setValue)
        self.worker.finished.connect(self.view.close)

    def run(self) -> None:
        r"""Run the task."""
        self.view.canceled.connect(self.worker.cancel)
        self.view.show()
        super().run()

    @property  # type: ignore[misc]
    def title(self) -> str:
        return str(self.view.windowTitle())

    @title.setter
    def title(self, value: str) -> None:
        self.view.setWindowTitle(value)

    @property  # type: ignore[misc]
    def label_text(self) -> str:
        return str(self.view.labelText())

    @label_text.setter
    def label_text(self, value: str) -> None:
        self.view.setLabelText(value)

    @property  # type: ignore[misc]
    def is_percentage_visible(self) -> bool:
        return self.view.is_percentage_visible

    @is_percentage_visible.setter
    def is_percentage_visible(self, value: bool) -> None:
        self.view.is_percentage_visible = value

    @property  # type: ignore[misc]
    def minimum(self) -> int:
        return int(self.view.minimum())

    @minimum.setter
    def minimum(self, value: int) -> None:
        self.view.setMinimum(value)

    @property  # type: ignore[misc]
    def maximum(self) -> int:
        return int(self.view.maximum())

    @maximum.setter
    def maximum(self, value: int) -> None:
        self.view.setMaximum(value)

    @property  # type: ignore[misc]
    def value(self) -> int:
        return int(self.view.value())

    @value.setter
    def value(self, value: int) -> None:
        self.view.setValue(value)
