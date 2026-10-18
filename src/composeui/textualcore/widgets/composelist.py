from textual.containers import Vertical


class ComposeList(Vertical):
    """A list's views one above the other, as tall as they are.

    Its collapsed collapsibles (an expander per record) leave out the line under their
    title, a lone one's room for its content: one line apart, many records stay in view.
    """

    DEFAULT_CSS = """
    ComposeList {
        height: auto;
        & > Collapsible.-collapsed {
            padding-bottom: 0;
        }
    }
    """
