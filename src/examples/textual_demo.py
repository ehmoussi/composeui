from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    GroupFormView,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelRowRadioGroupView,
    LogType,
    MainView,
    define_view,
)
from composeui.qtcore.qtapplication import QtApplication
from composeui.textualcore.textualapplication import TextualApplication


@define_view
class NameRowView(LabelRowInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Name"
        self.placeholder = "e.g. widget-42"
        self.text_edited.connect(self._check_name)
        self._check_name(self.text)

    def _check_name(self, text: str) -> None:
        if text == "":
            self.log_message = "A name is mandatory"
            self.log_type = LogType.ERROR
        else:
            self.log_message = ""
            self.log_type = LogType.INFO


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
    form: DemoFormView = Factory(DemoFormView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Textual Demo", extension=".demo")
        self.form.shape.value_changed.connect(self._display_shape_status)

    def _display_shape_status(self, value: str | None) -> None:
        if value is not None:
            self.status_bar.show_message(f"Shape changed: {value}")


class TextualDemoApp(TextualApplication[TextualDemoMainView]):
    def __init__(self) -> None:
        super().__init__(main_view=TextualDemoMainView())


class QtDemoApp(QtApplication[TextualDemoMainView]):
    def __init__(self) -> None:
        super().__init__(main_view=TextualDemoMainView())


def main() -> None:
    app = TextualDemoApp()
    app.run()


if __name__ == "__main__":
    main()
