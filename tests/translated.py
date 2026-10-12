"""A main view translated by `tests/locales`, shared by the core and backend tests."""

import enum
from pathlib import Path
from typing import Optional

from attrs import Factory

from composeui.core.view import (
    DialogView,
    GroupFormView,
    LabelRowComboboxView,
    LabelRowInputView,
    MainView,
    define_view,
)


class Size(enum.Enum):
    SMALL = enum.auto()
    LARGE = enum.auto()


@define_view
class SizeRowView(LabelRowComboboxView[Size]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.value = Size.LARGE

    def retranslate(self) -> None:
        super().retranslate()
        self.label = self.tr("Size")
        self.values = {self.tr("Small"): Size.SMALL, self.tr("Large"): Size.LARGE}


@define_view
class NameRowView(LabelRowInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.set_validator(self._check_name, self.text_edited)
        self.run_validator()

    def retranslate(self) -> None:
        super().retranslate()
        self.label = self.tr("Name")

    def _check_name(self) -> Optional[str]:
        return self.tr("A name is mandatory") if self.text == "" else None


@define_view
class ShapeFormView(GroupFormView):
    name: NameRowView = Factory(NameRowView)
    size: SizeRowView = Factory(SizeRowView)

    def retranslate(self) -> None:
        super().retranslate()
        self.title = self.tr("Shape")
        # over the row's own label: a parent has the last word
        self.size.label = self.tr("Shape size")


@define_view
class RemoveDialog(DialogView):
    def retranslate(self) -> None:
        super().retranslate()
        self.accept_text = self.tr("Remove")


@define_view
class DiscardDialog(DialogView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # set outside `retranslate`: the app doesn't translate it
        self.accept_text = "Discard"


@define_view
class TranslatedMainView(MainView):
    translations_dir = Path(__file__).parent / "locales"

    shape: ShapeFormView = Factory(ShapeFormView)
    confirm_remove: RemoveDialog = Factory(RemoveDialog)
    confirm_discard: DiscardDialog = Factory(DiscardDialog)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Shapes", extension=".shapes")
