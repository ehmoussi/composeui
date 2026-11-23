"""A main view opening a page and a folder for its user, shared by the backends' tests."""

from __future__ import annotations

from pathlib import Path

import attrs
from typing_extensions import override

from composeui.core.view import OMIT, ButtonView, MainView, define_view

#: the page that Help opens
HELP_URL = "https://example.org/help?topic=runs&lang=en"


@define_view
class OpeningMainView(MainView):
    """Help opens the page of `help_url` in the user's browser, Open folder `folder`."""

    has_file_menu = False

    help: ButtonView = attrs.field(factory=lambda: ButtonView(text="Help"))
    open_folder_button: ButtonView = attrs.field(factory=lambda: ButtonView(text="Open folder"))
    #: the page that Help opens
    help_url: str = attrs.field(default=HELP_URL, metadata={OMIT: True})
    #: the folder that Open folder opens
    folder: Path = attrs.field(factory=Path.cwd, metadata={OMIT: True})

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.help.clicked.connect(lambda: self.open_url(self.help_url))
        self.open_folder_button.clicked.connect(lambda: self.open_folder(self.folder))
