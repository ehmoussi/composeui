# Reactive methods

A reactive method is a view method that ComposeUI runs again each time a view field that it
read changes. Use it to show a value that comes from other fields, such as a total, a filtered
chart, or a summary. It replaces the callbacks that you would connect to each signal of those
fields.

Decorate the method with `reactive`, from `composeui.core.reactivity`. The method takes only
`self`. Its body reads fields and sets fields, as other code does:

```python
from composeui.core.application import Application
from composeui.core.reactivity import reactive
from composeui.core.view import CheckBoxView, LabelView, MainView, SliderView, child, define_view


@define_view
class OrderView(MainView):
    quantity: SliderView = child(SliderView, value=2, maximum=10)
    gift_wrap: CheckBoxView = child(CheckBoxView, text="Gift wrap")
    total: LabelView = child(LabelView)

    @reactive
    def show_total(self) -> None:
        price = self.quantity.value * 15
        if self.gift_wrap.is_checked:
            price += 5
        self.total.text = f"Total: {price} EUR"


app = Application(build_main_view=OrderView)
main_view = app.main_view
assert main_view.total.text == "Total: 30 EUR"
main_view.quantity.value = 3
assert main_view.total.text == "Total: 45 EUR"
main_view.gift_wrap.is_checked = True
assert main_view.total.text == "Total: 50 EUR"
```

`show_total` reads `quantity.value` and `gift_wrap.is_checked`: these fields are its inputs.
It sets `total.text`, which is not an input. A change of the slider or of the check box, by the
user or by code, runs it again.

## When a method runs

- **At start-up.** The application runs each reactive method once, after it has built the
  main view, and after `setup_model` when the app has a model. This first run records the
  inputs of the method.
- **After a change of an input.** A method runs again when a view field that it read in its
  last run changes. Each run records its inputs again. So a field that the method read only
  in a branch that it did not take is not an input. In the example, if `show_total` read a
  field only when `gift_wrap` is checked, a change of that field would not run it while the
  box is clear.
- **Reads count everywhere in the run.** A read in a helper function, or in a method of
  another view, is an input too, if it happens while the method runs.
