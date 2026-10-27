"""Tests for the cattrs (un)structure hooks and MainView state persistence."""

from __future__ import annotations

import datetime
import enum
import json
import logging
import math
from pathlib import Path
from typing import Any, Optional, Union

import pytest
from attrs import Factory, evolve

from composeui.core.application import _add_reference_to_signals
from composeui.core.renderer import Renderer, RendererContainer
from composeui.core.signal import Signal
from composeui.core.view import (
    CONVERTER,
    STATE_FORMAT,
    ActionView,
    ChartKind,
    ChartView,
    ComboBoxView,
    FloatInputMixin,
    InputView,
    InvalidStateError,
    LabelView,
    MainView,
    MetricView,
    ProgressBarView,
    RadioGroupView,
    ReferenceLine,
    SelectionMode,
    Series,
    SliderView,
    TreeNode,
    TreeView,
    _is_omitted_type,
    define_view,
    format_date,
    parse_date,
    replace_cell,
)
from examples.pipechart import PipeChartMainView
from tests.bookings import BookingMainView
from tests.buildings import SiteMainView, styled_site
from tests.datafiles import DataFileMainView
from tests.horizontal import HorizontalMainView
from tests.tables import EditableTableMainView
from tests.toolbar import ToolBarMainView


# Generic mixins must be bound to a concrete type through a subclass (like
# `EdgeTypeView(LabelRowRadioGroupView[EdgeType])` in examples/pipeform.py), not by
# annotating a field directly as `RadioGroupView[str]`: attrs/cattrs' type resolution
# machinery can't handle a subscripted generic alias used as a field's own type.
@define_view
class _StrRadioGroupView(RadioGroupView[str]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.values = {"a": "a", "b": "b"}


@define_view
class _RadioMainView(MainView):
    app_title = "Radio"
    extension = ".radio"

    radio: _StrRadioGroupView = Factory(_StrRadioGroupView)


@pytest.mark.parametrize(
    "text",
    ["2026-10-25T13:45:12.123456", "2026-10-25 13:45:12", "2026-10-25T13:45:12+05:30"],
)
def test_datetimes_structure_from_iso_text_or_native_values_and_round_trip(text: str) -> None:
    expected = datetime.datetime.fromisoformat(text)
    restored = CONVERTER.structure(text, datetime.datetime)
    assert type(restored) is datetime.datetime
    assert restored == expected
    assert CONVERTER.structure(expected, datetime.datetime) == expected
    saved = json.loads(json.dumps(CONVERTER.unstructure(restored)))
    assert saved == expected.isoformat()
    assert CONVERTER.structure(saved, datetime.datetime) == expected


def test_is_omitted_type_detects_signal_renderer_and_container() -> None:
    assert _is_omitted_type(Signal[str]) is True
    assert _is_omitted_type(Optional[Union[Renderer[Any, Any], RendererContainer[Any]]]) is True


def test_is_omitted_type_ignores_unrelated_types() -> None:
    assert _is_omitted_type(int) is False
    assert _is_omitted_type(Optional[int]) is False
    assert _is_omitted_type(type(None)) is False


def test_unstructure_omits_signal_and_renderer_fields() -> None:
    view = _RadioMainView()
    data = CONVERTER.unstructure(view)
    assert "renderer" not in data
    assert "renderer" not in data["radio"]
    assert "value_changed" not in data["radio"]


def test_unstructure_includes_radio_group_values() -> None:
    view = _RadioMainView()
    data = CONVERTER.unstructure(view)
    assert data["radio"]["values"] == {"a": "a", "b": "b"}


def test_load_state_ignores_values_even_though_saved(tmp_path: Path) -> None:
    view = _RadioMainView()
    view.radio.value = "a"
    filepath = tmp_path / "state.json"
    view.save_state(filepath)
    assert filepath.read_text().find('"values"') != -1  # sanity check it's actually there

    fresh = _RadioMainView()
    fresh.load_state(filepath)  # must not crash on the unresolved-TValue `values` dict
    assert fresh.radio.values == {"a": "a", "b": "b"}  # untouched, from __attrs_post_init__
    assert fresh.radio.value == "a"


def test_a_study_neither_saves_nor_sets_an_icon(tmp_path: Path) -> None:
    # the web backend serves an icon's file: a study naming one could read any file
    view = ToolBarMainView()
    view.toolbar.run.icon = "icons/run.svg"
    filepath = tmp_path / "state.json"
    view.save_state(filepath)
    assert '"icon"' not in filepath.read_text()

    data = view.state_data()
    data["toolbar"]["run"]["icon"] = "/etc/passwd"  # a study saved before, or forged
    view.load_state_data(data)
    assert view.toolbar.run.icon == "icons/run.svg"


def test_radio_group_rejects_a_value_not_in_values() -> None:
    view = _RadioMainView()
    with pytest.raises(ValueError, match="not one of the available values"):
        view.radio.value = "not-an-option"
    assert view.radio.value is None  # rejected assignment leaves the field unchanged


def test_radio_group_accepts_none_and_members_of_values() -> None:
    view = _RadioMainView()
    view.radio.value = "a"
    assert view.radio.value == "a"
    view.radio.value = None
    assert view.radio.value is None


def test_radio_group_rejects_a_value_when_values_is_still_empty() -> None:
    view = RadioGroupView[str]()
    with pytest.raises(ValueError, match="Set `values` before setting `value`"):
        view.value = "a"


def test_radio_group_clears_value_when_values_no_longer_contains_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    view = _RadioMainView()
    view.radio.value = "b"
    with caplog.at_level(logging.WARNING, logger="COMPOSEUI_VIEW"):
        view.radio.values = {"a": "a"}  # "b" no longer an option

    assert view.radio.value is None
    assert any("no longer contains" in record.message for record in caplog.records)


def test_radio_group_keeps_value_when_still_a_member_of_new_values() -> None:
    view = _RadioMainView()
    view.radio.value = "a"
    view.radio.values = {"a": "a", "c": "c"}
    assert view.radio.value == "a"


def test_a_progress_bar_shows_a_count_within_its_range_of_steps() -> None:
    assert ProgressBarView.clamp(120, 100) == 100  # a count overshooting its total
    assert ProgressBarView.clamp(-1, 100) == 0
    assert ProgressBarView.clamp(120, None) == 120  # a task of unknown length
    bar = ProgressBarView()
    with pytest.raises(ValueError, match="maximum"):
        bar.maximum = 0
    assert bar.maximum == 100


def test_a_series_has_one_y_per_x() -> None:
    series = Series(name="Pressure", x=(0, 1), y=[2, math.nan])  # any numbers, as floats
    assert (series.x, series.y[0]) == ([0.0, 1.0], 2.0)
    with pytest.raises(ValueError, match="2 x for 1 y"):
        Series(name="Pressure", x=[0, 1], y=[2])


def test_a_bar_series_puts_each_value_in_its_chart_s_category_in_order() -> None:
    series = Series.bars("Pickups", (count for count in [3, 0, 5]))  # any iterable
    assert (series.name, series.x, series.y) == ("Pickups", [0.0, 1.0, 2.0], [3.0, 0.0, 5.0])


def test_a_series_is_drawn_as_its_chart_unless_it_says_otherwise() -> None:
    line = Series(name="Model", x=[0], y=[0])
    dots = Series(name="Measured", x=[0], y=[0], kind=ChartKind.SCATTER)
    assert ChartView.kind_of(line, ChartKind.LINE) is ChartKind.LINE
    assert ChartView.kind_of(line, ChartKind.SCATTER) is ChartKind.SCATTER
    assert ChartView.kind_of(dots, ChartKind.LINE) is ChartKind.SCATTER


def test_a_bar_chart_draws_only_bars_a_bar_per_category() -> None:
    dots = Series(name="Measured", x=[0, 2, 0.5, 7, 2], y=[1, 2, 3, 4, 5], kind=ChartKind.SCATTER)
    assert ChartView.kind_of(dots, ChartKind.BAR) is ChartKind.BAR
    # by the category its x names; none past the categories, the last of one wins
    assert str(ChartView.bar_heights(dots, 3)) == str([1.0, math.nan, 5.0])
    with pytest.raises(ValueError, match="as bars"):
        Series(name="Measured", x=[0], y=[1], kind=ChartKind.BAR)


def test_a_category_s_bars_are_side_by_side_around_its_index() -> None:
    assert ChartView.bar_slot(0, 1) == (0, 0.8)
    assert ChartView.bar_slot(0, 2) == (-0.2, 0.4)
    assert ChartView.bar_slot(1, 2) == (0.2, 0.4)


def test_a_log_axis_leaves_out_what_it_cannot_show() -> None:
    series = Series(name="Decay", x=[-1, 0, 1, 10], y=[5, 5, 0, 10])
    assert ChartView.drawn_points(series, x_log=False, y_log=False) == (series.x, series.y)
    # an x of 0 or less: no point; a y of 0 or less: a gap
    x, y = ChartView.drawn_points(series, x_log=True, y_log=True)
    assert x == [1, 10]
    assert str(y) == str([math.nan, 10.0])
    assert ChartView.drawn_points(series, x_log=True, y_log=False) == ([1, 10], [0, 10])
    # the bars of 5 and 0 high: on a log axis, no bar of 0
    assert str(ChartView.bar_heights(series, 2, y_log=True)) == str([5.0, math.nan])
    # nor a reference line at 0, on its own axis only
    lines = [ReferenceLine(0, "Zero"), ReferenceLine(0, "Start", vertical=True)]
    assert ChartView.drawn_lines(lines, x_log=True, y_log=False) == lines[:1]
    assert ChartView.drawn_lines(lines, x_log=False, y_log=True) == lines[1:]


def test_a_step_line_holds_each_value_until_the_next_point() -> None:
    xs, ys = [0.0, 2.0, 5.0], [1.0, math.nan, 4.0]
    step_xs, step_ys = ChartView.step_points(xs, ys)
    assert step_xs == [0, 2, 2, 5, 5]
    assert str(step_ys) == str([1.0, 1.0, math.nan, math.nan, 4.0])  # its gap kept
    assert [ChartView.held_value(xs, ys, x) for x in (-1, 0, 1.9, 6)] == [None, 1, 1, 4]
    gap = ChartView.held_value(xs, ys, 3)
    assert gap is not None
    assert math.isnan(gap)


def test_a_series_color_is_given_as_rrggbb() -> None:
    assert Series(name="Oval", x=[0], y=[0], color="#FFD700", fill=True).color == "#FFD700"
    for color in ("yellow", "#ffd70", "ffd700"):
        with pytest.raises(ValueError, match="#rrggbb"):
            Series(name="Oval", x=[0], y=[0], color=color)


def test_a_reference_line_s_color_is_given_as_rrggbb() -> None:
    assert ReferenceLine(40, "Max: 40", color="#d03030").value == 40.0
    with pytest.raises(ValueError, match="#rrggbb"):
        ReferenceLine(40, "Max: 40", color="red")


def test_a_chart_s_height_is_positive_and_not_a_study_s() -> None:
    chart = ChartView(height=300)
    with pytest.raises(ValueError, match="positive"):
        chart.height = 0
    assert "height" not in CONVERTER.unstructure(chart)  # the app's layout


def test_an_axis_label_shows_its_unit() -> None:
    assert ChartView.axis_label("Time", "s") == "Time (s)"
    assert ChartView.axis_label("Time", "") == "Time"
    assert ChartView.axis_label("", "s") == "(s)"


def test_a_study_saves_its_charts_series(tmp_path: Path) -> None:
    view = PipeChartMainView()
    view.add_curve()
    path = tmp_path / "study.pipechart"
    view.save_state(path)

    loaded = PipeChartMainView()
    loaded.load_state(path)

    loaded.add_measurements()  # one series of its own kind
    names = [series.name for series in loaded.chart.series]
    assert names == ["D = 50 mm", "Measured, D = 50 mm"]
    saved, back = view.chart.series[0], loaded.chart.series[0]
    assert back.x == saved.x
    # the transitional flow's gap too: NaN is no number equal to itself
    assert any(math.isnan(drop) for drop in back.y)
    assert str(back.y) == str(saved.y)
    # the app's text, not the study's
    assert "title" not in json.loads(path.read_text())["views"]["results"]["chart_tab"]["chart"]


def test_a_tree_knows_its_nodes_by_path_and_keeps_those_new_nodes_still_hold() -> None:
    view = SiteMainView()
    tree = view.site
    # two "Floor 1": their own parents tell them apart
    tree.selected = ("Building B", "Floor 1", "Lobby")
    tree.expanded = [("Building A",), ("Building B", "Floor 1")]
    assert tree.node(("Building B", "Floor 1")).children == (TreeNode("Lobby"),)
    with pytest.raises(ValueError, match="none is there"):
        tree.selected = ("Building C",)
    with pytest.raises(ValueError, match="none is there"):
        tree.expanded = [("Parking", "Level 1")]
    with pytest.raises(ValueError, match="share the key"):
        TreeView(nodes=[TreeNode("Room"), TreeNode("Room")])
    TreeView(nodes=[TreeNode("Room", key="1"), TreeNode("Room", key="2")])

    tree.nodes = [TreeNode("Building A", [TreeNode("Floor 1")]), TreeNode("Building B")]
    assert (tree.expanded, tree.selected) == ([("Building A",)], None)
    assert tree.expanded_with(("Building B",), is_expanded=True) == [
        ("Building A",),
        ("Building B",),
    ]


def test_a_study_saves_its_trees_nodes_expanded_and_selected(tmp_path: Path) -> None:
    view = SiteMainView()
    view.site.nodes = [*view.site.nodes, TreeNode("Garden", [TreeNode("Shed", key="shed")])]
    view.site.expanded = [("Garden",)]
    view.site.selected = ("Garden", "shed")
    path = tmp_path / "study.site"
    view.save_state(path)

    loaded = SiteMainView()
    loaded.load_state(path)
    assert loaded.site.nodes == view.site.nodes
    assert (loaded.site.expanded, loaded.site.selected) == ([("Garden",)], ("Garden", "shed"))


def test_a_study_saves_its_tree_nodes_marks_and_styles_but_not_their_icons(
    tmp_path: Path,
) -> None:
    view = SiteMainView()
    # the web serves a node's icon file: a study must not name one
    view.site.nodes = styled_site(str(tmp_path / "secret.png"))
    path = tmp_path / "study.site"
    view.save_state(path)
    assert "secret.png" not in path.read_text()

    loaded = SiteMainView()
    loaded.load_state(path)
    (building, parking) = view.site.nodes
    assert loaded.site.nodes == [evolve(building, icon=None), parking]


@pytest.mark.parametrize(
    ("value", "decimals", "shown"),
    [
        (36.0, 0, "36"),
        (3.14159, 2, "3.14"),
        (2.5, 2, "2.5"),  # no trailing zeros
        (-0.001, 2, "0"),  # not "-0"
        (36.0, None, "36.0"),  # as `str` writes it
        (math.inf, 2, "inf"),
        (None, 2, ""),
    ],
)
def test_a_decimal_number_shows_at_most_its_decimals(
    value: Optional[float], decimals: Optional[int], shown: str
) -> None:
    assert FloatInputMixin.shown_text(value, decimals) == shown


def test_a_date_is_typed_and_shown_as_its_format_says_or_as_iso_8601() -> None:
    day = datetime.date(2026, 1, 2)
    assert format_date(day, "dd/MM/yyyy") == "02/01/2026"
    assert format_date(day, "yyyy. MM. dd.") == "2026. 01. 02."
    assert format_date(day, "dd/MM") == "2026-01-02"  # no year: a catalog's mistake
    assert parse_date("2/1/2026", "dd/MM/yyyy") == day  # single digits
    assert parse_date(" 02.01.2026 ", "dd.MM.yyyy.") == day  # the ending dot left out
    assert parse_date("2026-01-02", "MM/dd/yyyy") == day  # ISO 8601, whatever the format
    for text in ("31/02/2026", "2/1/26", "2026/01/02", "02/01/2026 x", ""):
        with pytest.raises(ValueError, match="isn't a date as dd/MM/yyyy"):
            parse_date(text, "dd/MM/yyyy")


def test_a_date_input_follows_the_language_and_its_study_keeps_its_dates(tmp_path: Path) -> None:
    view = BookingMainView()
    arrival = view.form.arrival
    assert arrival.shown_text(arrival.value) == "10/18/2026"
    view.set_language("fr")
    assert (arrival.shown_text(arrival.value), arrival.month_names[0]) == ("18/10/2026", "janvier")
    arrival.value = datetime.date(2027, 3, 4)
    path = tmp_path / "study.booking"
    view.save_state(path)
    saved = json.loads(path.read_text())["views"]["form"]["arrival"]
    assert (saved["value"], saved["minimum"]) == ("2027-03-04", "2026-10-01")
    assert "date_format" not in saved  # the language's, not the study's

    view.reset_state()  # a new study: its dates back, in the language still shown
    assert arrival.shown_text(arrival.value) == "18/10/2026"
    view.load_state(path)
    assert arrival.value == datetime.date(2027, 3, 4)


def test_a_study_keeps_a_file_path_but_not_the_file_types_the_app_offers(tmp_path: Path) -> None:
    view = DataFileMainView()
    measurements = view.form.measurements
    assert measurements.path is None
    measurements.text = " /data/flows.csv "
    measurements.extensions = {"Any": ("",)}
    path = tmp_path / "study.measurements"
    view.save_state(path)
    saved = json.loads(path.read_text())["views"]["form"]["measurements"]
    assert (saved["text"], saved["has_reload"]) == (" /data/flows.csv ", True)
    assert "extensions" not in saved  # the app's, not the study's

    view.reset_state()
    assert measurements.text == ""
    view.load_state(path)
    assert measurements.path == Path("/data/flows.csv")
    assert measurements.extensions == {"Any": ("",)}


def test_a_slider_shows_its_value_at_the_nearest_step_within_its_range() -> None:
    # steps 2, 5, 8, 11 and 14 (positions 0 to 4): 16 is no step
    assert SliderView.last_position(2, 16, 3) == 4
    assert SliderView.position(5, 2, 16, 3) == 1
    assert SliderView.position(7, 2, 16, 3) == 2
    assert SliderView.position(16, 2, 16, 3) == 4
    assert SliderView.position(-5, 2, 16, 3) == 0
    # halfway between two steps goes up, whatever the step
    assert SliderView.position(1, 0, 10, 2) == 1
    assert SliderView.position(3, 0, 10, 2) == 2
    # a maximum below the minimum leaves one step, the minimum
    assert SliderView.last_position(5, 0, 1) == 0
    assert SliderView.position(3, 5, 0, 1) == 0
    with pytest.raises(ValueError, match="step"):
        SliderView(step=0)


def test_a_metric_badge_points_the_way_its_figure_changed() -> None:
    assert MetricView.badge(2, "since yesterday") == "↑ 2 since yesterday"
    assert MetricView.badge(-1.5, "") == "↓ 1.5"
    assert MetricView.badge(0, "today") == "→ 0 today"
    # a float's own noise and a large count read as written
    assert MetricView.badge(0.1 + 0.2, "") == "↑ 0.3"
    assert MetricView.badge(1_000_000.0, "") == "↑ 1000000"


def test_unstructure_serializes_a_string_choice_as_itself() -> None:
    view = _RadioMainView()
    view.radio.value = "b"
    data = CONVERTER.unstructure(view)
    assert data["radio"]["value"] == "b"

    view.radio.value = None
    assert CONVERTER.unstructure(view)["radio"]["value"] is None


class _Edge(enum.Enum):
    ROUND = 1
    SHARP = 2


@define_view
class _EdgeComboBoxView(ComboBoxView[_Edge]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.values = {"Round": _Edge.ROUND, "Sharp": _Edge.SHARP}


@define_view
class _SizeComboBoxView(ComboBoxView[float]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.values = {"Small": 0.5, "Large": 2.0}


def test_a_choice_is_saved_by_a_key_its_label_in_another_language_still_loads() -> None:
    edge, size = _EdgeComboBoxView(), _SizeComboBoxView()
    edge.value, size.value = _Edge.SHARP, 2.0
    # an enum by its member's name, anything else by its position
    assert (edge.serialize_value(), size.serialize_value()) == ("SHARP", "1")
    assert edge.options == [("ROUND", "Round"), ("SHARP", "Sharp")]

    edge.values = {"Arrondi": _Edge.ROUND, "Vif": _Edge.SHARP}
    size.values = {"Petit": 0.5, "Grand": 2.0}

    assert edge.deserialize_value("SHARP") is _Edge.SHARP
    assert size.deserialize_value("1") == 2.0


def test_a_choice_saved_by_its_label_still_loads() -> None:
    """Older state files saved a choice by its label."""
    edge = _EdgeComboBoxView()

    assert edge.deserialize_value("Sharp") is _Edge.SHARP


def test_save_and_load_state_round_trip_preserves_renderer_bindings(tmp_path: Path) -> None:
    view = _RadioMainView()
    view.minimum_width = 999
    view.status_bar.message = "hi"
    view.radio.value = "b"

    filepath = tmp_path / "state.json"
    view.save_state(filepath)
    assert view.state_filepath == filepath

    fresh = _RadioMainView()
    status_bar_before = fresh.status_bar
    assert fresh.radio.value is None  # fresh view, nothing selected yet

    fresh.load_state(filepath)

    assert fresh.minimum_width == 999
    assert fresh.status_bar.message == "hi"
    assert fresh.status_bar is status_bar_before
    assert fresh.radio.value == "b"
    assert fresh.state_filepath == filepath
    assert fresh.title == "Radio"  # frozen field untouched


def test_save_state_does_not_crash_with_a_live_status_bar_timer(tmp_path: Path) -> None:
    view = _RadioMainView()
    view.status_bar.show_message("hi")  # starts a live threading.Timer
    try:
        filepath = tmp_path / "state.json"
        view.save_state(filepath)  # must not raise TypeError: Timer not JSON serializable
        assert '"_timer"' not in filepath.read_text()
    finally:
        if view.status_bar._timer is not None:  # noqa: SLF001
            view.status_bar._timer.cancel()  # noqa: SLF001


def test_load_state_warns_and_clears_value_when_label_no_longer_exists(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    saved = _RadioMainView()
    saved.radio.value = "b"
    filepath = tmp_path / "state.json"
    saved.save_state(filepath)

    fresh = _RadioMainView()
    fresh.radio.values = {"a": "a"}  # "b" option no longer exists
    with caplog.at_level(logging.WARNING, logger="COMPOSEUI_VIEW"):
        fresh.load_state(filepath)

    assert fresh.radio.value is None
    assert any("_StrRadioGroupView.value" in record.message for record in caplog.records)


@define_view
class _StudyMainView(MainView):
    app_title = "Study"
    extension = ".study"

    radio: _StrRadioGroupView = Factory(_StrRadioGroupView)
    note: InputView = Factory(InputView)
    heading: LabelView = Factory(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # set up after construction, not attrs defaults: a reset must restore these too
        self.radio.value = "a"
        self.note.text = "initial note"


@define_view
class _NextStudyMainView(_StudyMainView):
    """`_StudyMainView` at a new `state_version`, with no change of its state to upgrade."""

    state_version = 2


@define_view
class _RemarkStudyMainView(MainView):
    """The next version of `_StudyMainView`'s state: its `note` renamed `remark`."""

    extension = ".study"
    state_version = 2

    remark: InputView = Factory(InputView)

    def migrate_state(self, data: Any, version: int) -> Any:
        if version < 2:
            data["remark"] = data.pop("note")
        return data


def test_a_study_file_holds_its_versions_and_an_older_one_is_upgraded(tmp_path: Path) -> None:
    view = _StudyMainView()
    view.note.text = "kept"
    filepath = tmp_path / "old.study"
    view.save_state(filepath)

    data = json.loads(filepath.read_text())
    assert (data["composeui"], data["app"]) == ({"format": STATE_FORMAT}, {"version": 1})
    remark = _RemarkStudyMainView()
    remark.load_state(filepath)
    assert remark.remark.text == "kept"
    # without `migrate_state`, the state loads as it is
    unchanged = _NextStudyMainView()
    unchanged.load_state(filepath)
    assert unchanged.note.text == "kept"


def test_a_study_file_from_before_the_versions_opens_as_their_first(tmp_path: Path) -> None:
    filepath = tmp_path / "unversioned.study"
    filepath.write_text('{"note": {"text": "from before"}}')

    view = _RemarkStudyMainView()
    view.load_state(filepath)

    assert view.remark.text == "from before"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"app": {"version": 2}}, "saved by a newer version of this application"),
        ({"composeui": {"format": STATE_FORMAT + 1}}, "saved by a newer version of ComposeUI"),
        ({"app": {"version": 0}}, r"isn't a valid \.study file"),
        ({"app": {"version": "1"}}, r"isn't a valid \.study file"),
        ({"composeui": {"format": True}}, r"isn't a valid \.study file"),
        ({"composeui": 1}, r"isn't a valid \.study file"),
        ({"app": None}, r"isn't a valid \.study file"),
    ],
)
def test_a_study_file_of_a_newer_or_unknown_version_is_refused(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    view = _StudyMainView()
    filepath = tmp_path / "other.study"
    view.save_state(filepath)
    data = json.loads(filepath.read_text())
    data["views"]["note"]["text"] = "not loaded"
    filepath.write_text(json.dumps({**data, **change}))

    with pytest.raises(InvalidStateError, match=message):
        view.load_state(filepath)

    assert view.note.text == "initial note"


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '{"composeui": {"format": 1}, "app": {"version": 1}}',
        '{"composeui": {"format": 1}, "app": {"version": 1}, "views": []}',
    ],
)
def test_a_study_file_without_the_views_state_is_refused(tmp_path: Path, content: str) -> None:
    filepath = tmp_path / "other.study"
    filepath.write_text(content)

    with pytest.raises(InvalidStateError, match=r"isn't a valid \.study file"):
        _StudyMainView().load_state(filepath)


