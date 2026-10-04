from __future__ import annotations

import enum

from attrs import Factory

from composeui.core.view import (
    ComboboxView,
    FloatInputView,
    InputView,
    LabelView,
    LogView,
    MainView,
    RadioGroupView,
    define_view,
)
from composeui.webcore.webapplication import WebApplication


@define_view
class GreetingInputView(InputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.placeholder = "Type your name..."


@define_view
class AgeInputView(FloatInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.placeholder = "Type your age..."
        self.minimum = 0
        self.decimals = 0


class GreetingStyle(enum.Enum):
    CASUAL = "Casual"
    FORMAL = "Formal"


@define_view
class GreetingStyleView(RadioGroupView[GreetingStyle]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.values = {style.value: style for style in GreetingStyle}
        self.value = GreetingStyle.CASUAL


class Colour(enum.Enum):
    RED = "Red"
    GREEN = "Green"
    BLUE = "Blue"


@define_view
class ColourView(ComboboxView[Colour]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # no initial value: the combobox starts on an empty choice
        self.values = {colour.value: colour for colour in Colour}


@define_view
class HelloMainView(MainView):
    name_label: LabelView = Factory(LabelView)
    greeting: GreetingInputView = Factory(GreetingInputView)
    name_log: LogView = Factory(LogView)
    age_label: LabelView = Factory(LabelView)
    age: AgeInputView = Factory(AgeInputView)
    age_log: LogView = Factory(LogView)
    style_label: LabelView = Factory(LabelView)
    style: GreetingStyleView = Factory(GreetingStyleView)
    colour_label: LabelView = Factory(LabelView)
    colour: ColourView = Factory(ColourView)
    summary: LabelView = Factory(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Hello ComposeUI", extension=".hello")
        self.name_label.text = "Name"
        self.age_label.text = "Age"
        self.style_label.text = "Greeting"
        self.colour_label.text = "Favourite colour"
        # one keystroke updates the status bar, the name's log and the summary at once
        self.name_log.set_validator(self._check_name, self.greeting.text_edited)
        self.age_log.set_validator(self._check_age, self.age.text_edited)
        self.greeting.text_edited.connect(self._greet)
        self.style.value_changed.connect(self._greet)
        self.greeting.text_edited.connect(self._update_summary)
        self.age.text_edited.connect(self._update_summary)
        self.colour.value_changed.connect(self._update_summary)
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

    def _greet(self, _changed: object = None) -> None:
        name = self.greeting.text
        if name == "":
            self.status_bar.show_message("")
        elif self.style.value == GreetingStyle.FORMAL:
            self.status_bar.show_message(f"Good day, {name}.")
        else:
            self.status_bar.show_message(f"Hello, {name}!")

    def _update_summary(self, _changed: object = None) -> None:
        name = self.greeting.text or "Nobody"
        if self.age.value is None or self._check_age() is not None:
            summary = f"{name} hasn't said how old they are"
        else:
            summary = f"{name} is {int(self.age.value)} years old"
        if self.colour.value is not None:
            summary += f" and likes {self.colour.value.value.lower()}"
        self.summary.text = f"{summary}."


class HelloApp(WebApplication[HelloMainView]):
    def __init__(self) -> None:
        super().__init__(build_main_view=HelloMainView)


def main() -> None:
    HelloApp().run()


if __name__ == "__main__":
    main()
