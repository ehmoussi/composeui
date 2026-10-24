from __future__ import annotations

from attrs import Factory

from composeui.core.application import run
from composeui.core.registry import RendererType
from composeui.core.view import (
    GroupFormView,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelRowRadioGroupView,
    MainView,
    define_view,
)


@define_view
class NameRowView(LabelRowInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Name"
        self.placeholder = "e.g. widget-42"
        self.set_validator(self._check_name, self.text_edited)
        self.run_validator()

    def _check_name(self) -> str | None:
        return "A name is mandatory" if self.text == "" else None


@define_view
class SizeRowView(LabelRowFloatInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Size"
        self.minimum = 0
        self.value = 3.0


@define_view
class ShapeRowView(LabelRowRadioGroupView[str]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Shape"
        self.values = {"round": "ROUND", "square": "SQUARE", "hex": "HEXAGON"}


@define_view
class DemoFormView(GroupFormView):
    name: NameRowView = Factory(NameRowView)
    size: SizeRowView = Factory(SizeRowView)
    shape: ShapeRowView = Factory(ShapeRowView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Demo"


@define_view
class TextualDemoMainView(MainView):
    app_title = "Textual Demo"
    extension = ".demo"

    form: DemoFormView = Factory(DemoFormView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.form.shape.value_changed.connect(self._display_shape_status)

    def _display_shape_status(self, value: str | None) -> None:
        assert value is not None  # the user picks a radio button, never none
        self.status_bar.show_message(f"Shape changed: {value}")


def main() -> None:
    run(TextualDemoMainView, default_backend=RendererType.TEXTUAL)


if __name__ == "__main__":
    main()
