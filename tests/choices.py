"""Choices of several values, shared by the backend tests of the check list and multi-combobox."""

from __future__ import annotations

import enum

from composeui.core.view import (
    CheckListView,
    LabelRowMultiComboBoxView,
    MainView,
    child,
    define_view,
)


class Base(enum.Enum):
    UNTER = 1
    HINTER = 2
    WEITER = 3


@define_view
class BasesRow(LabelRowMultiComboBoxView[Base]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.values = {"Unter": Base.UNTER, "Hinter": Base.HINTER, "Weiter": Base.WEITER}


@define_view
class HoursList(CheckListView[int]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.values = {"Early morning": 5, "Morning": 9, "Noon": 12, "Evening": 19}


@define_view
class ChoicesMainView(MainView):
    app_title = "Choices"
    extension = ".choices"

    bases: BasesRow = child(BasesRow, label="Bases")
    hours: HoursList = child(HoursList, has_search=True)


@define_view
class OneBaseMainView(ChoicesMainView):
    """Keeps a base chosen: the last one unchecked is checked again, in code."""

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.bases.selected_changed.connect(self._keep_one)

    def _keep_one(self, selected: list[Base]) -> None:
        if selected == []:
            self.bases.selected = [Base.UNTER]
