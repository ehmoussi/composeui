# API reference

This reference is built from the docstrings of the code. `composeui.core` holds the views,
the signals, and the application. It imports no backend. The backend modules hold the
application classes that `composeui.core.application.run` starts.
The [architecture](../technical-guide.md#architecture) explains how the parts fit together.

```{toctree}
:caption: composeui.core

view
signal
application
model
sqlitemodel
dataframesource
study
jobs
reload
translation
renderer
registry
chartimage
```

```{toctree}
:caption: Backends

backends
```