def test_a_study_file_its_upgrade_cannot_read_is_refused(tmp_path: Path) -> None:
    filepath = tmp_path / "old.study"
    filepath.write_text('{"composeui": {"format": 1}, "app": {"version": 1}, "views": {}}')
    view = _RemarkStudyMainView()

    with pytest.raises(InvalidStateError, match="doesn't match this application"):
        view.load_state(filepath)  # `migrate_state` finds no `note` to rename

    assert view.state_filepath is None


def test_reset_state_brings_back_a_newly_built_main_view_in_place() -> None:
    view = _StudyMainView()
    radio, note = view.radio, view.note
    seen: list[Optional[str]] = []

    def on_changed(value: Optional[str]) -> None:
        seen.append(value)

    radio.value_changed.connect(on_changed)
    radio.values = {"b": "b", "c": "c"}  # drops "a", which clears the value
    radio.value = "c"
    note.text = "edited"
    view.minimum_width = 1
    view.state_filepath = Path("old.study")

    view.reset_state()

    # the same view objects, so renderers bound to them keep working
    assert view.radio is radio
    assert view.note is note
    assert radio.values == {"a": "a", "b": "b"}
    assert radio.value == "a"
    assert note.text == "initial note"
    assert view.minimum_width == 720
    assert view.state_filepath is None
    assert view.title == "Study"  # frozen field untouched
    radio.value_changed.emit("b")  # connections survive the reset
    assert seen == ["b"]


