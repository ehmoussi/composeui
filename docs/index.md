# ComposeUI

ComposeUI is a small MVVM layer for building UIs in Python. Views are typed `attrs`
classes. A renderer binds each view to a widget of a backend: Qt, Textual, or the web.
Signals carry the events between the views, the model, and the app.

- The [user guide](user-guide.md) explains how to build an app: the views and widgets,
  and what each backend shows.
- The [examples guide](examples-guide.md) says what each example app shows, and how to run
  it.
- The [widget catalog](widgets.md) lists every view that a backend renders.
- The [API reference](api/index.md) documents each module of `composeui.core`, and the
  application classes of the backends.
- The [technical guide](technical-guide.md) explains how ComposeUI works inside: its
  [architecture](technical-guide.md#architecture), and how to add a widget or a backend.

```{toctree}
:hidden:

user-guide
examples-guide
widgets
api/index
technical-guide
```
