"""A help page in Markdown, shared by the backend tests of `MarkdownView`.

Its menu's `PickFileAction` shows a picked Markdown file instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import Factory

from composeui.core.view import MainView, MarkdownView, Menu, PickFileAction, child, define_view

if TYPE_CHECKING:
    from pathlib import Path


@define_view
class HelpMenu(Menu):
    open_help: PickFileAction = child(
        PickFileAction, text="Open Help", extensions={"Markdown": (".md", ".markdown")}
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Help"
        self.open_help.shortcut = "Ctrl+h"


@define_view
class HelpMainView(MainView):
    app_title = "Help"
    extension = ".help"

    help_menu: HelpMenu = Factory(HelpMenu)
    help: MarkdownView = Factory(MarkdownView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.help.text = "# Help\n\n- Open a study\n- Run it\n"
        self.help_menu.open_help.file_picked.connect(self._show_file)

    def _show_file(self, path: Path) -> None:
        self.help.text = path.read_text(encoding="utf-8")
