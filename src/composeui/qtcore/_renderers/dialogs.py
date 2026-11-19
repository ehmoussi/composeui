"""Qt message and content dialog renderers."""

from __future__ import annotations

import sys
from typing import Any

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QAbstractButton, QMessageBox, QPushButton

from composeui.core.view import DialogKind, DialogView, OkCancelDialogView
from composeui.qtcore._renderers.forms import _widget_of
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.qtslot import connect_slot
from composeui.qtcore.widgets.qformdialog import QFormDialog
from composeui.qtcore.widgets.qwindowrelease import release_when_hidden

#: macOS shows no title on a message box (Apple's guidelines): its bold text is the title there,
#: and its informative text the message
_TITLE_AS_TEXT = sys.platform == "darwin"


def _show_dialog_text(box: QMessageBox, title: str, text: str) -> None:
    """Show a dialog's title and text, the title as the bold text where it has no title."""
    title_as_text = _TITLE_AS_TEXT and title != ""
    box.setWindowTitle(title)  # macOS ignores it
    box.setText(title if title_as_text else text)
    box.setInformativeText(text if title_as_text else "")


class QtDialogRenderer(QtWidgetRenderer[DialogView, QMessageBox]):
    """A modal message box, shown without blocking: its answer reaches the view later."""

    def __init__(self, view: DialogView) -> None:
        super().__init__(view)
        self._accept_button: QPushButton | None = None
        self._reject_button: QPushButton | None = None
        #: a hidden button Escape clicks in a confirmation: it dismisses the dialog, which
        #: needn't be its rejection (`DialogView.dismiss`)
        self._escape_button: QPushButton | None = None
        #: the button that closed the box; None when it was closed from its window
        self._clicked: QAbstractButton | None = None
        self._refresh_dispatcher.update(
            {
                "is_visible": self._refresh_dialog_visible,
                "title": self._refresh_dialog_title,
                "text": self._refresh_dialog_text,
                "kind": self._refresh_kind,
                "accept_text": self._refresh_accept_text,
                "reject_text": self._refresh_reject_text,
                "is_destructive": self._refresh_is_destructive,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            box = QMessageBox()
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setModal(True)
            release_when_hidden(box)
            self._accept_button = box.addButton("", QMessageBox.ButtonRole.AcceptRole)
            self._reject_button = box.addButton("", QMessageBox.ButtonRole.RejectRole)
            self._escape_button = box.addButton("", QMessageBox.ButtonRole.RejectRole)
            self._escape_button.hide()
            connect_slot(box.buttonClicked, box, self._set_clicked)
            connect_slot(box.finished, box, self._answer)
            self._rendered_object = box
            self.refresh()

    def _set_clicked(self, button: QAbstractButton) -> None:
        self._clicked = button

    def _answer(self, _result: int) -> None:
        if self._clicked is None or self._clicked is self._escape_button:
            self._view.dismiss()
        elif self._clicked is self._accept_button:
            self._view.accept()
        else:
            self._view.reject()

    def _refresh_dialog_visible(
        self, _view: DialogView, rendered_object: QMessageBox, value: bool
    ) -> None:
        if value:
            self._clicked = None
        rendered_object.setVisible(value)

    @staticmethod
    def _refresh_dialog_title(view: DialogView, rendered_object: QMessageBox, value: str) -> None:
        # the view's field still holds the previous value: it's set once the refresh is over
        _show_dialog_text(rendered_object, value, view.text)

    @staticmethod
    def _refresh_dialog_text(view: DialogView, rendered_object: QMessageBox, value: str) -> None:
        _show_dialog_text(rendered_object, view.title, value)

    def _refresh_kind(
        self, view: DialogView, rendered_object: QMessageBox, value: DialogKind
    ) -> None:
        assert self._accept_button is not None
        assert self._reject_button is not None
        assert self._escape_button is not None
        is_confirm = value is DialogKind.CONFIRM
        self._reject_button.setVisible(is_confirm)
        # Escape clicks it: the hidden reject button would otherwise answer a message
        rendered_object.setEscapeButton(self._escape_button if is_confirm else self._accept_button)
        self._show_safe_button(rendered_object, kind=value, is_destructive=view.is_destructive)

    def _refresh_is_destructive(
        self, view: DialogView, rendered_object: QMessageBox, value: bool
    ) -> None:
        self._show_safe_button(rendered_object, kind=view.kind, is_destructive=value)

    def _show_safe_button(
        self, box: QMessageBox, *, kind: DialogKind, is_destructive: bool
    ) -> None:
        assert self._accept_button is not None
        assert self._reject_button is not None
        # the default button takes Enter, and the focus as the box opens
        is_safe_first = is_destructive and kind is DialogKind.CONFIRM
        box.setDefaultButton(self._reject_button if is_safe_first else self._accept_button)
        # red like a `ButtonVariant.DANGER` button
        self._accept_button.setStyleSheet("QPushButton { color: red; }" if is_safe_first else "")

    def _refresh_accept_text(
        self, _view: DialogView, _rendered_object: QMessageBox, value: str
    ) -> None:
        assert self._accept_button is not None
        self._accept_button.setText(value)

    def _refresh_reject_text(
        self, _view: DialogView, _rendered_object: QMessageBox, value: str
    ) -> None:
        assert self._reject_button is not None
        self._reject_button.setText(value)


class QtFormDialogRenderer(QtWidgetRenderer[OkCancelDialogView, QFormDialog]):
    """A modal dialog holding its form or other view, shown without blocking.

    Its answer reaches the view. OK is disabled while the view says so, e.g. while a check
    of the form fails. The view closes the dialog once it accepts the answer, so OK on a
    form refusing it leaves the dialog open.
    """

    def __init__(self, view: OkCancelDialogView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_dialog_title,
                "text": self._refresh_text,
                "kind": self._refresh_kind,
                "is_destructive": self._refresh_kind,
                "accept_text": self._refresh_accept_text,
                "reject_text": self._refresh_reject_text,
                "is_accept_enabled": self._refresh_is_accept_enabled,
                "has_failing_check": self._refresh_has_failing_check,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            dialog = QFormDialog()
            release_when_hidden(dialog)
            content = _widget_of(self._view.content)
            assert content is not None
            dialog.set_form(content)
            log = _widget_of(self._view.log_view)
            assert log is not None
            dialog.set_log(log)
            for button in self._view.buttons:
                widget = _widget_of(button)
                assert isinstance(widget, QPushButton)  # this backend renders a dialog's buttons
                dialog.add_button(widget)
            dialog.answered_ok.connect(self._view.accept)
            dialog.answered_cancel.connect(self._view.reject)
            dialog.dismissed.connect(self._view.dismiss)
            self._rendered_object = dialog
            self.refresh()

    @staticmethod
    def _refresh_dialog_title(
        _view: OkCancelDialogView, rendered_object: QFormDialog, value: str
    ) -> None:
        rendered_object.setWindowTitle(value)

    @staticmethod
    def _refresh_text(_view: OkCancelDialogView, rendered_object: QFormDialog, value: str) -> None:
        rendered_object.text.setText(value)
        rendered_object.text.setVisible(value != "")

    @staticmethod
    def _refresh_kind(
        _view: OkCancelDialogView, _rendered_object: QFormDialog, _value: Any
    ) -> None:
        pass  # always OK and Cancel: its view is confirmed or not, and Enter submits it

    @staticmethod
    def _refresh_accept_text(
        _view: OkCancelDialogView, rendered_object: QFormDialog, value: str
    ) -> None:
        rendered_object.ok_button.setText(value)

    @staticmethod
    def _refresh_reject_text(
        _view: OkCancelDialogView, rendered_object: QFormDialog, value: str
    ) -> None:
        rendered_object.cancel_button.setText(value)

    # each is told its own field's new value, not yet the view's
    @staticmethod
    def _refresh_is_accept_enabled(
        view: OkCancelDialogView, rendered_object: QFormDialog, value: bool
    ) -> None:
        rendered_object.ok_button.setEnabled(value and not view.has_failing_check)

    @staticmethod
    def _refresh_has_failing_check(
        view: OkCancelDialogView, rendered_object: QFormDialog, value: bool
    ) -> None:
        rendered_object.ok_button.setEnabled(view.is_accept_enabled and not value)
