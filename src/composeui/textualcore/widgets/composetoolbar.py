from textual.containers import Horizontal
from textual.widgets import Button

from composeui.core.signal import SignalNoArgs


class ComposeToolbarButton(Button):
    """A toolbar `Button` re-exposing its presses as a plain composeui `Signal`."""

    def __init__(self) -> None:
        super().__init__(compact=True)
        self.triggered = SignalNoArgs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.triggered.emit()


class ComposeToolbar(Horizontal):
    """A row of toolbar buttons, docked at the top of the screen."""

    DEFAULT_CSS = """
    ComposeToolbar {
        dock: top;
        height: auto;
        padding: 0 1;
        background: $panel;
    }
    ComposeToolbar > ComposeToolbarButton {
        margin-right: 1;
    }
    """
