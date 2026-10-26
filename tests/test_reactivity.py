"""Automatic dependencies, update timing and lifecycle of reactive view methods."""

from __future__ import annotations

import gc
import threading
import weakref
from typing import TYPE_CHECKING

import attrs
import pytest

from composeui.core.reactivity import ReactiveCycleError, batch_updates, reactive
from composeui.core.registry import RendererType
from composeui.core.view import IntInputView, LabelView, MainView, child, define_view

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from composeui.core.jobs import Job


@define_view
class _Order(MainView):
    app_title = "Order"
    extension = ".order"
    quantity: IntInputView = child(IntInputView, value=2)
    price: IntInputView = child(IntInputView, value=3)
    total: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.runs: list[tuple[int, int]] = []
        self.activate_reactions()

    def subtotal(self) -> int:
        quantity, price = self.quantity.value or 0, self.price.value or 0
        self.runs.append((quantity, price))
        return quantity * price

    @reactive
    def show_total(self) -> None:
        self.total.text = str(self.subtotal())


def test_reactions_follow_widget_edits_and_assignments_without_signals(qtbot: QtBot) -> None:
    widgets = pytest.importorskip("qtpy.QtWidgets")
    core = pytest.importorskip("qtpy.QtCore")
    renderers = pytest.importorskip("composeui.qtcore.qtrenderer")
    form = _Order()
    form.render(RendererType.QT)
    assert isinstance(form.renderer, renderers.QtWidgetRenderer)
    qtbot.addWidget(form.renderer.qt_object)
    assert isinstance(form.quantity.renderer, renderers.QtWidgetRenderer)
    assert isinstance(form.total.renderer, renderers.QtWidgetRenderer)
    quantity = form.quantity.renderer.qt_object
    total = form.total.renderer.qt_object
    assert isinstance(quantity, widgets.QSpinBox)
    assert isinstance(total, widgets.QLabel)
    assert total.text() == "6"
    quantity.selectAll()
    qtbot.keyClicks(quantity, "4")
    qtbot.keyClick(quantity, core.Qt.Key.Key_Return)
    assert total.text() == "12"
    form.price.value = 5
    assert total.text() == "20"
    # Watching assignments must not depend on the input renderer's refresh suppression.
    with form.price.renderer.stop_refresh():
        form.price.value = 6
    assert total.text() == "24"


def test_batches_deduplicate_updates_and_ignore_equal_scalar_assignments() -> None:
    form = _Order()
    form.activate_reactions()
    form.quantity.value = 2
    assert form.runs == [(2, 3)]
    with batch_updates():
        form.quantity.value = 7
        with batch_updates():
            form.price.value = 8
        assert form.total.text == "6"
    assert form.total.text == "56"
    assert form.runs == [(2, 3), (7, 8)]


@define_view
class _Branch(MainView):
    first: IntInputView = child(IntInputView, value=1)
    second: IntInputView = child(IntInputView, value=2)
    output: LabelView = child(LabelView)
    use_first: bool = True

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.runs = 0
        self.activate_reactions()

    @reactive
    def show(self) -> None:
        self.runs += 1
        value = self.first.value if self.use_first else self.second.value
        self.output.text = str(value)


def test_dependencies_follow_branches_and_replaced_child_views() -> None:
    form = _Branch()
    form.second.value = 8
    assert (form.output.text, form.runs) == ("1", 1)
    form.use_first = False
    form.first.value = 9
    assert (form.output.text, form.runs) == ("8", 2)
    old = form.second
    # Even an equal replacement must move the subscription to the new instance.
    form.second = IntInputView(value=8)
    old.value = 10
    assert (form.output.text, form.runs) == ("8", 3)
    form.second.value = 11
    assert (form.output.text, form.runs) == ("11", 4)


def test_stop_and_reactivate_reactions() -> None:
    form = _Order()
    form.stop_reactions()
    form.quantity.value = 9
    assert form.total.text == "6"
    form.activate_reactions()
    assert form.total.text == "27"


@define_view
class _Collection(MainView):
    items: list[int] = attrs.field(factory=lambda: [1])
    output: LabelView = child(LabelView)

    @reactive
    def show(self) -> None:
        self.output.text = str(sum(self.items))


def test_collections_require_reassignment_instead_of_in_place_mutation() -> None:
    view = _Collection()
    view.activate_reactions()
    view.items.append(2)
    assert view.output.text == "1"
    view.items = list(view.items)
    assert view.output.text == "3"


@define_view
class _Chained(_Order):
    @reactive
    def derive_price(self) -> None:
        self.price.value = (self.quantity.value or 0) * 2


def test_chained_reactions_settle_without_relying_on_method_order() -> None:
    view = _Chained()
    assert view.total.text == "8"
    view.quantity.value = 3
    assert view.total.text == "18"


def test_dependencies_do_not_keep_a_discarded_owner_alive() -> None:
    form = _Order()
    quantity = form.quantity
    reference = weakref.ref(form)
    del form
    gc.collect()
    assert reference() is None
    quantity.value = 9


