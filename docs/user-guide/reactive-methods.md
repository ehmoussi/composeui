# Reactive methods

Use `@reactive` to keep a view field in sync with its inputs. For example, show an order
total that follows the quantity. Use a signal callback for a one-off action, such as placing
the order.

**After the first run, ComposeUI reruns the method when an input from its last run
changes.** Each run records the inputs again.

Import `reactive` from `composeui.core.reactivity`. The method takes only `self`.

In this example, the total starts with the cost of the items. It adds a delivery charge
only when the **Include delivery** box is checked. Use `Application` without a toolkit
to try the example by setting fields in Python:

```python
from attrs import field

from composeui.core.application import Application
from composeui.core.reactivity import reactive
from composeui.core.view import (
    OMIT,
    CheckBoxView,
    LabelView,
    MainView,
    SliderView,
    child,
    define_view,
)


@define_view
class OrderView(MainView):
    quantity: SliderView = child(SliderView, value=2, maximum=10)
    include_delivery: CheckBoxView = child(CheckBoxView, text="Include delivery")
    delivery_prices: dict[str, int] = field(factory=lambda: {"standard": 5})
    total: LabelView = field(factory=LabelView, metadata={OMIT: True})

    @reactive
    def show_total(self) -> None:
        price = self.quantity.value * 15
        if self.include_delivery.is_checked:
            price += self.delivery_prices["standard"]
        self.total.text = f"Total: {price} EUR"


app = Application(build_main_view=OrderView)
main_view = app.main_view
assert main_view.total.text == "Total: 30 EUR"
main_view.quantity.value = 3
assert main_view.total.text == "Total: 45 EUR"
main_view.include_delivery.is_checked = True
assert main_view.total.text == "Total: 50 EUR"
```

