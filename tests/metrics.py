"""A row of metrics, shared by the backend tests of `MetricView`."""

from __future__ import annotations

from attrs import Factory

from composeui.core.view import HorizontalView, MainView, MetricView, child, define_view


@define_view
class JobsRow(HorizontalView):
    running: MetricView = child(
        MetricView, label="Running", value="3", delta=2, delta_text="since yesterday"
    )
    failed: MetricView = child(MetricView, label="Failed", value="1")


@define_view
class JobsMainView(MainView):
    app_title = "Jobs"
    extension = ".jobs"

    summary: JobsRow = Factory(JobsRow)
