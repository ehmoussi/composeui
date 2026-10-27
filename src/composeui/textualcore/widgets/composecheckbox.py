from __future__ import annotations

from textual.widgets import Checkbox

from composeui.core.signal import Signal


class ComposeCheckBox(Checkbox):
    """A `Checkbox` re-exposing the user's toggles as a plain composeui `Signal`.

    Textual posts `Checkbox.Changed` for any change of `value`, set in code too;
    `set_checked` keeps those quiet, as Qt's renderers block their widget's signals
    while refreshing it, so `toggled` only reports the user's toggles.
    """

    # a form row's field while the row is invalid (see `ROW_INVALID_CLASS`)
    DEFAULT_CSS = """
    ComposeCheckBox.-row-invalid {
        border: tall $error 60%;
        &:focus {
            border: tall $error;
        }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.toggled: Signal[bool] = Signal()

    def set_checked(self, is_checked: bool) -> None:
        with self.prevent(Checkbox.Changed):
            self.value = is_checked

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self.toggled.emit(event.value)
