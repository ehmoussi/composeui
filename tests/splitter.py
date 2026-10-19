"""A study beside its result, and a chart above its table, for `SplitterView`'s tests."""

from __future__ import annotations

import attrs

from composeui.core.view import (
    STRETCH,
    LabelView,
    MainView,
    Orientation,
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


@define_view
class ChartPane(VerticalView):
    chart: LabelView = child(LabelView, text="Chart")


@define_view
class TablePane(VerticalView):
    table: LabelView = child(LabelView, text="Table")


@define_view
class ResultSplitter(SplitterView):
    orientation = Orientation.VERTICAL

    chart: ChartPane = attrs.field(factory=ChartPane, metadata={STRETCH: 2})
    table: TablePane = attrs.Factory(TablePane)


@define_view
class VerticalSplitterMainView(MainView):
    app_title = "Result"
    extension = ".result"

    splitter: ResultSplitter = attrs.Factory(ResultSplitter)
