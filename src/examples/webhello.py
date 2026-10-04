from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    FloatInputView,
    InputView,
    LabelView,
    LogView,
    MainView,
    define_view,
)
from composeui.webcore.webapplication import WebApplication


@define_view
class GreetingInputView(InputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.placeholder = "Type your name..."
        self.text_edited.connect(self._on_name_changed)

    # `main_view` is injected automatically because it's a requested parameter.
    def _on_name_changed(self, text: str, *, main_view: MainView) -> None:
        main_view.status_bar.show_message(f"Hello, {text}!" if text else "")


@define_view
class AgeInputView(FloatInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.placeholder = "Type your age..."
        self.minimum = 0
        self.decimals = 0


@define_view
class HelloMainView(MainView):
    name_label: LabelView = Factory(LabelView)
    greeting: GreetingInputView = Factory(GreetingInputView)
    name_log: LogView = Factory(LogView)
    age_label: LabelView = Factory(LabelView)
    age: AgeInputView = Factory(AgeInputView)
    age_log: LogView = Factory(LogView)
    summary: LabelView = Factory(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Hello ComposeUI", extension=".hello")
        self.name_label.text = "Name"
        self.age_label.text = "Age"
        # one keystroke updates the status bar, the name's log and the summary at once
        self.name_log.set_validator(self._check_name, self.greeting.text_edited)
        self.age_log.set_validator(self._check_age, self.age.text_edited)
        self.greeting.text_edited.connect(self._update_summary)
        self.age.text_edited.connect(self._update_summary)
        self.name_log.run_validator()
        self._update_summary()

    def _check_name(self) -> str | None:
        return "A name is mandatory" if self.greeting.text == "" else None

    def _check_age(self) -> str | None:
        age = self.age.value
        if age is None:
            return None
        if age < 0:
            return "An age can't be negative"
        if not age.is_integer():
            return "An age is a whole number of years"
        return None

    def _update_summary(self, _text: str = "") -> None:
        name = self.greeting.text or "Nobody"
        if self.age.value is None or self._check_age() is not None:
            self.summary.text = f"{name} hasn't said how old they are."
        else:
            self.summary.text = f"{name} is {int(self.age.value)} years old."


class HelloApp(WebApplication[HelloMainView]):
    def __init__(self) -> None:
        super().__init__(build_main_view=HelloMainView)


def main() -> None:
    HelloApp().run()


if __name__ == "__main__":
    main()
