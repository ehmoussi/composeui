r"""Message view."""

from composeui.core.qt.qtview import QtView
from composeui.mainview.interfaces.imessageview import IMessageView, MessageViewType

from qtpy.QtWidgets import QMessageBox, QWidget

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass(eq=False)
class QtMessageView(QtView, IMessageView):
    r"""Display a message in a modal view."""

    view: None = field(init=False, default=None)
    _parent: QWidget
    _type: Optional[MessageViewType] = field(init=False, repr=False, default=None)
    _buttons: Optional[Union[QMessageBox.StandardButtons, QMessageBox.StandardButton]] = field(
        init=False, repr=False, default=None
    )
    result: Optional[bool] = field(init=False, repr=False, default=None)

    def run(self) -> Optional[bool]:
        r"""Run the view."""
        self.result = None
        if self._buttons is not None:
            if self._type == MessageViewType.question:
                self.result = (
                    QMessageBox.question(self._parent, self.title, self.message, self._buttons)
                    == QMessageBox.Yes
                )
            elif self._type == MessageViewType.critical:
                self.result = (
                    QMessageBox.critical(self._parent, self.title, self.message, self._buttons)
                    == QMessageBox.Ok
                )
            elif self._type == MessageViewType.warning:
                self.result = (
                    QMessageBox.warning(self._parent, self.title, self.message, self._buttons)
                    == QMessageBox.Ok
                )
        return self.result

    @property  # type: ignore[misc]
    def message_type(self) -> Optional[MessageViewType]:
        return self._type

    @message_type.setter
    def message_type(self, message_type: MessageViewType) -> None:
        if message_type == MessageViewType.question:
            self._buttons = QMessageBox.Yes | QMessageBox.No
        elif message_type in (MessageViewType.critical, MessageViewType.warning):
            self._buttons = QMessageBox.Close
        else:
            message = f"The given type {message_type} is not available."
            raise ValueError(message)
        self._type = message_type
