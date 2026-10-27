from __future__ import annotations

from typing import Generic, Optional, TypeVar

from textual.content import Content
from textual.widgets import RadioButton, RadioSet

from composeui.core.signal import Signal

TValue = TypeVar("TValue")


class ComposeRadioSet(RadioSet, Generic[TValue]):
    """A `RadioSet` built from a `{label: value}` mapping, like Qt's `QRadioGroup`.

    Textual dispatches `RadioSet.Changed` by calling `on_radio_set_changed` on the
    widget itself first; a renderer isn't part of the DOM, so it can't bind to that
    directly. Re-emitting it through a plain composeui `Signal` lets
    `TextualRadioGroupRenderer` connect like it would to any other composeui signal.
    """

    # a form row's field while the row is invalid (see `ROW_INVALID_CLASS`)
    DEFAULT_CSS = """
    ComposeRadioSet.-row-invalid {
        border: tall $error 60%;
        &:focus {
            border: tall $error;
        }
    }
    """

    def __init__(self, values: dict[str, TValue]) -> None:
        self._values: dict[str, TValue] = dict(values)
        super().__init__(*(RadioButton(Content(label)) for label in self._values))
        self.value_changed: Signal[Optional[TValue]] = Signal()

    def set_values(self, values: dict[str, TValue]) -> None:
        """Rebuild the radio buttons for a new set of options."""
        self.remove_children()
        self._values = dict(values)
        for label in self._values:
            self.mount(RadioButton(Content(label)))

    def set_value(self, value: Optional[TValue]) -> None:
        for button, candidate in zip(self.query(RadioButton), self._values.values()):
            # None presses its button only when it's one of the values
            if value == candidate and not button.value:
                button.value = True

    def value(self) -> TValue:
        assert self.pressed_index != -1  # asked once a button is pressed
        return list(self._values.values())[self.pressed_index]

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self.value_changed.emit(self.value())
