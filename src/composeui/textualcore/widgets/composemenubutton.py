"""The popup list of a menu button: its entries under the button, one picked or none."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional

from textual.binding import Binding
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from typing_extensions import override

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult
    from textual.binding import BindingType
    from textual.geometry import Region


class ComposeMenuPopup(ModalScreen[Optional[int]]):
    """A list of a menu button's entries, under the button; None stands for a separator.

    Each entry is its text and whether it is enabled. Picking one (a click or Enter)
    dismisses the list with its index among the entries, Escape or a click outside with
    None.
    """

    DEFAULT_CSS = """
    ComposeMenuPopup {
        align: left top;
        background: transparent;
    }
    ComposeMenuPopup > OptionList {
        width: auto;
        min-width: 20;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: round $primary;
        constrain: inside inside;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "close", "Close")]

    def __init__(self, entries: list[Optional[tuple[str, bool]]], under: Region) -> None:
        super().__init__()
        options: list[Optional[Option]] = [
            # `Content`: the entry's text as it is, not as Textual's markup
            None
            if entry is None
            else Option(Content(entry[0]), id=str(index), disabled=not entry[1])
            for index, entry in enumerate(entries)
        ]
        self.options = OptionList(*options)
        self._under = under

    @override
    def compose(self) -> ComposeResult:
        yield self.options

    def on_mount(self) -> None:
        self.options.styles.offset = (self._under.x, self._under.bottom)
        self.options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        assert event.option.id is not None
        self.dismiss(int(event.option.id))

    def on_click(self, event: events.Click) -> None:
        if event.widget is self:  # outside the list: the list's own click picks an entry
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
