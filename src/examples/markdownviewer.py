"""A Markdown viewer: `python -m examples.markdownviewer --markdown README.md --backend qt`.

`--markdown` is the app's own command-line option, beside the backend's (`--backend
textual`, `--language`, ...); Markdown > Open Markdown (Ctrl+M) picks one, on the web
too (the browser uploads it).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    import argparse


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
    has_file_menu = False  # no study to open or save: only Markdown files

    markdown_menu: MarkdownMenu = Factory(MarkdownMenu)
    document: MarkdownView = Factory(MarkdownView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.markdown_menu.open_markdown.file_picked.connect(self.open_markdown)
        self.document.text = self.tr("Open a Markdown file: *Markdown > Open Markdown*.")

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--markdown", type=Path, metavar="FILE", help="Show the Markdown FILE.")

    def apply_arguments(self, args: argparse.Namespace) -> None:
        if args.markdown is not None:
            self.open_markdown(args.markdown)

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
    run(MarkdownViewerMainView)


if __name__ == "__main__":
    main()