`show_total` always reads `quantity.value` and `include_delivery.is_checked`. If the box is
unchecked, the method skips `delivery_prices` because it does not need the charge. It writes
`total.text` without reading it, so `total.text` is an output, not an input. `OMIT` keeps the
label out of the [study state](building-views.md#saving-and-loading-state).

## Why didn't my method run?

Ask two questions: **Did the last run read the field? Did you change the field itself?**
Try these changes separately in the order example:

| Change | Does `show_total` run again? |
| --- | --- |
| A different `main_view.quantity.value` | Yes. The method always reads it. |
| `main_view.delivery_prices = {"standard": 7}` while **Include delivery** is unchecked | No. The last run did not read `delivery_prices`. |
| `main_view.delivery_prices = {"standard": 7}` while **Include delivery** is checked | Yes. The last run read the field, and the assignment replaces the dictionary. |
| `main_view.delivery_prices["standard"] = 7` while **Include delivery** is checked | No. This changes a dictionary entry, not the field. |

Only public view fields and [task state](#slow-work-in-a-task) can be inputs. Signals and
`renderer` do not count. A helper or property can read a field on behalf of the method.
Private fields, plain attributes, model data, and global variables are not inputs. To react
to a model change, connect a callback to the model's signal. In the callback, set a view
field or start a task.

If the method has not run yet, ComposeUI has no inputs to track. `Application` starts it for
you. If you build a view on its own, call `start_reactions(view)` from
`composeui.core.reactivity`. See [Test the views](testing.md#test-the-views).

If the method has run, see [Debug a method's inputs](#debug-a-methods-inputs) to check
what ComposeUI tracks and what causes a run.

## What counts as a change

- **Setting a field.** A field can change when you assign to it. Changing an object that
  it holds in place does not count.
- **Equal values.** Setting a field to an equal value of the same type changes nothing, for a
  `str`, `int`, `float`, `bool`, `bytes`, an enum, a date, a time, or a path. `4` and `4.0`
  have different types, so setting one in place of the other is a change.
- **Other values.** For a list, a dict, a dataframe, or any other object, setting a different
  object is a change, even if it is equal to the old one. Setting the same object is not a change.
- **Lists and dicts.** Set a new list or dict to change a view's list or dict. A change in
  place raises `TypeError` (see [Views are reactive](core-concepts.md#views-are-reactive)).
  The view keeps its own copy of the list or dict that you set. So setting the same list or
  dict object again is a change.
- **A child view replaced.** Setting a new view into a field, such as `view.panel = Panel()`,
  is a change for the methods that read through it, such as `self.panel.title.text`. They run
  again, and read the fields of the new view.

## When a method runs

- **At start-up.** The application starts the methods after it builds the main view and,
  if there is a model, after `setup_model`. The first run records the inputs.
- **After a batch of changes.** A batch groups updates such as the callbacks of one
  `Signal.emit` or the changes in one web request for a user action. If several inputs change
  before a method runs, it runs once for those changes. One user action can include more than
  one batch. For example, a Qt slider can run a method after the value changes, then run it
  again if a `value_changed` callback changes another input.
- **After an assignment on its own.** If no batch is active, the methods run before the
  assignment returns. Two separate assignments can run the same method twice.
- **In start order.** When several methods wait to run, ComposeUI picks the one it started
  first. At start-up, it starts the main view's methods, then those of its child views, level
  by level in field order. It uses definition order within a class, with base classes first.
- **Again in the same batch.** A method can set a field that another method reads. If the
  other method is still waiting, it does not need an extra run. If it ran already, ComposeUI
  schedules it again.
- **On New and Open.** ComposeUI batches the assignments that reset or load study fields.
  An existing method does not run again unless an input changes. See
  [Saving and loading state](building-views.md#saving-and-loading-state).
- **When views enter or leave.** Assigning a child view to a started view starts the child's
  methods. The same rule applies to items in a
  [list of views](organizing-the-window.md#a-list-of-views). Removing a child or item stops
  its methods.
- **When a subclass overrides a method.** An override without `@reactive` does not run
  automatically.

## What a method must not do

- **Correct its own input.** If a method tries to set a field it already read in that run,
  ComposeUI raises `ReactiveLoopError`. It rejects the assignment even if the value is
  unchanged.
- **Keep changing another method's inputs in a cycle.** If a method needs to run more than
  100 times in one batch, ComposeUI stops the batch and raises `ReactiveLoopError`. Methods
  still waiting in that batch do not run.
- **Be a coroutine.** An `async def` method raises `TypeError` when its class is defined. Give
  slow work to a [task](#slow-work-in-a-task).

Use a signal callback to correct an input. Here, if the user moves `low` above `high`,
the callback raises `high.value` to match `low.value`. The callback can read and write
`high.value`. In a test, set `low.value` and emit `value_changed` separately: setting the
slider value in code does not emit its signal.

```python
from composeui.core.application import Application
from composeui.core.view import MainView, SliderView, child, define_view


@define_view
class RangeView(MainView):
    low: SliderView = child(SliderView, value=10, maximum=100)
    high: SliderView = child(SliderView, value=50, maximum=100)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.low.value_changed.connect(self.keep_order)

    def keep_order(self, low: int) -> None:
        if self.high.value < low:
            self.high.value = low


app = Application(build_main_view=RangeView)
app.main_view.low.value = 60
app.main_view.low.value_changed.emit(60)
assert app.main_view.high.value == 60
```

## Errors in a method

If a method raises an exception, ComposeUI continues with the other waiting methods.
At the end of the batch, it raises the first exception and logs any others. The code
that started the batch receives the exception, for example a field assignment or a
call to `Signal.emit`. Changes the methods made before the exception stay in place.

The [cycle limit](#what-a-method-must-not-do) is different. When ComposeUI reaches it,
it stops the batch without running the remaining methods.

## Slow work in a task

Keep reactive methods quick. ComposeUI does not switch threads when a field assignment
triggers a method. To update a view from a job, return a result or use
[`job.call_on_main_thread`](threads.md#how-jobs-behave). Do not set view fields directly
from the job's function.

Use a [task](threads.md#reusable-loading-tasks) to run a slow query in the background.
In this example, a slider selects the hour for a count of taxi pickups. Use two reactive methods:

1. `load_count` reads the slider and passes the hour to
   [`start_latest`](threads.md#run-the-latest-call-only). The task runs `count_pickups` in
   the background. That function gets the hour as an argument; it does not read the view.
2. `show_count` reads the task's state and updates the label. It does not start the task.

```python
from composeui.core.application import Application
from composeui.core.jobs import Job
from composeui.core.reactivity import reactive
from composeui.core.view import LabelView, MainView, SliderView, child, define_view


def count_pickups(_job: Job[int], hour: int) -> int:
    return hour * 100  # Query the pickups of the hour here.


@define_view
class PickupsView(MainView):
    hour: SliderView = child(SliderView, value=11, maximum=23)
    count: LabelView = child(LabelView, text="No count yet")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.counter = self.jobs.task(count_pickups)

    @reactive
    def load_count(self) -> None:
        self.counter.start_latest(self.hour.value)

    @reactive
    def show_count(self) -> None:
        if self.counter.is_running:
            self.count.text = "Loading…"
        elif self.counter.error is not None:
            self.count.text = "Could not load pickups"
        elif self.counter.has_result:
            self.count.text = f"{self.counter.result} pickups"
        else:
            self.count.text = "No count yet"


app = Application(build_main_view=PickupsView)
main_view = app.main_view
main_view.hour.value = 12
main_view.hour.value = 13
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert main_view.count.text == "1300 pickups"
```

When the slider changes, `load_count` requests a new count. Starting the task changes its
state, so `show_count` runs and shows “Loading…”. When the count arrives, `show_count` runs
again. `load_count` does not: it watches the slider, not the task. If the count for hour 12
is still pending when you select hour 13, `start_latest` replaces that run and ignores its
result.

- **A method watches the whole task.** Reading any of `is_running`, `is_canceled`,
  `progress`, `result`, `error`, or `has_result` makes the task an input. The method can
  rerun on a start, a progress report, a cancellation, an outcome, or a reset by New, Open,
  or `jobs.drop()`. Even a method that reads only `result` can rerun when progress changes.
- **Keep the two methods separate.** `start`, `start_latest`, and `cancel` do not make the
  task an input. But do not read a task's state and then start or cancel it in the same
  method. For example, reading `is_running` and then calling `start_latest` on the same
  task raises `ReactiveLoopError`: the start would change the state the method just read.
- **Check what each method watches.** In this example,
  [`reactive_inputs(main_view)`](#debug-a-methods-inputs) lists `hour.value` for `load_count`
  and `counter` for `show_count`.
- **A reset does not restart the task.** New and Open clear the task's result. If the hour
  does not change, `load_count` does not run just because the task was reset. If you need a
  query for every study, start it from a
  [`loaded` callback](building-views.md#saving-and-loading-state).

## Debug a method's inputs

Use `reactive_inputs(view)` to check which inputs a method read on its last run. It groups the
inputs by method name. It shows a field or task as a path from `view` when possible. If it
cannot find a path to a task, it shows the name of the task's function.

After running the order example with **Include delivery** checked:

```python
from composeui.core.reactivity import reactive_inputs

print(reactive_inputs(main_view))
# {'show_total': ['quantity.value', 'include_delivery.is_checked', 'delivery_prices']}
```

`reactive_inputs` omits fields that it recorded as holding a child view, such as `quantity`.
Replacing the child can still trigger a run. If the method read `quantity.value`, that
field appears in the list.

Run an app with `--log-reactivity` to see which changes caused each run. For example,
changing the order quantity gives a trace like this:

```text
Change quantity.value (watched by 1 reaction)
Run OrderView.show_total [reaction 0]: 0.420 ms; causes: quantity.value
```

The log shows changes only for inputs that have watchers. It lists input names, not
values. The watcher count tells how many methods or helpers watch the input when it
changes. It is not a run count.

If several inputs cause one run, the log lists them together. If the method runs again,
the log lists only the new causes. The time measures the method itself, not the wait
before it starts or the work a task does in the background. The log marks a run that
raises an exception as `failed`.

Qt and Textual start their methods before the app reads the flag, so it does not trace
their first runs. On the web, it also traces the first runs of each session.

## Helpers that follow their inputs

Two helpers use the same scheduling rules as reactive methods:

- **Show views from a check box.** [`CheckBoxMixin.shows`](building-views.md#forms-and-their-fields)
  shows views only while the check box is checked. `reactive_inputs` lists `shows` on the
  check box.
- **Show a task's state.** [`Task.show_state`](threads.md#show-a-tasks-state) shows the
  state of a task in a status line. `reactive_inputs` lists `show_state` on the status line.

Calling a helper schedules its first run. After that, it runs again when an input changes.
If the view's methods stop, the helper also stops. Starting the view's methods again does not
restart the helper.

Reactive methods can read fields that a helper sets, such as `is_visible`. When a callback
of `Signal.emit` sets `is_checked`, `shows` runs after the callbacks finish, not during the
callback that assigns the field.

## On each backend

Qt, Textual, and the web use the same rules to track inputs. On the web, the app's template
main view does not run reactive methods. Each session starts the methods of its own main
view after `setup_session` and, if there is a model, after `setup_model`. The methods stop
when the session ends.

In the [Uber pickups example](../../src/examples/uberpickups.py), a slider selects an hour.
Reactive methods filter the table, mark the selected hour on the chart, and start a query
with `start_latest` for the map. The chart keeps the counts for all hours. The
[dataframe version](../../src/examples/uberpickupsframe.py) builds the table, chart, and map
from its task's result, without storing it in the model.
