# Core concepts

| Concept | Role |
| --- | --- |
| View (`composeui.core.view`) | A typed `attrs` class that holds the state of a part of the UI, such as `InputView`, `FormView`, or `TableView`. You compose views by nesting view fields in other views. See [Building views](building-views.md). |
| Main view | The root view, a subclass of `MainView`: the window, with its menus, its status bar, and its content. See [The main view](building-views.md#the-main-view). |
| Signal (`composeui.core.signal`) | An event of a view or a model, such as `clicked`. `signal.connect(callback)` calls the callback on each event, and gives it the `view`, `main_view`, or `model` that it asks for. |
| Model (`composeui.core.model`) | The app's data beside the views. It is optional. `SqliteModel` keeps the data in a [SQLite database](sqlite-model.md). |
| Study | The file that the File menu saves and opens: the state of the views, and the data of the model. The `extension` of the main view names its file type. See [Saving and loading state](building-views.md#saving-and-loading-state). |
| Backend | The toolkit that shows the views: Qt, Textual, or the web. `run(MainViewClass)` starts the app on the backend that `--backend` names. See [Backends](running-the-app.md#backends). |
| Jobs (`composeui.core.jobs`) | `main_view.jobs`: functions that [run in threads](threads.md). Their results are emitted on the main thread. |

A backend binds each view to a widget with a renderer. The renderer keeps the two in sync in
both directions, so the app's code never calls it. The
[technical guide](../technical-guide.md#views-and-renderers) explains renderers.

## How ComposeUI maps to MVVM

ComposeUI follows the Model-View-ViewModel pattern, but its names are not the usual ones:

| MVVM | ComposeUI |
| --- | --- |
| Model | The model, a `Model` or a `SqliteModel`. It knows no view. It tells of its changes with signals. |
| ViewModel | The views of `composeui.core.view`. They hold the state of the UI as typed fields, and their signals and callbacks act on the model. |
| View | The widget of the backend: a Qt widget, a Textual widget, or an HTML element. Your code does not touch it. |
| Binding | The renderer. It pushes each change of a view to its widget, and copies the widget's state back. |

Each view has one widget, and views nest as their widgets do. So the views are the
widget tree of the UI, without the toolkit. One app runs on each backend without a change.

## Views are reactive

When code sets an attribute of a view (`view.text = "..."`), the view pushes the change to
its renderer. You do not call `update()` or `refresh()` for normal state changes.

## Signals inject arguments

`Signal.connect` and `Application.connect` read the callback's parameter names. When a
callback asks for `view`, `main_view`, or `model`, it gets them:

```python
# `main_view` is injected automatically because it's a requested parameter.
def _on_name_changed(self, text: str, *, main_view: MainView) -> None:
    main_view.status_bar.show_message(f"Hello, {text}!" if text else "")
```

A callback can take fewer of the signal's arguments than the signal emits. It then gets the
first ones, or none. `connect(callback, now=True)` also calls the callback once, right away.

## Computed fields

Use `@reactive` to keep derived UI fields consistent with the state they read.
ComposeUI records dependencies while the method runs. Assigning a dependency reruns
the method, without a signal connection or an explicit dependency list:

```python
from composeui.core.reactivity import reactive
from composeui.core.view import IntInputView, LabelView, MainView, child, define_view


@define_view
class OrderView(MainView):
    app_title = "Order"
    extension = ".order"
    quantity: IntInputView = child(IntInputView, value=2)
    price: IntInputView = child(IntInputView, value=3)
    total: LabelView = child(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.activate_reactions()

    @reactive
    def show_total(self) -> None:
        self.total.text = str((self.quantity.value or 0) * (self.price.value or 0))


view = OrderView()
assert view.total.text == "6"
view.quantity.value = 4
assert view.total.text == "12"
```

- **Activation.** Call `activate_reactions()` once all the method's inputs exist. Use
  the end of `__attrs_post_init__` for local state, or the end of model setup for a
  late-created task. Activation runs each method once; repeated activation does nothing.
  Each view activates its own methods, not its children's methods.
- **Observable reads.** Fields of views, task properties (`is_running`, `progress`,
  `result`, `error`, and `has_result`), and `jobs.is_running` are observable. Reads inside
  synchronous helpers count too. Task dependencies currently use the task's complete
  state notification, so any task transition can rerun the method.
- **Branches.** Dependencies are collected again on each run. A short-circuited
  expression only subscribes to the values it reads. Replacing a child view moves the
  subscription to its new fields, even if its values match the old child.
- **Normal Python.** Methods take only `self` and return `None`; no arguments are
  injected. Assignments retain autocomplete and static type checking. Async methods are
  not supported. Inherited reactions stay active unless a subclass overrides them.
- **Timing.** Outside a batch, reactions settle before the triggering assignment returns.
  Changes made by a reaction can schedule other reactions. Declaration order is not an
  execution-order contract; intermediate derived values can exist while updates settle.
  Use one method for outputs that must be computed together.
- **Collections and external state.** In-place list or dictionary mutations, ordinary
  object attributes, and SQL queries are not observable. Assign a replacement collection,
  or keep an explicit signal callback for external state. A child added later must
  activate its own methods after initialization.
- **Lifetime and state.** The view owns its reactions. Dependencies do not keep it alive.
  Call `stop_reactions()` to disconnect this view's methods, and `activate_reactions()`
  to restart them. Reactions are not serialized. Loading or resetting view state batches
  changes and recomputes active reactions after all fields have been restored. Derived
  values in a saved file do not override their rules.
- **Errors.** Errors propagate, including during activation. Reads made before an error
  stay subscribed, so correcting an input can rerun the method. There is no rollback.
  A reaction that runs more than 100 times in one update raises `ReactiveCycleError`.
- **Threads.** Reactions run on the thread that changes their dependencies. They do not
  add thread safety. From a worker, use job progress or `Job.call_on_main_thread`, not
  direct view assignments. On the web, existing session locking still owns dispatch.

For several assignments, use a batch to avoid recomputing after each one:

```python
from composeui.core.reactivity import batch_updates

with batch_updates():
    view.quantity.value = 4
    view.price.value = 5

assert view.total.text == "20"
```

Nested batches flush only when the outermost batch completes. Inside a batch, derived
fields can hold their previous values. If a batch fails, assignments remain, but pending
reactions are discarded; a later dependency change can trigger them again.

Keep actions such as starting jobs, writing files, and opening dialogs in explicit event
callbacks. A reaction can run many times, so use it to describe what the UI should show,
not to perform an operation once. [Pipe form](../../src/examples/pipeform.py) uses reactions
for conditional fields; [Pipe sweep](../../src/examples/pipesweep.py) uses one for control
enablement. [Uber pickups](../../src/examples/uberpickups.py) separates reactive visibility
and progress text from its outcome callback.
