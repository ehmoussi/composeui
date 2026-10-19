from __future__ import annotations

from textual.widgets import Button

from composeui.core.signal import SignalNoArgs


class ComposeButton(Button):
    """A `Button` re-exposing its presses as a plain composeui `Signal`."""

    def __init__(self) -> None:
        super().__init__()
        self.clicked = SignalNoArgs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.clicked.emit()
