"""A confirmation guarding an edit, shared by the core and backend tests of dialogs."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    ActionView,
    DialogKind,
    DialogView,
    LabelView,
    MainView,
    Menu,
    define_view,
)


@define_view
class EditMenu(Menu):
    clear: ActionView = Factory(ActionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Edit"
        self.clear.text = "Clear"
        self.clear.shortcut = "Ctrl+l"


@define_view
class ClearDialog(DialogView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.kind = DialogKind.CONFIRM
        self.title = "Clear the name"
        self.text = "The name will be lost."
        self.accept_text = "Clear"


@define_view
class DialogsMainView(MainView):
    app_title = "Dialogs"
    extension = ".dialogs"

    edit_menu: EditMenu = Factory(EditMenu)
    name: LabelView = Factory(LabelView)
    confirm_clear: ClearDialog = Factory(ClearDialog)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.name.text = "Ada"
        self.edit_menu.clear.triggered.connect(self.confirm_clear.open)
        self.confirm_clear.accepted.connect(self._clear)

    def _clear(self) -> None:
        self.name.text = ""
