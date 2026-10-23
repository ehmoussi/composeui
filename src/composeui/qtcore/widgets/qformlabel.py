from __future__ import annotations

from typing import Any

from qtpy.QtCore import QPoint
from qtpy.QtWidgets import QHBoxLayout, QToolButton, QToolTip, QWidget

from composeui.qtcore.widgets.qplaintext import plain_label, plain_tool_tip


class QFormLabel(QWidget):
    """A form row's label, then a "?" button showing the row's help, if it has any.

    Hovering shows the help as a tooltip; clicking the button, or Space once Tab reached
    it, shows it too, for a touch screen or the keyboard.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text_label = plain_label()
        layout.addWidget(self.text_label)
        self._help = ""
        self.help_button = QToolButton()
        self.help_button.setText("?")
        self.help_button.setAutoRaise(True)
        self.help_button.setVisible(False)
        self.help_button.clicked.connect(self.show_help)
        layout.addWidget(self.help_button)
        # both packed at the start, the "?" right after the text
        layout.addStretch()

    def text(self) -> str:
        return self.text_label.text()

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)

    def help(self) -> str:
        return self._help

    def set_help(self, text: str) -> None:
        # on the whole label: hovering its text shows the help too
        self._help = text
        self.setToolTip(plain_tool_tip(text))
        self.help_button.setToolTip(plain_tool_tip(text))
        self.help_button.setVisible(text != "")

    def set_help_button_text(self, text: str) -> None:
        self.help_button.setAccessibleName(text)

    def show_help(self) -> None:
        """Show the help under the button, as hovering it would."""
        below = self.help_button.mapToGlobal(QPoint(0, self.help_button.height()))
        QToolTip.showText(below, plain_tool_tip(self.help()), self.help_button)
