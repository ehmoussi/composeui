from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from composeui.core.view import DialogKind

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType

    from composeui.core.view import DialogView


class ComposeDialog(ModalScreen[Optional[bool]]):
    """A dialog's modal screen, dismissed with True (accepted), False (rejected) or None.

    None is a dialog closed with Escape, without a button. Built from the dialog's view
    as it opens.
    """

    DEFAULT_CSS = """
    ComposeDialog {
        align: center middle;
    }
    ComposeDialog > Vertical {
        width: auto;
        min-width: 40;
        max-width: 80%;
        height: auto;
        padding: 1 2;
        border: thick $primary 80%;
        background: $surface;
    }
    ComposeDialog .title {
        text-style: bold;
        margin-bottom: 1;
    }
    ComposeDialog Horizontal {
        width: 100%;
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    ComposeDialog Button {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "dismiss_dialog", "Close")]

    def __init__(self, view: DialogView) -> None:
        super().__init__()
        self.title_label = Label(view.title, classes="title", markup=False)
        self.title_label.display = view.title != ""
        self.text_label = Static(view.text, markup=False)
        self.accept_button = Button(Content(view.accept_text), variant="primary", id="accept")
        self.reject_button = Button(Content(view.reject_text), id="reject")
        self.reject_button.display = view.kind is DialogKind.CONFIRM
        self.is_enabled = view.is_enabled

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self.title_label
            yield self.text_label
            with Horizontal():
                yield self.reject_button
                yield self.accept_button

    def on_mount(self) -> None:
        self.set_enabled(is_enabled=self.is_enabled)
        self.accept_button.focus()

    def set_enabled(self, *, is_enabled: bool) -> None:
        self.is_enabled = is_enabled
        self.accept_button.disabled = not is_enabled
        self.reject_button.disabled = not is_enabled

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button is self.accept_button)

    def action_dismiss_dialog(self) -> None:
        if self.is_enabled:
            self.dismiss(None)
