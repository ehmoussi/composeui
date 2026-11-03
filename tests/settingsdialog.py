"""A settings dialog with its own buttons and a check: the tests of `DialogButtonView`."""

from __future__ import annotations

from typing import Optional

import attrs

from composeui.core.view import (
    ContentDialogView,
    DialogButtonView,
    InputView,
    MainView,
    VerticalView,
    child,
    define_view,
)

#: the message of the dialog's check while the folder is empty
NO_FOLDER = "Choose an output folder."


@define_view
class SettingsPanel(VerticalView):
    folder: InputView = child(InputView, text="results")


@define_view
class SettingsDialog(ContentDialogView[SettingsPanel]):
    """Cancel, Apply (open, checked), Discard (closing, unchecked), Save: Apply is the app's."""

    content: SettingsPanel = attrs.Factory(SettingsPanel)
    apply: DialogButtonView = child(DialogButtonView, text="Apply")
    discard: DialogButtonView = child(DialogButtonView, text="Discard", closes=True, checks=False)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.accept_text = "Save"
        self.add_check(self._has_folder, self.content.folder.text_changed)

    def _has_folder(self) -> Optional[str]:
        return None if self.content.folder.text else NO_FOLDER


@define_view
class SettingsMainView(MainView):
    settings: SettingsDialog = attrs.Factory(SettingsDialog)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        #: each answer of the dialog, by its signal: "apply", "discard", "accepted" or
        #: "rejected"; not a field: the test's record, not the view's state
        self.answers: list[str] = []
        dialog = self.settings
        dialog.apply.clicked.connect(lambda: self.answers.append("apply"))
        dialog.discard.clicked.connect(lambda: self.answers.append("discard"))
        dialog.accepted.connect(lambda: self.answers.append("accepted"))
        dialog.rejected.connect(lambda: self.answers.append("rejected"))
