r"""View of an action."""

from composeui.core.qt.qtview import QtView
from composeui.core.views.actionview import ActionView

from qtpy.QtGui import QIcon, QKeySequence
from qtpy.QtWidgets import QAction

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtActionView(QtView, ActionView):
    r"""View of an action."""

    view: QAction = field(init=False)
    _icon_filepath: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.view = QAction()
        self._icon_filepath = ""
        # assign signals
        self.triggered.add_qt_signals((self.view, self.view.triggered))
        self.toggled.add_qt_signals((self.view, self.view.toggled))
        self.changed.add_qt_signals((self.view, self.view.changed))

    @property  # type: ignore[misc]
    def data(self) -> str:
        return str(self.view.data())

    @data.setter
    def data(self, data: str) -> None:
        self.view.setData(data)

    @property  # type: ignore[misc]
    def text(self) -> str:
        return str(self.view.text())

    @text.setter
    def text(self, text: str) -> None:
        self.view.setText(text)

    @property  # type: ignore[misc]
    def icon(self) -> str:
        return self._icon_filepath

    @icon.setter
    def icon(self, filepath: str) -> None:
        self._icon_filepath = filepath
        self.view.setIcon(QIcon(f":/icons/{filepath}"))

    @property  # type: ignore[misc]
    def is_separator(self) -> bool:
        return bool(self.view.isSeparator())

    @is_separator.setter
    def is_separator(self, is_separator: bool) -> None:
        self.view.setSeparator(is_separator)

    @property  # type: ignore[misc]
    def is_checkable(self) -> bool:
        return bool(self.view.isCheckable())

    @is_checkable.setter
    def is_checkable(self, is_checkable: bool) -> None:
        self.view.setCheckable(is_checkable)

    @property  # type: ignore[misc]
    def is_checked(self) -> bool:
        return bool(self.view.isChecked())

    @is_checked.setter
    def is_checked(self, is_checked: bool) -> None:
        self.view.setChecked(is_checked)

    @property  # type: ignore[misc]
    def shortcut(self) -> str:
        return str(self.view.shortcut().toString())

    @shortcut.setter
    def shortcut(self, shortcut: str) -> None:
        self.view.setShortcut(QKeySequence(shortcut))
