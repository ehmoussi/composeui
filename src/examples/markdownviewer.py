"""A Markdown viewer: `python -m examples.markdownviewer --markdown README.md --backend qt`.

`--markdown` is the app's own command-line option, beside the backend's (`--backend
textual`, `--language`, ...). The field at the top takes the file's path: typed, or
picked with its "…" button, on the web too (the browser uploads it); its reload button
reads the file again, e.g. once edited.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import attrs
from attrs import Factory

from composeui.core.application import run
from composeui.core.view import (
    OMIT,
    FilePathInputView,
    MainView,
    MarkdownView,
    T,
    child,
    define_view,
)

if TYPE_CHECKING:
    import argparse


@define_view
class MarkdownViewerMainView(MainView):
    app_title = T("Markdown Viewer")
    extension = ".mdviewer"
    has_file_menu = False  # no study to open or save: only Markdown files

    markdown_file: FilePathInputView = child(
        FilePathInputView, extensions={"Markdown": (".md", ".markdown")}, has_reload=True
    )
    document: MarkdownView = Factory(MarkdownView)
    #: the file the document shows, None before the first one; not study data
    _shown: Optional[Path] = attrs.field(default=None, init=False, metadata={OMIT: True})

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.markdown_file.placeholder = self.tr("The path of a Markdown file")
        self.markdown_file.path_picked.connect(self.open_markdown)
        self.markdown_file.editing_finished.connect(self._open_typed)
        self.markdown_file.reload_clicked.connect(self._reload)
        self.document.text = self.tr("Open a Markdown file: type its path, or pick it with *…*.")

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--markdown", type=Path, metavar="FILE", help="Show the Markdown FILE.")

    def apply_arguments(self, args: argparse.Namespace) -> None:
        if args.markdown is not None:
            self.markdown_file.text = str(args.markdown)
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
        self._shown = path
        self.status_bar.show_message(path.name)

    def _open_typed(self) -> None:
        # also once the field only loses the focus: the file shown isn't read again
        path = self.markdown_file.path
        if path is not None and path != self._shown:
            self.open_markdown(path)

    def _reload(self) -> None:
        path = self.markdown_file.path
        if path is not None:
            self.open_markdown(path)


def main() -> None:
    run(MarkdownViewerMainView)


if __name__ == "__main__":
    main()
