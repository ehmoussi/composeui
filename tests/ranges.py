"""Ranges, shared by the backend tests of the range sliders and the date range."""

from __future__ import annotations

import datetime

from composeui.core.view import (
    LabelRowDateRangeInputView,
    LabelRowFloatRangeSliderView,
    LabelRowRangeSliderView,
    MainView,
    child,
    define_view,
)

FIRST_DAY, LAST_DAY = datetime.date(2014, 9, 1), datetime.date(2014, 9, 30)


@define_view
class RangesMainView(MainView):
    app_title = "Ranges"
    extension = ".ranges"

    hours: LabelRowRangeSliderView = child(
        LabelRowRangeSliderView, label="Hours", minimum=0, maximum=23, value=(8, 18)
    )
    distance: LabelRowFloatRangeSliderView = child(
        LabelRowFloatRangeSliderView,
        label="Distance",
        minimum=0.0,
        maximum=3.0,
        step=0.5,
        value=(0.5, 2.0),
    )
    days: LabelRowDateRangeInputView = child(
        LabelRowDateRangeInputView,
        label="Days",
        minimum=FIRST_DAY,
        maximum=LAST_DAY,
        value=(FIRST_DAY, None),
    )