def test_the_new_action_resets_the_main_view() -> None:
    view = _StudyMainView()
    _add_reference_to_signals(view, None)  # what an application does: injects `main_view`
    view.note.text = "edited"

    view.file_menu.new.triggered.emit()

    assert view.note.text == "initial note"


def test_triggering_a_checkable_action_toggles_it_before_its_callbacks_run() -> None:
    wrap = ActionView(text="Wrap", is_checkable=True)
    plain = ActionView(text="Refresh")
    seen: list[bool] = []
    wrap.triggered.connect(lambda: seen.append(wrap.is_checked))

    wrap.triggered.emit()
    wrap.triggered.emit()
    plain.triggered.emit()

    assert seen == [True, False]
    assert plain.is_checked is False


def test_load_state_restores_values_equal_to_attrs_defaults(tmp_path: Path) -> None:
    """A saved field equal to its attrs default must still be restored on load.

    `_StudyMainView` starts `note.text` at "initial note" (in `__attrs_post_init__`),
    not at `InputView`'s attrs default `""`: a study where the note was emptied must
    load back empty, not with the fresh view's starting text.
    """
    view = _StudyMainView()
    view.note.text = ""  # back to the attrs default, away from the starting state
    filepath = tmp_path / "study.study"
    view.save_state(filepath)  # `radio.is_visible` is saved at its attrs default, True

    loaded = _StudyMainView()
    # like pipeform's Fillet group, hidden at first until its option is picked
    loaded.radio.is_visible = False
    loaded.load_state(filepath)

    assert loaded.note.text == ""
    assert loaded.radio.is_visible is True


