"""A Markdown viewer: `python -m examples.markdownviewer README.md --backend qt`.

The file comes first on the command line, the rest goes to the app (`--backend textual`,
`--language`, ...); Markdown > Open Markdown (Ctrl+M) picks one, on the web too (the
browser uploads it).
"""

from __future__ import annotations

import sys
from pathlib import Path

from attrs import Factory

from composeui.core.application import run
from composeui.core.view import (
    MainView,
    MarkdownView,
    Menu,
    PickFileAction,
    T,
    child,
    define_view,
)


@define_view
class MarkdownMenu(Menu):
    open_markdown: PickFileAction = child(
        PickFileAction, extensions={"Markdown": (".md", ".markdown")}
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Markdown")
        self.open_markdown.text = self.tr("Open Markdown")
        self.open_markdown.shortcut = "Ctrl+m"


@define_view
class MarkdownViewerMainView(MainView):
    app_title = T("Markdown Viewer")
    extension = ".mdviewer"

    markdown_menu: MarkdownMenu = Factory(MarkdownMenu)
    document: MarkdownView = Factory(MarkdownView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.markdown_menu.open_markdown.file_picked.connect(self.open_markdown)
        self.document.text = self.tr("Open a Markdown file: *Markdown > Open Markdown*.")

    def open_markdown(self, path: Path) -> None:
        """Show the Markdown file at `path`, or say in the status bar why it can't."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            message = self.tr("Can't open {name}: {error}")
            self.status_bar.show_message(message.format(name=repr(path.name), error=error))
            return
        self.document.text = text
        self.status_bar.show_message(path.name)


def main() -> None:
    path: Path | None = None
    # the file first: `run` hands the rest of the command line to the app, which knows
    # only its own options
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        path = Path(sys.argv.pop(1))

    def build_main_view() -> MarkdownViewerMainView:
        main_view = MarkdownViewerMainView()
        if path is not None:
            main_view.open_markdown(path)
        return main_view

    run(build_main_view)


if __name__ == "__main__":
    main()