- **Only view fields and tasks are inputs.** A plain attribute, which is not a field, is not
  an input. Neither is the data of a model, nor a global variable. When such data changes,
  connect its signal, such as a table's `changed`, to set a field or to start a task. The state
  of a task is an input (see [Slow work in a task](#slow-work-in-a-task)).
- **Once per event.** One event that changes several inputs runs each method once, after the
  event. These are events:
  - the callbacks of one signal emission, such as a button's `clicked`;
  - a change that the user makes in a widget;
  - a web request that the browser sends for an action of the user;
  - New and Open, which set the fields of the study;
  - the start-up run of the methods.
- **A change outside an event.** Code that sets a field outside a signal's callback, such as
  a test, makes its own event. The methods run before the assignment returns. So two
  assignments in a row run a method twice.
- **In a fixed order.** When several methods wait to run, they run in the order in which they
  started. The main view's methods come first. Then come the methods of its child views, level
  by level, in the order of the fields. In one view, a base class's methods come before its
  subclass's, and the methods of a class run in the order that the class defines them. A view
  that starts later comes after the views that started before it.
- **Again in the same event.** When a method sets a field that another method reads, that
  other method waits to run again. It runs again in the same event, in the same order. If it is
  already waiting, it runs once.
- **A view set later.** A view that code sets into a field of a started view starts its
  methods, as does a new item of a [list of views](organizing-the-window.md#a-list-of-views).
  A view that leaves its field, or a removed item, stops its methods.
- **A subclass can turn it off.** A method of a subclass that has the name of a reactive method
  of its base class, without `@reactive`, replaces it: it does not run by itself.

## What counts as a change

- **Setting a field.** Only setting a field is a change. A method that sets a field does not
  read it: `self.total.text = ...` does not make `total.text` an input.
- **Equal values.** Setting a field to an equal value of the same type changes nothing, for a
  `str`, `int`, `float`, `bool`, `bytes`, an enum, a date, a time, or a path. `4` and `4.0`
  have different types, so setting one in place of the other is a change.
- **Other values.** Setting any other value, such as a list, a dict, or a dataframe, is a
  change, even when the new value is equal to the old one.
- **Lists.** Set a new list to change a view's list. A change in place raises `TypeError`
  (see [Views are reactive](core-concepts.md#views-are-reactive)).
- **A child view replaced.** Setting a new view into a field, such as `view.panel = Panel()`,
  is a change for the methods that read through it, such as `self.panel.title.text`. They run
  again, and read the fields of the new view.

## What a method must not do

- **Set a field that it reads.** The method would run again each time. ComposeUI refuses it
  with `ReactiveLoopError`, even when the value does not change. The field keeps its old
  value. The error comes out of the code that started the event, such as the assignment, the
  signal's `emit`, or the start-up of the application, once the other methods of the event
  have run.
- **Change each other without end.** When methods keep changing each other's inputs, a method
  that has run 100 times in one event, and must run again, raises `ReactiveLoopError`.
- **Be a coroutine.** An `async def` method raises `TypeError` when its class is defined. Give
  slow work to a [task](#slow-work-in-a-task).
- **Change a list in place.** It raises `TypeError`, as in any other code.

To correct a field from the field itself, such as a maximum that must not be under a minimum,
write a signal's callback instead. ComposeUI does not record what a callback reads:

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
app.main_view.low.value = 60  # as the user moves the slider, a renderer sets the value,
app.main_view.low.value_changed.emit(60)  # then emits the signal
assert app.main_view.high.value == 60
```

## Slow work in a task

A reactive method runs on the main thread, so it must be quick. Give a slow query to a
[task](threads.md#reusable-loading-tasks), and start it from the method with
[`start_latest`](threads.md#run-the-latest-call-only). A second method shows the result:

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
    count: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.counter = self.jobs.task(count_pickups)

    @reactive
    def count_at_hour(self) -> None:
        self.counter.start_latest(self.hour.value)

    @reactive
    def show_count(self) -> None:
        self.count.text = f"{self.counter.result or 0} pickups"


app = Application(build_main_view=PickupsView)
main_view = app.main_view
main_view.hour.value = 12
main_view.hour.value = 13  # The run for 13 replaces the run for 12.
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert main_view.count.text == "1300 pickups"
```

- **The task's state is an input.** A method that reads `is_running`, `is_canceled`,
  `progress`, `result`, `error`, or `has_result` runs again at each `changed` of the task: a
  start, a progress report, an outcome, and a reset by New, Open, or `jobs.drop()`.
- **Starting reads no state.** `start`, `start_latest`, and `cancel` do not read the task's
  state. So a method can start a task from its inputs, as `count_at_hour` does.
- **Read or start, not both.** A method that reads the state of a task, and then starts or
  cancels that task, would run again each time. It raises `ReactiveLoopError`. Read the state
  in one method, and start the task in another.
- **The latest result wins.** `start_latest` replaces a run that is still going on. A result
  that is out of date never replaces the latest one.

## Errors in a method

When a method raises an exception, the other methods of the event still run. Then the first
exception comes out of the code that started the event, as `ReactiveLoopError` does. The log
gets the others, as "The reactive method ... failed too". The fields that the methods set
before the exception keep their new values.

## Debug a method's inputs

`reactive_inputs(view)` gives the inputs that each reactive method of `view` read in its last
run, by method name. A field shows as its path from `view`, and a task as the name of its
function:

```python
from composeui.core.reactivity import reactive_inputs

print(reactive_inputs(main_view))
# {'show_total': ['quantity.value', 'gift_wrap.is_checked']}
```

A child view that a method reads on its way to a field, such as `quantity`, does not show: the
field does.

## On each backend

- **The same on each backend.** Reactive methods are part of `composeui.core`. They run on
  the main thread, on Qt, Textual, and the web.
- **One set per web session.** On the web, each session has its own main view, so it runs its
  own methods. They start after `setup_session` and `setup_model`. The response to an action
  of the user carries every change that the methods made. When the session ends, its methods
  stop.
- **Studies.** A study saves the fields, not the methods. After New or Open, each method that
  read a field of the study runs once.
- **In a test.** `Application` starts the methods, as the backends do (see
  [Test the views](testing.md#test-the-views)). A main view built without an application,
  such as `OrderView()`, runs none of them until `start_reactions(main_view)` starts them.
- **The cost.** An app without a reactive method runs as before. Once one class with a
  reactive method exists, ComposeUI records the reads during the runs of the methods only. A
  write of a view field, in any view, then takes about twice as long. A page takes up to about
  20% longer to build, and the web renders it up to about 10% slower.

The [Uber pickups example](../../src/examples/uberpickups.py) shows its chart and its map with
reactive methods, and queries the pickups of the slider's hour with `start_latest`. Its
[dataframe version](../../src/examples/uberpickupsframe.py) builds its table, its chart and its
map from the result of its loading task, with no state in its model.
