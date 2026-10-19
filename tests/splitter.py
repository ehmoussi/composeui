"""A study beside its result, shared by the backend tests of `SplitterView`."""

from __future__ import annotations

import attrs

from composeui.core.view import (
    STRETCH,
    LabelView,
    MainView,
    SplitterView,
    VerticalView,
    child,
    define_view,
)


@define_view
class StudyPane(VerticalView):
    study: LabelView = child(LabelView, text="Study 1")


@define_view
class SettingsPane(VerticalView):
    graph: LabelView = child(LabelView, text="Graph settings")


@define_view
class ResultPane(VerticalView):
    result: LabelView = child(LabelView, text="Result")


@define_view
class StudySplitter(SplitterView):
    study: StudyPane = attrs.Factory(StudyPane)
    settings: SettingsPane = attrs.Factory(SettingsPane)
    result: ResultPane = attrs.field(factory=ResultPane, metadata={STRETCH: 2})


@define_view
class SplitterMainView(MainView):
    app_title = "Study"
    extension = ".study"

    splitter: StudySplitter = attrs.Factory(StudySplitter)
