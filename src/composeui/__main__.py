from __future__ import annotations

from attrs import Factory, field

from composeui.qtapplication import QtApplication
from composeui.view import (
    FormView,
    GroupFormView,
    LabelFloatInputRowView,
    LabelInputRowView,
    MainView,
    define_view,
)


@define_view
class RadiusInputView(LabelFloatInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Radius"
        self.field_view.value = 20.0
        self.field_view.minimum = 0
        self.field_view.decimals = 3


@define_view
class WidthInputView(LabelFloatInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Width"
        self.field_view.value = 20.0
        self.field_view.minimum = 0
        self.field_view.decimals = 3


@define_view
class HalfLengthInputView(LabelFloatInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Half Length"
        self.field_view.value = 200.0
        self.field_view.minimum = 0
        self.field_view.decimals = 3


@define_view
class PipeDimension(GroupFormView):
    radius: RadiusInputView = Factory(RadiusInputView)
    width: WidthInputView = Factory(WidthInputView)
    half_length: HalfLengthInputView = Factory(HalfLengthInputView)

    def __attrs_post_init__(self) -> None:
        self.title = "Main Pipe"


@define_view
class PipeNameRowView(LabelInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Name"
        self.field_view.text_edited.connect(self._check_name)

    def _check_name(self, text: str) -> None:
        if text == "":
            self.log_view.log_message = "A name is mandatory"
            self.log_view.log_type = type(self.log_view.log_type).ERROR
        else:
            self.log_view.log_message = ""
            self.log_view.log_type = type(self.log_view.log_type).INFO
        # if self.log_view.renderer is not None:
        #     self.log_view.renderer.refresh()


@define_view
class PipeFormView(FormView):
    name: PipeNameRowView = field(factory=PipeNameRowView)
    main_pipe: PipeDimension = Factory(PipeDimension)


@define_view
class PipeMainView(MainView):
    pipe_form: PipeFormView = field(factory=PipeFormView)

    def __attrs_post_init__(self) -> None:
        # Use object.__setattr__ to bypass the frozen attribute restriction.
        object.__setattr__(self, "title", "Pipe Form")
        object.__setattr__(self, "extension", ".pipe")


def main() -> None:
    main_view = PipeMainView()
    app = QtApplication(main_view)
    app.run()


if __name__ == "__main__":
    main()
