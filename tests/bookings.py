"""A booking's first day, shared by the backend tests of `DateInputView`."""

from __future__ import annotations

import datetime

from attrs import Factory

from composeui.core.view import FormView, LabelRowDateInputView, MainView, child, define_view


@define_view
class BookingForm(FormView):
    arrival: LabelRowDateInputView = child(
        LabelRowDateInputView,
        label="Arrival",
        value=datetime.date(2026, 10, 18),
        minimum=datetime.date(2026, 10, 1),
        maximum=datetime.date(2026, 12, 31),
    )


@define_view
class BookingMainView(MainView):
    app_title = "Booking"
    extension = ".booking"

    form: BookingForm = Factory(BookingForm)
