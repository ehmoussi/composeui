"""Filters whose first choice, None, keeps every row, shared by the backend tests of choices."""

from __future__ import annotations

from typing import Optional

from attrs import Factory

from composeui.core.view import (
    FormView,
    LabelRowComboBoxView,
    LabelRowRadioGroupView,
    MainView,
    child,
    define_view,
)

#: "All" first, its value None: the choice a filter keeps every row with
REGIONS: dict[str, Optional[str]] = {"All regions": None, "North": "north", "South": "south"}


@define_view
class FiltersForm(FormView):
    region: LabelRowComboBoxView[Optional[str]] = child(
        LabelRowComboBoxView[Optional[str]], label="Region", values=REGIONS
    )
    shown: LabelRowRadioGroupView[Optional[str]] = child(
        LabelRowRadioGroupView[Optional[str]], label="Shown", values=REGIONS
    )


@define_view
class FiltersMainView(MainView):
    app_title = "Filters"
    extension = ".filters"

    form: FiltersForm = Factory(FiltersForm)