def test_ui_text_is_neither_saved_nor_loaded(tmp_path: Path) -> None:
    """Labels and titles come from the app's code and language, not from a study."""
    view = _StudyMainView()
    view.heading.text = "Notes"
    filepath = tmp_path / "study.study"
    view.save_state(filepath)

    data = json.loads(filepath.read_text())
    views = data["views"]
    assert "text" not in views["heading"]
    assert "title" not in views["file_menu"]
    assert "text" not in views["file_menu"]["new"]
    # a file saved before UI text was left out, e.g. in another language
    views["heading"]["text"] = "Remarques"
    views["note"]["text"] = "a note"
    filepath.write_text(json.dumps(data))
    view.load_state(filepath)

    assert view.heading.text == "Notes"
    assert view.note.text == "a note"


def test_load_state_failing_halfway_leaves_the_view_unchanged(tmp_path: Path) -> None:
    view = _StudyMainView()
    filepath = tmp_path / "bad.study"
    # `minimum_width` is valid and applied before the timeout fails to convert
    filepath.write_text('{"minimum_width": 1, "status_bar": {"timeout": "abc"}}')

    with pytest.raises(InvalidStateError, match="doesn't match this application"):
        view.load_state(filepath)

    assert view.minimum_width == 720
    assert view.state_filepath is None


