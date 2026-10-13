from __future__ import annotations

import enum

from attrs import Factory

from composeui.core.view import (
    FormView,
    LabelRowComboboxView,
    LabelRowFloatInputView,
    LabelRowInputView,
    LabelRowRadioGroupView,
    LabelView,
    MainView,
    define_view,
)
from composeui.webcore.webapplication import WebApplication


@define_view
class NameRowView(LabelRowInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Name"
        self.placeholder = "Type your name..."
        self.set_validator(self._check_name, self.text_edited)
        self.run_validator()

    def _check_name(self) -> str | None:
        return "A name is mandatory" if self.text == "" else None


@define_view
class AgeRowView(LabelRowFloatInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Age"
        self.placeholder = "Type your age..."
        self.minimum = 0
        self.decimals = 0
        self.set_validator(self._check_age, self.text_edited)

    def _check_age(self) -> str | None:
        if self.value is None:
            return None
        if self.value < 0:
            return "An age can't be negative"
        if not self.value.is_integer():
            return "An age is a whole number of years"
        return None


class GreetingStyle(enum.Enum):
    CASUAL = "Casual"
    FORMAL = "Formal"


@define_view
class GreetingStyleRowView(LabelRowRadioGroupView[GreetingStyle]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Greeting"
        self.values = {style.value: style for style in GreetingStyle}
        self.value = GreetingStyle.CASUAL


class Colour(enum.Enum):
    RED = "Red"
    GREEN = "Green"
    BLUE = "Blue"


@define_view
class ColourRowView(LabelRowComboboxView[Colour]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = "Favourite colour"
        # no initial value: the combobox starts on an empty choice
        self.values = {colour.value: colour for colour in Colour}


@define_view
class HelloFormView(FormView):
    name: NameRowView = Factory(NameRowView)
    age: AgeRowView = Factory(AgeRowView)
    style: GreetingStyleRowView = Factory(GreetingStyleRowView)
    colour: ColourRowView = Factory(ColourRowView)


@define_view
class HelloMainView(MainView):
    app_title = "Hello ComposeUI"
    extension = ".hello"

    form: HelloFormView = Factory(HelloFormView)
    summary: LabelView = Factory(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        form = self.form
        # one keystroke updates the status bar, the row's own log and the summary at once
        form.name.text_edited.connect(self._greet)
        form.style.value_changed.connect(self._greet)
        form.name.text_edited.connect(self._update_summary)
        form.age.text_edited.connect(self._update_summary)
        form.colour.value_changed.connect(self._update_summary)
        self._update_summary()

    def _greet(self, _changed: object = None) -> None:
        name = self.form.name.text
        if name == "":
            self.status_bar.show_message("")
        elif self.form.style.value == GreetingStyle.FORMAL:
            self.status_bar.show_message(f"Good day, {name}.")
        else:
            self.status_bar.show_message(f"Hello, {name}!")

    def _update_summary(self, _changed: object = None) -> None:
        form = self.form
        name = form.name.text or "Nobody"
        # the age row's own validator has already run: its log says whether it's valid
        if form.age.value is None or form.age.log_message != "":
            summary = f"{name} hasn't said how old they are"
        else:
            summary = f"{name} is {int(form.age.value)} years old"
        if form.colour.value is not None:
            summary += f" and likes {form.colour.value.value.lower()}"
        self.summary.text = f"{summary}."


class HelloApp(WebApplication[HelloMainView]):
    def __init__(self) -> None:
        super().__init__(build_main_view=HelloMainView)


def main() -> None:
    HelloApp().run()


if __name__ == "__main__":
    main()
