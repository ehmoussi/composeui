from __future__ import annotations

import sys

from attrs import define, field
from qtpy.QtWidgets import QApplication

from composeui.view import (
    FormView,
    InputView,
    LabelFormRowView,
    LogType,
    RendererType,
)


@define
class TestFieldView(LabelFormRowView):
    def __init__(self) -> None:
        self.__attrs_init__(field_view=InputView())


@define
class TestFormView(FormView):
    test_field_view: TestFieldView = field(factory=TestFieldView)


def main() -> None:
    app = QApplication(sys.argv)
    view = TestFormView()
    view.is_visible = True
    view.test_field_view.label_view.text = "My Field"
    view.test_field_view.log_view.log_message = "Error message"
    view.test_field_view.log_view.log_type = LogType.ERROR
    view.render(RendererType.QT)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
