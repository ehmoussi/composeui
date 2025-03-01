"""View to Select File View."""

from composeui.core.interfaces.iselectpathview import ISelectPathView
from composeui.core.qt.view import View

from qtpy.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from dataclasses import dataclass, field


@dataclass(eq=False)
class SelectPathView(View, ISelectPathView):
    view: QWidget = field(init=False, default_factory=QWidget)

    _label: QLabel = field(init=False, default_factory=QLabel)
    _file_name_lineedit: QLineEdit = field(init=False, default_factory=QLineEdit)
    _button: QPushButton = field(init=False, default_factory=QPushButton)

    def __post_init__(self) -> None:
        super().__post_init__()
        layout = QHBoxLayout()
        self.view.setLayout(layout)
        # label
        layout.addWidget(self._label)
        # lineedit
        self._file_name_lineedit.setReadOnly(self.is_read_only)
        layout.addWidget(self._file_name_lineedit)
        # button
        layout.addWidget(self._button)
        # assign signal
        self.select_clicked.add_qt_signals((self._button, self._button.clicked))

    @property  # type: ignore[misc]
    def label(self) -> str:
        return self._label.text()

    @label.setter
    def label(self, label: str) -> None:
        self._label.setText(label)

    @property  # type: ignore[misc]
    def is_read_only(self) -> bool:
        return self._file_name_lineedit.isReadOnly()

    @is_read_only.setter
    def is_read_only(self, is_read_only: bool) -> None:
        self._file_name_lineedit.setReadOnly(is_read_only)

    @property  # type: ignore[misc]
    def button_name(self) -> str:
        return self._button.text()

    @button_name.setter
    def button_name(self, button_name: str) -> None:
        self._button.setText(button_name)

    @property  # type: ignore[misc]
    def path(self) -> str:
        return self._file_name_lineedit.text()

    @path.setter
    def path(self, path: str) -> None:
        self._file_name_lineedit.setText(path)
