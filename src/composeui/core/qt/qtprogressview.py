r"""Computation cases runner view."""

from composeui.core.qt.qtworkerview import QtWorkerView
from composeui.core.tasks.abstracttask import AbstractTask
from composeui.core.views.progressview import ProgressView

from qtpy.QtWidgets import QHBoxLayout, QProgressBar, QPushButton, QWidget

from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T", bound=AbstractTask)


@dataclass(eq=False)
class QtProgressView(QtWorkerView[T], ProgressView[T]):
    r"""View of a progress bar and run button to execute a task in background."""

    view: QWidget = field(init=False, repr=False, default_factory=QWidget)

    progress_bar: QProgressBar = field(init=False, repr=False, default_factory=QProgressBar)
    run_button: QPushButton = field(init=False, repr=False, default_factory=QPushButton)

    def __post_init__(self) -> None:
        super().__post_init__()
        layout = QHBoxLayout()
        self.view.setLayout(layout)
        # -- progress bar
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        layout.addWidget(self.progress_bar)
        # -- run button
        layout.addWidget(self.run_button)
        # assign signals
        self.button_clicked.add_qt_signals((self.run_button, self.run_button.clicked))

    @property  # type: ignore[misc]
    def is_percentage_visible(self) -> bool:
        return self.progress_bar.isTextVisible()

    @is_percentage_visible.setter
    def is_percentage_visible(self, is_percentage_visible: bool) -> None:
        self.progress_bar.setTextVisible(is_percentage_visible)

    @property  # type: ignore[misc]
    def minimum(self) -> int:
        return self.progress_bar.minimum()

    @minimum.setter
    def minimum(self, minimum: int) -> None:
        self.progress_bar.setMinimum(minimum)

    @property  # type: ignore[misc]
    def maximum(self) -> int:
        return self.progress_bar.maximum()

    @maximum.setter
    def maximum(self, maximum: int) -> None:
        self.progress_bar.setMaximum(maximum)

    @property  # type: ignore[misc]
    def value(self) -> int:
        return self.progress_bar.value()

    @value.setter
    def value(self, value: int) -> None:
        self.progress_bar.setValue(value)

    @property  # type: ignore[misc]
    def button_text(self) -> str:
        return self.run_button.text()

    @button_text.setter
    def button_text(self, button_text: str) -> None:
        self.run_button.setText(button_text)
        self.run_button.setToolTip(button_text)

    @property  # type: ignore[misc]
    def button_enabled(self) -> bool:
        return self.run_button.isEnabled()

    @button_enabled.setter
    def button_enabled(self, button_enabled: bool) -> None:
        self.run_button.setEnabled(button_enabled)
