from textual.widget import Widget
from textual.widgets import Collapsible

from composeui.core.signal import Signal


class ComposeCollapsible(Collapsible):
    """A `Collapsible` re-exposing the user's toggles as a plain composeui `Signal`.

    Textual posts `Collapsible.Expanded`/`Collapsed` for any change of `collapsed`, set
    in code too; `set_expanded` keeps those quiet, as Qt's renderers block their
    widget's signals while refreshing it, so `toggled` only reports the user's toggles.
    The messages bubble: one from a collapsible nested in this one isn't this one's.
    """

    def __init__(self, *children: Widget) -> None:
        super().__init__(*children)
        self.toggled: Signal[bool] = Signal()

    def set_expanded(self, is_expanded: bool) -> None:
        with self.prevent(Collapsible.Expanded, Collapsible.Collapsed):
            self.collapsed = not is_expanded

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self:
            self.toggled.emit(True)  # noqa: FBT003

    def on_collapsible_collapsed(self, event: Collapsible.Collapsed) -> None:
        if event.collapsible is self:
            self.toggled.emit(False)  # noqa: FBT003
