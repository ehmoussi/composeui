from typing import Any

from qtpy.QtWidgets import QHBoxLayout, QLabel, QWidget


class QFormLabel(QWidget):
    """A form row's label, then a "?" whose tooltip is the row's help, if it has any."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text_label = QLabel()
        layout.addWidget(self.text_label)
        self.help_label = QLabel("?")
        self.help_label.setVisible(False)
        layout.addWidget(self.help_label)
        # both packed at the start, the "?" right after the text
        layout.addStretch()

    def text(self) -> str:
        return self.text_label.text()

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)

    def help(self) -> str:
        return self.help_label.toolTip()

    def set_help(self, text: str) -> None:
        # on the whole label: hovering its text shows the help too
        self.setToolTip(text)
        self.help_label.setToolTip(text)
        self.help_label.setVisible(text != "")
