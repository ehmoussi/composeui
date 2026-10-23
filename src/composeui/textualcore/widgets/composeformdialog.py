from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from composeui.core.signal import Signal, SignalNoArgs

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType
    from textual.widget import Widget


class ComposeFormDialog(ModalScreen[None]):
    """A form dialog's modal screen: its title, text and form, then Cancel and OK.

    Installed once and pushed at each opening, so its form keeps its widgets: a screen
    dismissed can't be pushed again. It reports the user's answer (`answered`: "accept",
    "reject", or "dismiss" for Escape) without closing; its renderer pops it once the
    view closes the dialog, which stays open when its form refuses OK.
    """

    DEFAULT_CSS = """
    ComposeFormDialog {
        align: center middle;
    }
    ComposeFormDialog > VerticalScroll {
        width: 70%;
        max-width: 100;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: thick $primary 80%;
        background: $surface;
    }
    ComposeFormDialog .title {
        text-style: bold;
        margin-bottom: 1;
    }
    ComposeFormDialog Horizontal {
        width: 100%;
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    ComposeFormDialog Button {
        margin-left: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "dismiss_dialog", "Close")]

    def __init__(self, form: Widget) -> None:
        super().__init__()
        self.title_label = Label(classes="title", markup=False)
        self.text_label = Static(markup=False)
        self.form = form
        self.accept_button = Button("", variant="primary", id="accept")
        self.reject_button = Button("", id="reject")
        self.answered: Signal[str] = Signal()
        #: the screen's widgets are mounted, its form's among them: once, as it's installed
        self.mounted: SignalNoArgs = SignalNoArgs()

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield self.title_label
            yield self.text_label
            yield self.form
            with Horizontal():
                yield self.reject_button
                yield self.accept_button

    def on_mount(self) -> None:
        self.mounted.emit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.answered.emit("accept" if event.button is self.accept_button else "reject")

    def action_dismiss_dialog(self) -> None:
        if not self.reject_button.disabled:  # a disabled dialog can't be closed
            self.answered.emit("dismiss")
