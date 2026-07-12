from typing import Any

from textual import events
from textual.widgets import Input

from composeui.core.signal import Signal, SignalNoArgs


class ComposeInput(Input):
    """An `Input` that re-exposes its messages as plain composeui `Signal`s.

    Textual dispatches `Input.Changed`/`Input.Submitted` by calling `on_input_changed`/
    `on_input_submitted` on the widget itself (and its DOM ancestors); a renderer isn't
    part of the DOM, so it can't bind to those directly. Bridging them to `Signal`s here
    lets `TextualInputRenderer` connect like it would to any other composeui signal.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.value_changed: Signal[str] = Signal()
        self.value_submitted: SignalNoArgs = SignalNoArgs()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.value_changed.emit(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.value_submitted.emit()

    def on_blur(self, event: events.Blur) -> None:
        """Match Qt's `QLineEdit.editingFinished`, which fires on Enter *or* blur.

        `Input.Submitted` alone only covers Enter; without this, tabbing/clicking
        away from a field (instead of pressing Enter) never fires `editing_finished`.
        """
        self.value_submitted.emit()
