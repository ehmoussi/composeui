"""Tests of reactive methods: view methods run again when a field or a task they read changes."""

from __future__ import annotations

import gc
import subprocess
import sys
import threading
import weakref
from typing import TYPE_CHECKING, Any, cast

import pytest

from composeui.core.application import Application, ModelApplication
from composeui.core.model import Model
from composeui.core.reactivity import (
    ReactiveLoopError,
    reactive,
    reactive_inputs,
    start_reactions,
    stop_reactions,
)
from composeui.core.registry import RendererType
from composeui.core.view import (
    ButtonView,
    CheckBoxView,
    LabelRowSliderView,
    LabelView,
    ListView,
    MainView,
    MapPoint,
    MapView,
    SliderView,
    View,
    child,
    define_view,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot
    from qtpy.QtWidgets import QCheckBox

    from composeui.core.jobs import Job, Task
    from composeui.webcore.webrenderer import WebRenderer


@define_view
class HourView(MainView):
    """Shows the hour picked, only once the box is checked."""

    is_on: CheckBoxView = child(CheckBoxView, text="On")
    hour: LabelRowSliderView = child(LabelRowSliderView, label="Hour", maximum=23, value=11)
    shown: LabelView = child(LabelView)
    other: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        #: one item per run of `show_hour`
        self.runs: list[str] = []

    @reactive
    def show_hour(self) -> None:
        self.runs.append("show_hour")
        self.shown.text = f"{self.hour.value}:00" if self.is_on.is_checked else "Off"


def test_a_method_runs_at_the_start_then_again_only_for_the_fields_it_read() -> None:
    view = HourView()
    assert view.runs == []
    start_reactions(view)
    assert (view.shown.text, len(view.runs)) == ("Off", 1)
    # not read: the box is unchecked
    view.hour.value = 5
    view.other.text = "Not read either"
    assert len(view.runs) == 1

    view.is_on.is_checked = True
    assert (view.shown.text, len(view.runs)) == ("5:00", 2)
    view.hour.value = 6
    assert (view.shown.text, len(view.runs)) == ("6:00", 3)
    view.hour.value = 6  # the same value: no change
    assert len(view.runs) == 3
    assert reactive_inputs(view) == {"show_hour": ["is_on.is_checked", "hour.value"]}


def test_starting_twice_runs_a_method_once() -> None:
    view = HourView()
    start_reactions(view)
    start_reactions(view)
    assert len(view.runs) == 1


def test_stopped_methods_run_no_more_until_they_start_again() -> None:
    view = HourView()
    start_reactions(view)
    stop_reactions(view)
    view.is_on.is_checked = True
    assert (view.shown.text, len(view.runs)) == ("Off", 1)
    assert reactive_inputs(view) == {}

    start_reactions(view)
    assert view.shown.text == "11:00"


@define_view
class FormView(MainView):
    name: LabelView = child(LabelView)
    city: LabelView = child(LabelView)
    summary: LabelView = child(LabelView)
    save: ButtonView = child(ButtonView, text="Save")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.runs = 0

    @reactive
    def summarize(self) -> None:
        self.runs += 1
        self.summary.text = f"{self.name.text} in {self.city.text}"


def test_one_signal_s_changes_run_a_method_once_after_its_callbacks() -> None:
    view = FormView()
    start_reactions(view)
    summaries: list[str] = []

    def fill() -> None:
        view.name.text = "Ada"
        view.city.text = "London"
        # the method runs after the callbacks
        summaries.append(view.summary.text)

    view.save.clicked.connect(fill)
    view.save.clicked.emit()

    assert summaries == [" in "]
    assert (view.summary.text, view.runs) == ("Ada in London", 2)


def test_a_failing_callback_still_shows_the_changes_made_before_it_failed() -> None:
    view = FormView()
    start_reactions(view)

    def fail() -> None:
        view.name.text = "Ada"
        msg = "the callback's own error"
        raise RuntimeError(msg)

    view.save.clicked.connect(fail)
    with pytest.raises(RuntimeError, match="the callback's own error"):
        view.save.clicked.emit()

    assert view.summary.text == "Ada in "


def test_a_study_opened_or_started_over_runs_a_method_once(tmp_path: Path) -> None:
    view = HourView()
    start_reactions(view)
    view.is_on.is_checked = True
    view.hour.value = 5
    path = tmp_path / "study.json"
    view.save_state(path)
    view.runs.clear()

    view.reset_state()
    assert (view.shown.text, len(view.runs)) == ("Off", 1)
    view.load_state(path)
    assert (view.shown.text, len(view.runs)) == ("5:00", 2)


@define_view
class ChainView(MainView):
    first: LabelView = child(LabelView)
    second: LabelView = child(LabelView)
    third: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.runs: list[str] = []

    # before the method that gives it its input: it runs again after it
    @reactive
    def exclaim(self) -> None:
        self.runs.append("exclaim")
        self.third.text = f"{self.second.text}!"

    @reactive
    def shout(self) -> None:
        self.runs.append("shout")
        self.second.text = self.first.text.upper()


def test_methods_feeding_each_other_settle_in_one_change() -> None:
    view = ChainView()
    start_reactions(view)
    view.runs.clear()

    view.first.text = "hi"

    assert view.third.text == "HI!"
    assert view.runs == ["shout", "exclaim"]


@define_view
class TaxView(MainView):
    price: SliderView = child(SliderView, value=10)
    taxed: LabelView = child(LabelView)
    summary: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.runs: list[str] = []

    @reactive
    def show_summary(self) -> None:
        self.runs.append("summary")
        self.summary.text = f"{self.price.value} -> {self.taxed.text}"

    @reactive
    def tax(self) -> None:
        self.runs.append("tax")
        self.taxed.text = str(self.price.value * 2)


def test_methods_run_in_their_start_order_whatever_ran_before() -> None:
    view = TaxView()
    start_reactions(view)
    assert view.runs == ["summary", "tax", "summary"]

    view.runs.clear()
    view.price.value = 20
    # the same order again, though show_summary last read the price after tax did
    assert view.runs == ["summary", "tax", "summary"]
    assert view.summary.text == "20 -> 40"


@define_view
class TaxFirstView(MainView):
    price: SliderView = child(SliderView, value=10)
    taxed: LabelView = child(LabelView)
    summary: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.runs: list[str] = []

    @reactive
    def tax(self) -> None:
        self.runs.append("tax")
        self.taxed.text = str(self.price.value * 2)

    @reactive
    def show_summary(self) -> None:
        self.runs.append("summary")
        self.summary.text = f"{self.price.value} -> {self.taxed.text}"


def test_a_waiting_method_whose_input_an_earlier_one_sets_runs_once() -> None:
    view = TaxFirstView()
    start_reactions(view)
    view.runs.clear()

    view.price.value = 20

    assert view.runs == ["tax", "summary"]
    assert view.summary.text == "20 -> 40"


@define_view
class PointsView(MainView):
    pickups: MapView = child(MapView)
    count: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.runs = 0

    @reactive
    def count_points(self) -> None:
        self.runs += 1
        self.count.text = str(len(self.pickups.points))


def test_a_list_set_again_is_a_change_even_equal() -> None:
    view = PointsView()
    start_reactions(view)

    view.pickups.points = []
    assert view.runs == 2
    view.pickups.points += [MapPoint(latitude=48.9, longitude=2.3)]
    assert (view.runs, view.count.text) == (3, "1")


@define_view
class EchoView(MainView):
    text: LabelView = child(LabelView, text="hi")

    @reactive
    def shout(self) -> None:
        self.text.text = self.text.text.upper()


def test_a_method_setting_a_field_it_read_is_refused_even_unchanged() -> None:
    view = EchoView()
    with pytest.raises(
        ReactiveLoopError,
        match=r"EchoView\.shout sets LabelView\.text.*from a signal's callback instead",
    ):
        start_reactions(view)
    # refused too when the value it sets doesn't change: what the method does decides,
    # not the data
    with pytest.raises(ReactiveLoopError, match=r"EchoView\.shout sets LabelView\.text"):
        view.text.text = "HI"


@define_view
class PingPongView(MainView):
    is_on: CheckBoxView = child(CheckBoxView, text="Play")
    ping: LabelRowSliderView = child(LabelRowSliderView, label="Ping", maximum=1000)
    pong: LabelRowSliderView = child(LabelRowSliderView, label="Pong", maximum=1000)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.runs = 0

    @reactive
    def answer_ping(self) -> None:
        self.runs += 1
        if self.is_on.is_checked:
            self.pong.value = self.ping.value + 1

    @reactive
    def answer_pong(self) -> None:
        if self.is_on.is_checked:
            self.ping.value = self.pong.value + 1


def test_methods_changing_each_other_without_end_raise_rather_than_hang() -> None:
    view = PingPongView()
    start_reactions(view)

    with pytest.raises(ReactiveLoopError, match=r"answer_p[io]ng ran 100 times for one change"):
        view.is_on.is_checked = True

    # the loop is over: the next change runs the methods as before
    view.runs = 0
    view.is_on.is_checked = False
    assert view.runs == 1
    pong = view.pong.value
    view.ping.value = 3  # not read with the box unchecked
    assert (view.runs, view.pong.value) == (1, pong)


@define_view
class FailingView(MainView):
    source: LabelView = child(LabelView)
    copy: LabelView = child(LabelView)

    @reactive
    def check(self) -> None:
        if self.source.text == "boom":
            msg = "the method's own error"
            raise ValueError(msg)

    @reactive
    def copy_source(self) -> None:
        self.copy.text = self.source.text


@define_view
class TwiceFailingView(FailingView):
    @reactive
    def check_again(self) -> None:
        if self.source.text == "boom":
            msg = "the other method's error"
            raise KeyError(msg)


def test_two_failing_methods_raise_the_first_error_and_log_the_other(
    caplog: pytest.LogCaptureFixture,
) -> None:
    view = TwiceFailingView()
    start_reactions(view)

    with pytest.raises(ValueError, match="the method's own error"):
        view.source.text = "boom"

    assert view.copy.text == "boom"
    (record,) = caplog.records
    assert record.getMessage() == "The reactive method TwiceFailingView.check_again failed too"
    assert isinstance(record.exc_info, tuple)
    assert isinstance(record.exc_info[1], KeyError)


def test_a_failing_method_lets_the_others_show_the_change_then_raises() -> None:
    view = FailingView()
    start_reactions(view)

    with pytest.raises(ValueError, match="the method's own error"):
        view.source.text = "boom"

    assert view.copy.text == "boom"
    # it read its input before it failed: it runs again when the input changes
    view.source.text = "fine"
    assert view.copy.text == "fine"


@define_view
class PlainSubclassView(HourView):
    def show_hour(self) -> None:
        self.runs.append("plain")


def test_a_subclass_s_plain_method_replaces_a_reactive_one() -> None:
    view = PlainSubclassView()
    start_reactions(view)
    assert view.runs == []


def test_an_async_method_is_refused() -> None:
    async def show(_view: View) -> None:
        pass

    with pytest.raises(TypeError, match="must be synchronous"):
        reactive(cast("Any", show))


# tasks


def square(_job: Job[int], value: int) -> int:
    return value * value


@define_view
class SquareView(MainView):
    number: LabelRowSliderView = child(LabelRowSliderView, label="Number", maximum=100)
    shown: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.squares: Task[int, [int], None] = self.jobs.task(square, debounce=0)

    @reactive
    def compute(self) -> None:
        self.squares.start_latest(self.number.value)

    @reactive
    def show(self) -> None:
        result = self.squares.result
        self.shown.text = "..." if result is None else str(result)


def test_a_task_s_result_is_an_input_and_start_latest_follows_the_field() -> None:
    view = SquareView()
    start_reactions(view)
    assert view.shown.text == "..."
    view.jobs.wait()
    assert view.shown.text == "0"

    view.number.value = 7
    view.jobs.wait()

    assert view.shown.text == "49"
    assert reactive_inputs(view) == {"compute": ["number.value"], "show": ["squares"]}


@define_view
class LoadOnceView(MainView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loads = 0
        self.loader: Task[int, [], None] = self.jobs.task(self.load_rows)

    def load_rows(self, _job: Job[int]) -> int:
        self.loads += 1
        return self.loads

    @reactive
    def load(self) -> None:
        self.loader.start()


def test_a_method_starting_a_task_runs_once_without_reading_its_state() -> None:
    view = LoadOnceView()
    start_reactions(view)

    view.jobs.wait()

    assert (view.loads, view.loader.result, view.loader.is_running) == (1, 1, False)
    assert reactive_inputs(view) == {"load": []}


@define_view
class RestartView(MainView):
    shown: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.squares: Task[int, [int], None] = self.jobs.task(square, debounce=0)

    @reactive
    def restart(self) -> None:
        if not self.squares.is_running:
            self.squares.start_latest(2)


def test_a_method_starting_a_task_whose_state_it_read_is_refused() -> None:
    view = RestartView()

    with pytest.raises(ReactiveLoopError, match=r"RestartView\.restart starts the task square"):
        start_reactions(view)

    assert not view.squares.is_running


@define_view
class LatestView(MainView):
    shown: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.threads: dict[int, threading.Thread] = {}
        self.calls: list[int] = []
        self.task: Task[int, [int], None] = self.jobs.task(self.work, debounce=0)

    def work(self, _job: Job[int], value: int) -> int:
        # a slow query that never looks whether it was canceled
        self.calls.append(value)
        self.threads[value] = threading.current_thread()
        self.started.set()
        if value == 1:
            assert self.release.wait(10)
        return value * 10

    @reactive
    def show(self) -> None:
        self.shown.text = str(self.task.result)


def test_a_slow_obsolete_run_never_overwrites_the_latest_result() -> None:
    view = LatestView()
    start_reactions(view)
    finished: list[int] = []
    view.task.finished.connect(finished.append)
    view.task.start_latest(1)
    assert view.started.wait(10)
    view.started.clear()

    view.task.start_latest(2)
    # the last result stays until the new run's outcome
    assert view.task.is_running
    assert view.started.wait(10)
    view.threads[2].join(10)
    # the obsolete run ends last, its outcome handed over after the latest's
    view.release.set()
    view.threads[1].join(10)
    view.jobs.wait()
    view.jobs.start(square, 0)  # its outcome comes after them: wait hands them all over
    view.jobs.wait()

    assert (view.shown.text, view.task.result, finished) == ("20", 20, [20])


def test_quick_calls_of_start_latest_run_the_work_once() -> None:
    view = LatestView()
    view.task.debounce = 0.5
    for value in (2, 3, 4):
        view.task.start_latest(value)

    view.jobs.wait()

    assert (view.calls, view.task.result) == ([4], 40)


def test_canceling_during_the_debounce_ends_the_run_at_once() -> None:
    def count(job: Job[int]) -> int:
        return -1 if job.is_canceled else 1

    view = MainView()
    task = view.jobs.task(count, debounce=10)
    task.start_latest()
    task.cancel()

    view.jobs.wait(timeout=5)

    assert task.result == -1


# views built and dropped later


@define_view
class NameItem(View):
    name: LabelView = child(LabelView)
    title: LabelView = child(LabelView)

    @reactive
    def show_title(self) -> None:
        self.title.text = self.name.text.title()


@define_view
class Names(ListView[str]):
    def build_item(self, item: str) -> View:
        return NameItem(name=LabelView(text=item))


@define_view
class NamesView(MainView):
    names: Names = child(Names)
    clear: ButtonView = child(ButtonView, text="Clear")


def test_a_list_s_new_items_start_their_methods_and_its_removed_ones_stop() -> None:
    app = Application(build_main_view=NamesView)
    names = app.main_view.names
    names.items = ["ada lovelace"]
    (ada,) = names.item_views
    assert isinstance(ada, NameItem)
    assert ada.title.text == "Ada Lovelace"

    names.items = ["alan turing"]
    ada.name.text = "ada byron"

    (alan,) = names.item_views
    assert isinstance(alan, NameItem)
    assert alan.title.text == "Alan Turing"
    assert ada.title.text == "Ada Lovelace"


def test_an_item_removed_by_the_event_that_changed_it_runs_no_method() -> None:
    app = Application(build_main_view=NamesView)
    names = app.main_view.names
    names.items = ["ada lovelace"]
    (ada,) = names.item_views
    assert isinstance(ada, NameItem)

    def rename_and_clear() -> None:
        ada.name.text = "ada byron"
        names.items = []

    app.main_view.clear.clicked.connect(rename_and_clear)
    app.main_view.clear.clicked.emit()

    assert ada.title.text == "Ada Lovelace"


@define_view
class CardView(MainView):
    card: NameItem = child(NameItem)
    shown: LabelView = child(LabelView)

    @reactive
    def show_card(self) -> None:
        self.shown.text = self.card.title.text


def test_a_child_view_set_after_the_start_starts_its_methods_and_the_old_one_stops() -> None:
    view = CardView()
    start_reactions(view)
    old = view.card

    view.card = NameItem(name=LabelView(text="alan turing"))
    old.name.text = "ada byron"

    assert view.card.title.text == "Alan Turing"
    assert old.title.text == ""


def test_a_method_reading_through_a_child_view_follows_the_one_set_in_its_place() -> None:
    view = CardView()
    start_reactions(view)
    old = view.card

    view.card = NameItem(name=LabelView(text="alan turing"))
    assert view.shown.text == "Alan Turing"
    view.card.name.text = "grace hopper"
    assert view.shown.text == "Grace Hopper"
    old.name.text = "ada byron"
    assert view.shown.text == "Grace Hopper"
    # the child view read on the way isn't listed: its fields are
    assert reactive_inputs(view) == {"show_card": ["card.title.text"]}


def test_the_app_starts_the_methods_once_its_model_is_set_up() -> None:
    def set_up(view: ReaderView, _model: Model) -> None:
        view.panel = HourItem()

    app = ModelApplication(build_main_view=ReaderView, build_model=Model, setup_model=set_up)

    assert app.main_view.shown.text == "0"


@define_view
class HourItem(View):
    hour: LabelRowSliderView = child(LabelRowSliderView, label="Hour", maximum=23)


@define_view
class ReaderView(MainView):
    shown: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        #: a view outside the tree, e.g. a panel shared by several pages
        self.panel: HourItem | None = None

    @reactive
    def show(self) -> None:
        if self.panel is not None:
            self.shown.text = str(self.panel.hour.value)


def test_a_view_dropped_without_stopping_its_methods_is_collected() -> None:
    panel = HourItem()
    view = ReaderView()
    view.panel = panel
    start_reactions(view)
    assert reactive_inputs(view) == {"show": ["panel.hour.value"]}
    reference = weakref.ref(view)

    del view
    gc.collect()

    assert reference() is None
    panel.hour.value = 5  # its reader is gone with it


#: a view outside any main view's tree
SHARED = HourItem()


@define_view
class SharedReaderView(ReaderView):
    @reactive
    def show_shared(self) -> None:
        self.shown.text = str(SHARED.hour.value)


def test_the_inputs_name_a_view_outside_the_tree_by_its_class_and_a_collected_one() -> None:
    view = SharedReaderView()
    view.panel = HourItem()
    start_reactions(view)
    assert reactive_inputs(view) == {
        "show_shared": ["LabelRowSliderView.value"],
        "show": ["panel.hour.value"],
    }

    view.panel = None  # not a field: the method doesn't run again
    gc.collect()

    assert reactive_inputs(view)["show"] == ["value"]


def test_concurrent_sessions_record_only_their_own_reads() -> None:
    blocked, other = HourView(), HourView()
    blocked.is_on.is_checked = other.is_on.is_checked = True
    entered, proceed = threading.Event(), threading.Event()
    # its method waits mid-run, before its reads, for the other session's work
    blocked.runs = _WaitingList(entered, proceed)
    thread = threading.Thread(target=start_reactions, args=(blocked,))
    thread.start()
    assert entered.wait(10)
    start_reactions(other)
    other.hour.value = 3
    assert other.other.text == ""  # a read outside any method
    proceed.set()
    thread.join(10)

    expected = {"show_hour": ["is_on.is_checked", "hour.value"]}
    assert reactive_inputs(blocked) == reactive_inputs(other) == expected
    assert (blocked.shown.text, other.shown.text) == ("11:00", "3:00")
    other.other.text = "Changed"
    other.hour.value = 4
    assert blocked.shown.text == "11:00"


class _WaitingList(list[str]):
    """A list of runs whose `append` waits, mid-run, for the other thread."""

    def __init__(self, entered: threading.Event, proceed: threading.Event) -> None:
        super().__init__()
        self._entered = entered
        self._proceed = proceed

    def append(self, item: str) -> None:
        super().append(item)
        self._entered.set()
        assert self._proceed.wait(10)


def test_an_app_without_reactive_methods_reads_its_fields_as_before() -> None:
    code = """
from composeui.core.reactivity import is_enabled, reactive, start_reactions
from composeui.core.view import LabelView, MainView, child, define_view

assert not is_enabled()
assert "text" not in vars(LabelView)
assert not hasattr(LabelView, "text")


@define_view
class CopyView(MainView):
    source: LabelView = child(LabelView)
    copy: LabelView = child(LabelView)

    # the first reactive method tracks the fields of the classes defined before it
    @reactive
    def copy_source(self) -> None:
        self.copy.text = self.source.text


assert is_enabled()
view = CopyView()
start_reactions(view)
view.source.text = "Copied"
assert view.copy.text == "Copied"
"""
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603 (our own code)


# backends


def test_a_web_event_s_response_carries_what_the_methods_changed() -> None:
    session_module = pytest.importorskip("composeui.webcore.session")
    view = HourView()
    start_reactions(view)
    renderer_type: type[WebRenderer] = pytest.importorskip(
        "composeui.webcore.webrenderer"
    ).WebRenderer
    session = session_module.WebSession(view)
    box, shown = view.is_on.renderer, view.shown.renderer
    assert isinstance(box, renderer_type)
    assert isinstance(shown, renderer_type)

    response = session.handle_event(cast("WebRenderer", box).widget_id, "change", {"checked": "on"})

    assert response is not None
    body, _path = response
    assert f'id="{cast("WebRenderer", shown).widget_id}"' in body
    assert "11:00" in body


def test_an_ended_web_session_leaves_no_reader_and_is_collected() -> None:
    session_module = pytest.importorskip("composeui.webcore.session")
    panel = HourItem()
    view = ReaderView()
    view.panel = panel
    start_reactions(view)
    session = session_module.WebSession(view)
    reference = weakref.ref(view)

    session.close()
    panel.hour.value = 5
    assert view.shown.text == "0"
    assert reactive_inputs(view) == {}

    del session, view
    gc.collect()
    assert reference() is None


@define_view
class NamedBoxView(MainView):
    box: CheckBoxView = child(CheckBoxView, text="Off")

    @reactive
    def name_box(self) -> None:
        self.box.text = "On" if self.box.is_checked else "Off"


def test_a_method_changing_the_widget_the_user_changed_shows_on_it(qtbot: QtBot) -> None:
    qt_widgets = pytest.importorskip("qtpy.QtWidgets")
    box_type: type[QCheckBox] = qt_widgets.QCheckBox
    view = NamedBoxView()
    start_reactions(view)
    view.render(RendererType.QT)
    window = getattr(view.renderer, "qt_object", None)
    assert isinstance(window, qt_widgets.QWidget)
    qtbot.addWidget(window)
    box = getattr(view.box.renderer, "qt_object", None)
    assert isinstance(box, box_type)

    box.click()

    assert (view.box.text, box.text()) == ("On", "On")
