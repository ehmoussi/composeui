from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, Static

from composeui.core.signal import Signal

if TYPE_CHECKING:
    from textual import events
    from textual.widget import Widget


class ComposeSidebarToggle(Static, can_focus=True):
    """The arrow retracting or expanding a sidebar, by a click or Enter."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "press", "Retract or expand", show=False),
    ]

    def __init__(self, sidebar: ComposeSidebar) -> None:
        super().__init__(classes="sidebar--toggle")
        self._sidebar = sidebar

    def on_click(self, _event: events.Click) -> None:
        self.action_press()

    def action_press(self) -> None:
        self._sidebar.toggle_by_user()


class ComposeSidebar(VerticalScroll):
    """A column on the screen's left: its title and an arrow, then its views, scrolling.

    As wide as a third of the screen at most: the content beside it keeps the rest. The
    arrow retracts it to a strip holding only the arrow, and expands it back; `toggled`
    reports those, and `set_expanded` is quiet, as Qt's renderers block their widget's
    signals while refreshing it.
    """

    DEFAULT_CSS = """
    ComposeSidebar {
        width: 36;
        max-width: 33%;
        height: 1fr;
        padding: 0 1;
        margin-right: 1;
        border-right: vkey $foreground 20%;
        & > .sidebar--header {
            height: auto;
            margin-bottom: 1;
        }
        & .sidebar--title {
            width: 1fr;
            text-style: bold;
        }
        & .sidebar--toggle {
            width: 3;
            content-align: center middle;
            &:focus {
                background: $accent;
                color: $text-accent;
            }
            &:hover {
                background: $boost;
            }
        }
        & > .sidebar--content {
            height: auto;
        }
        &.-retracted {
            width: 5;
            & > .sidebar--content {
                display: none;
            }
        }
    }
    """

    def __init__(self, *children: Widget) -> None:
        self.title = Label(classes="sidebar--title")
        self.toggle = ComposeSidebarToggle(self)
        super().__init__(
            Horizontal(self.title, self.toggle, classes="sidebar--header"),
            Vertical(*children, classes="sidebar--content"),
        )
        self.toggled: Signal[bool] = Signal()
        self._title_text = ""
        self.set_expanded(True)

    @property
    def is_expanded(self) -> bool:
        return not self.has_class("-retracted")

    def set_title(self, title: str) -> None:
        self.title.update(title)
        self._title_text = title
        self.title.display = title != "" and self.is_expanded

    def set_expanded(self, is_expanded: bool) -> None:
        self.set_class(not is_expanded, "-retracted")
        self.title.display = self._title_text != "" and is_expanded
        # pointing the way the sidebar goes: left to retract it, right to expand it
        self.toggle.update("◀" if is_expanded else "▶")

    def toggle_by_user(self) -> None:
        is_expanded = not self.is_expanded
        self.set_expanded(is_expanded)
        self.toggled.emit(is_expanded)
