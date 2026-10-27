"""A pipe edited in a form dialog, shared by the core and backend tests of `FormDialogView`."""

from __future__ import annotations

import attrs

from composeui.core.view import (
    ButtonView,
    FormView,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelView,
    MainView,
    TypedFormDialogView,
    child,
    define_view,
)


@define_view
class PipeForm(FormView):
    name: LabelRowInputView = child(LabelRowInputView, label="Name")
    length: LabelRowFloatInputView = child(LabelRowFloatInputView, label="Length (m)")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.name.set_validator(self._check_name, self.name.text_edited)
        self.length.set_validator(self._check_length, self.length.text_edited)

    def _check_name(self) -> str | None:
        return "A name is mandatory" if self.name.text == "" else None

    def _check_length(self) -> str | None:
        length = self.length.value
        return "The length must be positive" if length is None or length <= 0 else None


@define_view
class EditPipeDialog(TypedFormDialogView[PipeForm]):
    form: PipeForm = attrs.Factory(PipeForm)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Edit the pipe"


@define_view
class PipeMainView(MainView):
    app_title = "Pipe"
    extension = ".pipe"

    pipe: LabelView = child(LabelView, text="Main line, 12 m")
    edit: ButtonView = child(ButtonView, text="Edit")
    edit_dialog: EditPipeDialog = attrs.Factory(EditPipeDialog)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.edit.clicked.connect(self._edit)
        self.edit_dialog.accepted.connect(self._apply)

    def _edit(self) -> None:
        """Open the dialog on the pipe as it is."""
        name, length = self.pipe.text.rsplit(", ", 1)
        self.edit_dialog.form.name.text = name
        self.edit_dialog.form.length.value = float(length.removesuffix(" m"))
        self.edit_dialog.form.check()
        self.edit_dialog.open()

    def _apply(self) -> None:
        form = self.edit_dialog.form
        self.pipe.text = f"{form.name.text}, {form.length.value:g} m"
