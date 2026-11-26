# Core concepts

A ComposeUI app is made of views, signals, an optional model, and studies. A backend shows
the views:

| Concept | Role |
| --- | --- |
| View (`composeui.core.view`) | A typed `attrs` class that holds the state of a part of the UI, such as `InputView`, `FormView`, or `TableView`. You compose views by nesting view fields in other views. See [Building views](building-views.md). |
| Main view | The root view, a subclass of `MainView`: the window, with its menus, its status bar, its notification, and its content. See [The main view](building-views.md#the-main-view). |
| Signal (`composeui.core.signal`) | An event of a view or a model, such as `clicked`. `signal.connect(callback)` calls the callback on each event, and gives it the `view`, `main_view`, or `model` that it asks for. |
| Reactive method (`composeui.core.reactivity`) | A view method decorated with `@reactive`. ComposeUI runs it again each time a view field that it read changes. See [Reactive methods](reactive-methods.md). |
| Model (`composeui.core.model`) | The app's data beside the views. It is optional. `DatabaseModel` keeps the data in a [SQLite database](sqlite-model.md). |
| Study | The file that the File menu saves and opens: the state of the views, and the data of the model, if it has data to save. For a `DatabaseModel`, this data is its `per_session` database. A [shared database](sqlite-model.md#a-database-shared-by-every-session) is not in the study. The `extension` of the main view names its file type. See [Saving and loading state](building-views.md#saving-and-loading-state). |
| Backend | The toolkit that shows the views: Qt, Textual, or the web. `run(MainViewClass)` starts the app on the backend that `--backend` names. See [Backends](running-the-app.md#backends). |
| Jobs (`composeui.core.jobs`) | `main_view.jobs`: functions that [run in worker threads](threads.md). They report their results through signals. |
| Task | `main_view.jobs.task(work)`, or `view.build_task(work)` in another view: a job that a view runs again and again, with its state (`is_running`, `progress`, `result`), and its `changed`, `finished`, and `failed` signals. See [Reusable loading tasks](threads.md#reusable-loading-tasks). |

A backend binds each view that it shows to a widget with a renderer. The renderer keeps the
two in sync in both directions, so the app's code never calls it. The
[technical guide](../technical-guide/architecture.md#views-and-renderers) explains renderers.

A backend leaves out, with no error, a view that it has no renderer for. For example, Textual
shows no `MapView`. See
[Adapt the views to the backend](running-the-app.md#adapt-the-views-to-the-backend).

## How ComposeUI maps to MVVM

ComposeUI follows the Model-View-ViewModel pattern, but its names are not the usual ones:

| MVVM | ComposeUI |
| --- | --- |
| Model | The model, a `Model` or a `DatabaseModel`. It knows no view. It reports its changes with signals. |
| ViewModel | The views of `composeui.core.view`. They hold the state of the UI as typed fields, and their signals and callbacks act on the model. |
| View | The widget of the backend: a Qt widget, a Textual widget, or an HTML element. Your code does not touch it. |
| Binding | The renderer. It pushes each change of a view to its widget, and copies the widget's state back. |

Each view has one widget, and views nest as their widgets do. So the views are the
widget tree of the UI, without the toolkit. One app runs on each backend without a change.

## Views are reactive

When code sets an attribute of a view (`view.text = "..."`), the view pushes the change to
its renderer. You do not call `update()` or `refresh()` for normal state changes. To set a field
from other fields each time they change, write a [reactive method](reactive-methods.md).

Only setting an attribute is a change. To change a list that a view holds, such as a map's
`points` or a table's `rows`, set a new list:

```python
view.points = [*view.points, point]
view.points += [point]  # the same: it sets a new list
```

A change in place, such as `view.points.append(point)`, would reach no renderer, so it
raises a `TypeError` that names the attribute. The lists inside the list, such as each row
of `rows`, are the same. A copy, such as `list(view.points)`, is a plain list that you can
change.

A dict that a view holds, such as a table's `filters`, is the same. Set a new dict:

```python
view.filters = {**view.filters, 0: "Ada"}
view.filters |= {0: "Ada"}  # the same: it sets a new dict
```

A change in place, such as `view.filters[0] = "Ada"`, would also skip the checks of the
attribute, so it raises a `TypeError` too. The lists and dicts inside a dict or a list are the
same. A copy, such as `dict(view.filters)`, is a plain dict that you can change. A subclass of
`dict`, such as a `defaultdict`, keeps its own behavior, so the view does not watch it: set a
new one to change it.

This applies to any field of a view, also one that no renderer shows, such as
`ActionView.data`. To change data in place, keep it out of the view's fields, for example in
the model.

## Signals inject arguments

`Signal.connect` and `Application.connect` read the callback's parameter names. When a
callback asks for `view`, `main_view`, or `model`, it gets them:

```python
# `main_view` is injected automatically because it's a requested parameter.
def _on_name_changed(self, text: str, *, main_view: MainView) -> None:
    main_view.status_bar.show_message(f"Hello, {text}!" if text else "")
```

With `signal.connect`, `view` is the view that owns the signal. It is available before an
app is built:

```python
from composeui.core.view import ButtonView

button = ButtonView(text="Click")

def on_click(*, view: ButtonView) -> None:
    view.text = "Clicked"

button.clicked.connect(on_click)
button.clicked.emit()
assert button.text == "Clicked"
```

`Application.connect(view=..., signals=...)` supplies the explicit `view` instead. It need
not own those signals. The callback also gets the app's own `main_view`, and a
`ModelApplication`'s own `model`, even from a signal of another app or a standalone signal.
A standalone signal, such as a model's signal, has no owning view. If a callback asks for
`view`, `main_view`, or `model` when none is available, it uses its parameter's default.
Without a default, the call raises `ValueError`. On the web, `app.connect` refuses a view or
a signal outside the app's main view (see
[How the web differs from a window](running-the-app.md#how-the-web-differs-from-a-window)).
A signal keeps its callbacks, and a callback keeps alive what it refers to. For example,
`model.changed.connect(view.show)` keeps `view` in memory until the signal is disconnected.
A signal belongs to one view: giving it to another view, as in `b.clicked = a.clicked`,
raises `ValueError`.

A callback can take fewer of the signal's arguments than the signal emits. It then gets the
first ones, or none. `connect(callback, now=True)` also calls the callback once, right away,
without the signal's arguments. Use it for a callback that reads the current state, such as
one that shows a model's rows. A callback that takes the signal's arguments needs defaults
for them.
