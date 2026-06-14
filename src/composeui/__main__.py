from __future__ import annotations

from attrs import Factory, define, field

from composeui.qtapplication import QtApplication
from composeui.view import (
    FormView,
    GroupFormView,
    LabelFloatInputRowView,
    LabelInputRowView,
    MainView,
)


@define
class RadiusInputView(LabelFloatInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Radius"
        self.field_view.value = 20.0
        self.field_view.minimum = 0
        self.field_view.decimals = 3


@define
class WidthInputView(LabelFloatInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Width"
        self.field_view.value = 20.0
        self.field_view.minimum = 0
        self.field_view.decimals = 3


@define
class HalfLengthInputView(LabelFloatInputRowView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label_view.text = "Half Length"
        self.field_view.value = 200.0
        self.field_view.minimum = 0
        self.field_view.decimals = 3


@define
class PipeDimension(GroupFormView):
    radius: RadiusInputView = Factory(RadiusInputView)
    width: WidthInputView = Factory(WidthInputView)
    half_length: HalfLengthInputView = Factory(HalfLengthInputView)

    def __attrs_post_init__(self) -> None:
        self.title = "Main Pipe"


@define
class PipeFormView(FormView):
    name: LabelInputRowView = field(factory=LabelInputRowView)
    main_pipe: PipeDimension = Factory(PipeDimension)

    def __attrs_post_init__(self) -> None:
        self.name.label_view.text = "Name"


@define
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
