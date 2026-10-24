from __future__ import annotations

from textual.widgets import TabbedContent, TabPane

from composeui.core.signal import Signal


class ComposeTabbedContent(TabbedContent):
    """A `TabbedContent` re-exposing the user's picks as a plain composeui `Signal`.

    Textual posts `TabbedContent.TabActivated` for any change of `active`, set in code
    too; `set_active` keeps those quiet, as Qt's renderers block their widget's signals
    while refreshing it, so `picked` only reports the tab the user picks, by its pane.
    The message bubbles: one from tabs nested in a pane isn't this one's.
    """

    def __init__(self, *panes: TabPane, initial: str = "") -> None:
        # `initial`: the pane shown first, else the first; Textual reports it as activated
        super().__init__(initial=initial)
        # as the compose syntax does: its positional arguments are titles, not panes
        for pane in panes:
            self.compose_add_child(pane)
        self.picked: Signal[TabPane] = Signal()

    def set_active(self, pane_id: str) -> None:
        if not self.is_attached:
            # not composed yet: shown first once mounted, as the tabs are built from it
            self._initial = pane_id
            return
        with self.prevent(TabbedContent.TabActivated):
            self.active = pane_id

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tabbed_content is self:
            self.picked.emit(event.pane)