@pytest.mark.parametrize("stop_first", [False, True])
def test_queued_reactions_do_not_run_after_their_owner_stops_or_disappears(
    *, stop_first: bool
) -> None:
    form = _Order()
    quantity, output = form.quantity, form.total
    with batch_updates():
        quantity.value = 9
        if stop_first:
            form.stop_reactions()
        del form
        gc.collect()
    assert output.text == "6"


def test_loading_and_resetting_recompute_after_all_fields_are_restored(tmp_path: Path) -> None:
    form = _Order()
    form.quantity.value = 7
    form.price.value = 8
    path = tmp_path / "order.order"
    form.save_state(path)
    restored = _Order()
    restored.load_state(path)
    assert restored.runs == [(2, 3), (7, 8)]
    assert restored.total.text == "56"
    # Derived values from a file do not override the rule, even with unchanged inputs.
    state = restored.state_data()
    state["total"]["text"] = "stale"
    restored.load_state_data(state)
    assert restored.total.text == "56"
    restored.reset_state()
    assert restored.total.text == "6"


@define_view
class _Broken(MainView):
    divisor: int = 0
    result: float = 0

    @reactive
    def divide(self) -> None:
        self.result = 1 / self.divisor


def test_errors_surface_and_tracking_recovers_without_rollback() -> None:
    view = _Broken()
    with pytest.raises(ZeroDivisionError):
        view.activate_reactions()
    view.divisor = 2
    assert view.result == 0.5
    with pytest.raises(ZeroDivisionError):
        view.divisor = 0
    assert view.divisor == 0
    view.divisor = 4
    assert view.result == 0.25

    def failed_batch() -> None:
        with batch_updates():
            view.divisor = 5
            msg = "failed batch"
            raise ValueError(msg)

    with pytest.raises(ValueError, match="failed batch"):
        failed_batch()
    assert view.result == 0.25
    view.divisor = 10
    assert view.result == 0.1


@define_view
class _Cycle(MainView):
    value: int = 0

    @reactive
    def increment(self) -> None:
        self.value += 1


def test_cycles_fail_instead_of_hanging_and_do_not_poison_other_views() -> None:
    view = _Cycle()
    with pytest.raises(ReactiveCycleError, match="increment"):
        view.activate_reactions()
    view.stop_reactions()
    assert _Order().total.text == "6"


@define_view
class _Override(_Order):
    def show_total(self) -> None:
        self.total.text = "manual"


@define_view
class _Inherited(_Order):
    pass


def test_inheritance_preserves_reactions_and_ordinary_overrides_disable_them() -> None:
    inherited = _Inherited()
    inherited.quantity.value = 4
    assert inherited.total.text == "12"
    overridden = _Override()
    overridden.quantity.value = 4
    assert overridden.runs == []


def test_async_methods_are_rejected() -> None:
    async def invalid(_view: MainView) -> None:
        pass

    with pytest.raises(TypeError, match="synchronous"):
        reactive(invalid)  # type: ignore[arg-type]


@define_view
class _Converted(MainView):
    value: int = attrs.field(
        default=1,
        converter=int,
        validator=attrs.validators.ge(0),
        on_setattr=attrs.setters.pipe(attrs.setters.convert, attrs.setters.validate),
    )
    output: LabelView = child(LabelView)

    @reactive
    def show(self) -> None:
        self.output.text = str(self.value)


def test_reactions_read_converted_values_after_assignment_and_respect_validation() -> None:
    view = _Converted()
    view.activate_reactions()
    view.value = "4"  # type: ignore[assignment]
    assert view.output.text == "4"
    with pytest.raises(ValueError, match=">= 0"):
        view.value = -1
    assert view.output.text == "4"


def test_task_state_tracks_progress_result_failure_and_drop_on_the_dispatch_thread() -> None:
    def work(job: Job[int, int], *, fail: bool) -> int:
        job.report_progress(2)
        if fail:
            msg = "unavailable"
            raise ValueError(msg)
        return 42

    view = _Order()
    task = view.jobs.task(work)
    states: list[tuple[bool, object, object, object, bool]] = []
    threads: list[int] = []

    @reactive
    def show(_view: MainView) -> None:
        states.append((task.is_running, task.progress, task.result, task.error, task.has_result))
        threads.append(threading.get_ident())

    class TaskView(MainView):
        show_state = show

    observer = TaskView()
    observer.activate_reactions()
    task.start(fail=False)
    view.jobs.wait()
    assert states[:3] == [
        (False, None, None, None, False),
        (True, None, None, None, False),
        (True, 2, None, None, False),
    ]
    assert states[-1] == (False, 2, 42, None, True)
    task.start(fail=True)
    view.jobs.wait()
    assert isinstance(states[-1][3], ValueError)
    assert states[-1][:3] == (False, 2, None)
    view.jobs.drop()
    assert states[-1] == (False, None, None, None, False)
    assert set(threads) == {threading.get_ident()}