def test_the_open_action_shows_why_a_state_file_is_rejected(tmp_path: Path) -> None:
    view = _StudyMainView()
    view.status_bar.timeout = 0  # no auto-clear timer left running after the test
    _add_reference_to_signals(view, None)
    filepath = tmp_path / "bad.study"
    filepath.write_text("{not json")
    view.file_view.filepath = filepath  # the answer a file dialog would give

    view.file_menu.open_file.triggered.emit()

    assert view.status_bar.message == "Can't open 'bad.study': it isn't a valid .study file."


def test_a_table_selects_only_one_of_its_rows_and_keeps_it_through_new_rows() -> None:
    table = HorizontalMainView().tables.narrow
    table.selected_rows = [2]

    for rows in ([3], [0, 0], [0, 1]):  # past the end, twice, or several rows
        with pytest.raises(ValueError, match="selected_rows"):
            table.selected_rows = rows
    assert table.selected_rows == [2]

    # East moved to the end, past the replaced rows' last index
    table.rows = [["West"], ["South"], ["Centre"], ["East"]]
    assert table.selected_rows == [3]
    # twice: either could be the one selected
    table.rows = [["East"], ["East"]]
    assert table.selected_rows == []
    table.selected_rows = [0]
    table.rows = [["North"]]
    assert table.selected_rows == []


