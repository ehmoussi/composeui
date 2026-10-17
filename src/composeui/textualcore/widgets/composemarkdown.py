from __future__ import annotations

from textual.widgets import Markdown


class ComposeMarkdown(Markdown):
    """A `Markdown` whose text is set at any time, mounted or not.

    Its links open in the browser (Textual's `open_links`).
    """

    def set_text(self, text: str) -> None:
        if self.is_mounted:
            # not awaited: Textual mounts the new blocks in a task, one update after another
            self.update(text)
        else:
            self._initial_markdown = text  # what `Markdown` shows once mounted
