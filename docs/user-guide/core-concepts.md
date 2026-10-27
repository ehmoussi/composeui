# Core concepts

A ComposeUI app is made of views, signals, an optional model, and studies, which a backend
shows:

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