def test_a_table_selecting_several_rows_keeps_each_through_new_rows() -> None:
    table = HorizontalMainView().tables.narrow
    table.selection_mode = SelectionMode.MULTIPLE
    table.selected_rows = [0, 2]

    # North dropped, East moved to the start
    table.rows = [["East"], ["South"], ["West"]]
    assert table.selected_rows == [0]
    table.selected_rows = [0, 1, 2]
    table.rows = [["West"], ["South"], ["East"]]
    assert table.selected_rows == [0, 1, 2]

    # back to a single row: the first selected one stays
    table.selection_mode = SelectionMode.SINGLE
    assert table.selected_rows == [0]


def test_rows_answering_an_edit_keep_its_row_selected_as_edited_or_as_it_was() -> None:
    table = EditableTableMainView().places
    table.rows = [["Harbour", "Busy"], ["Lake", "Calm"], ["Marsh", "Still"]]
    table.selection_mode = SelectionMode.MULTIPLE
    table.selected_rows = [0, 1]

    def answer(row: int, column: int, text: str) -> None:
        if text == "Windy":  # applied, the rows sorted by note: the lake moves last
            table.rows = sorted(replace_cell(table.rows, row, column, text), key=lambda r: r[1])
        elif text == "Foggy":  # refused, the same rows put back
            table.rows = [list(cells) for cells in table.rows]
        else:  # reformatted: the app's own row, neither the edited nor the old one
            table.rows = replace_cell(table.rows, row, column, text.upper())

    table.cell_edited.connect(answer)
    table.emit_cell_edited(1, 1, "Windy")
    assert table.rows == [["Harbour", "Busy"], ["Marsh", "Still"], ["Lake", "Windy"]]
    assert table.selected_rows == [0, 2]  # the harbour's untouched, the lake's moved
    table.emit_cell_edited(2, 1, "Foggy")
    assert table.selected_rows == [0, 2]
    table.emit_cell_edited(2, 1, "rainy")
    assert table.selected_rows == [0]
    # rows assigned after the edit hold the lake as they always did
    table.selected_rows = [2]
    table.rows = [["Lake", "RAINY"]]
    assert table.selected_rows == [0]


def test_load_state_restores_a_table_selection_with_its_rows(tmp_path: Path) -> None:
    view = HorizontalMainView()
    view.tables.wide.selection_mode = SelectionMode.MULTIPLE
    view.tables.wide.rows = [["A"], ["B"], ["C"]]
    view.tables.wide.selected_rows = [0, 2]
    path = tmp_path / "state.side"
    view.save_state(path)

    loaded = HorizontalMainView()
    loaded.load_state(path)

    assert loaded.tables.wide.selection_mode is SelectionMode.MULTIPLE
    assert loaded.tables.wide.rows == [["A"], ["B"], ["C"]]
    assert loaded.tables.wide.selected_rows == [0, 2]
