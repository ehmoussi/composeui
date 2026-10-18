"""A form creating a record beside two pages, shared by the backend tests of `SidebarView`."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import (
    ButtonView,
    FormView,
    LabelRowInputView,
    MainView,
    SidebarView,
    child,
    define_view,
)
from tests.pages import PagesRouter


@define_view
class NewRecordForm(FormView):
    name: LabelRowInputView = child(LabelRowInputView, label="Name")


@define_view
class NewRecordSidebar(SidebarView):
    form: NewRecordForm = Factory(NewRecordForm)
    create: ButtonView = child(ButtonView, text="Create")


@define_view
class SidebarMainView(MainView):
    app_title = "Records"
    extension = ".records"

    sidebar: NewRecordSidebar = child(NewRecordSidebar, title="New record")
    router: PagesRouter = Factory(PagesRouter)
