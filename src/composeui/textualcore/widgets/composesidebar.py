from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Label


class ComposeSidebar(VerticalScroll):
    """A column on the screen's left: its title, then its views, scrolling on their own.

    As wide as a third of the screen at most: the content beside it keeps the rest.
    """

    DEFAULT_CSS = """
    ComposeSidebar {
        width: 36;
        max-width: 33%;
        height: 1fr;
        padding: 0 1;
        margin-right: 1;
        border-right: vkey $foreground 20%;
        & > .sidebar--title {
            text-style: bold;
            margin-bottom: 1;
        }
    }
    """

    def __init__(self, *children: Widget) -> None:
        self.title = Label(classes="sidebar--title")
        super().__init__(self.title, *children)
