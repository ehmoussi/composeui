from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from composeui.core.signal import SignalNoArgs


class ComposeToolbarButton(Button):
    """A toolbar `Button` re-exposing its presses as a plain composeui `Signal`."""

    def __init__(self) -> None:
        super().__init__(compact=True)
        self.triggered = SignalNoArgs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.triggered.emit()


class ComposeToolbarSeparator(Static):
    """A thin bar between two groups of toolbar buttons."""

    DEFAULT_CSS = """
    ComposeToolbarSeparator {
        width: auto;
        margin-right: 1;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__("│")


class ComposeToolbar(Horizontal):
    """A row of toolbar buttons, in the `ComposeToolbars` docked at the top of the screen."""

    DEFAULT_CSS = """
    ComposeToolbar {
        height: auto;
        padding: 0 1;
        background: $panel;
    }
    ComposeToolbar > ComposeToolbarButton {
        margin-right: 1;
    }
    """


class ComposeToolbars(Vertical):
    """The toolbars, one above the other, docked at the top of the screen.

    Widgets docked to the same edge overlap: the toolbars share one dock instead.
    """

    DEFAULT_CSS = """
    ComposeToolbars {
        dock: top;
        height: auto;
    }
    """
