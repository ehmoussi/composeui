---
name: composeui
description: "Use when writing or changing an app built with ComposeUI, the Python MVVM layer whose views are typed attrs classes that a Qt, Textual or web renderer shows: when the code imports composeui, defines a MainView, a FormView or another view with @define_view, connects a Signal, or starts an app with run(). Holds the rules that keep such an app correct on every backend, a minimal app, and where the documentation is."
metadata:
  composeui-version: "0.2"
---

# ComposeUI

ComposeUI is a small MVVM layer. The app is a tree of views under a `MainView`. A view is a
typed `attrs` class that holds the state of a part of the UI. A renderer of the chosen
backend (Qt, Textual, or the web) binds each view to a widget. Signals carry events between
the views, the model, and the app. The API is early-stage and still moving: when the
documentation and this skill disagree, trust the documentation.

Full documentation: https://ehmoussi.github.io/composeui/ (an index for models is at
https://ehmoussi.github.io/composeui/llms.txt).

This file is a copy, for ComposeUI 0.2. The current skill is at
https://ehmoussi.github.io/composeui/skills/composeui/SKILL.md, published with the
documentation of the `main` branch. `python -c "import composeui; print(composeui.__version__)"`
gives the installed version. When it is newer than 0.2 (its first two numbers), or a name of
this file is not in the installed `composeui`, the copy is older than the code: read the
current skill, and tell the user to download it again.

## A minimal app

```python
from attrs import Factory

from composeui.core.application import run
from composeui.core.view import InputView, MainView, define_view


@define_view
class GreetingInputView(InputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.placeholder = "Type your name..."
        self.text_edited.connect(self._on_name_changed)

    def _on_name_changed(self, text: str, *, main_view: MainView) -> None:
        main_view.status_bar.show_message(f"Hello, {text}!" if text else "")


@define_view
class HelloMainView(MainView):
    app_title = "Hello ComposeUI"
    extension = ".hello"

    greeting: GreetingInputView = Factory(GreetingInputView)


if __name__ == "__main__":
    run(HelloMainView)
```

Run it with `--backend qt` (extra `pyside6`), `--backend textual` (extra `tui`), or without
the option for the web (extra `web`, the default).

## Rules

- **Import views, signals and `run` from `composeui.core`.** Never import `PySide6`,
  Textual, or Starlette in the app's views: the same views must run on every backend.
  Use `qtpy` if the app needs Qt itself. To adapt a view to the backend, ask
  `renders(MapView)`, or `current_backend()`, from `composeui.core.application` as the
  views are built.
- **Decorate every view class with `@define_view`,** and give it typed fields. Fields are
  keyword-only. A class variable such as `app_title`, `extension`, `align`, or `width`
  configures the class and is not state.
- **A child view is a field that builds it:** `Factory(MyView)`, or
  `child(MyView, label="Name")` to set fields. Never share one instance between views.
- **Wire a view in `__attrs_post_init__`.** Call `super().__attrs_post_init__()` first,
  then set values and connect signals.
- **Views are reactive.** Set an attribute (`view.text = "..."`) and the renderer shows it.
  Never call `update()` or `refresh()`, and never touch a widget: the app's code does not
  see the toolkit.
- **A signal callback asks for `view`, `main_view`, or `model` by parameter name,** and
  `connect` injects them. Spell the names exactly. A callback may take fewer of the
  signal's arguments than it emits.
- **Check a form with a validator:** `self.set_validator(self._check, self.text_edited)`
  where `_check` returns an error message or `None`. Then call `form.check()` and read
  `form.is_valid`.
- **Pick a file on the server with `server_roots`** when the app needs the file where it is,
  not a copy: on the web, a file path field otherwise uploads a copy. The web lists only
  the files in those folders, and `path` is `None` for a path typed outside them: read
  `path`, not `text`. A table's path cell takes them too:
  `CellWidget.file_path(extensions, server_roots=(...))`; the web refuses a path typed
  outside them. A `FolderPathInputView` takes a folder, and a `SavePathInputView` a file to
  save, the same way; on the web, without `server_roots`, their path is typed. Give only folders that every user of the app may see.
  See https://ehmoussi.github.io/composeui/user-guide/widgets.html#files-on-the-server
- **Keep the state saveable.** `MainView.save_state` writes the views' fields with
  `cattrs`, which handles `datetime.date` and `datetime.datetime` as ISO 8601 text. A new
  field must be serializable, or carry the `OMIT` metadata. Text that the code sets, not
  the user, carries `UI_TEXT`. A new or removed field needs no new version. To rename or
  move a field, raise the main view's `state_version`, and upgrade an older study in
  `migrate_state`. Older versions of the app then refuse the new studies. A load sets the
  fields without emitting their signals: connect `MainView.loaded`, emitted as the app
  starts and after New and Open, to give again what a study doesn't hold, such as a large
  table's source.
  See https://ehmoussi.github.io/composeui/user-guide/building-views.html#saving-and-loading-state
- **Run slow work in jobs** (`main_view.jobs.start(work, *args)`), not in a callback: a
  callback blocks the UI. The function of a job never touches a view. Connect `finished`,
  `failed`, and `progress` (`job.report_progress(value)`), which emit on the main thread.
  Raise `RefusedError` for an expected refusal only. For a worker that a view runs again
  and again, create `self.jobs.task(work)` once in `__attrs_post_init__`, not as a field.
  Let the task set its controls' state: `task.disables(*views)` and
  `task.cancel_with(stop)`, rather than enabling them in each callback.
  See https://ehmoussi.github.io/composeui/user-guide/threads.html
- **Keep the model out of the views.** The optional model (`Model`, `SqliteModel`) holds
  the data and knows no view. The app gives it to `run` with `build_model=` and
  `setup_model=`. Batch inserts and CSV imports (`insert_batches`, `CSVSqliteTable`,
  `fill`, `fill_from_file`, `fill_from_url`) commit once their generator is read to the
  end. Pass only trusted URLs.
  See https://ehmoussi.github.io/composeui/user-guide/sqlite-model.html and
  https://ehmoussi.github.io/composeui/user-guide/csv-import.html
- **Show many rows in a `SourceTableView`,** on a `ListSource`, a `SqliteSource`
  (`table.source()` for a CSV table), or a `DataFrameSource` (the `dataframe` extra). Assign
  a source's new `frame` on the main thread.
  See https://ehmoussi.github.io/composeui/user-guide/tables.html#a-large-table
- **Build a bar chart's series with `Series.bars(name, values)`.** With the `dataframe`
  extra, `series_of` and `points_of` from `composeui.core.dataframesource` read a chart's
  series or a map's points from a frame.
  See https://ehmoussi.github.io/composeui/user-guide/charts.html
- **Use `MapView` for geographic points**, not `ChartView`: `MapPoint(latitude=...,
  longitude=...)`. `center=None` and `zoom=None` fit the points. The study saves the
  viewport, not the points: build them again from the model after a load. Textual shows no
  map. Follow OpenStreetMap's tile policy.
  See https://ehmoussi.github.io/composeui/user-guide/maps.html
- **Mark user-visible text for translation** with `T("...")` or `self.tr("...")`
  (`T` is in `composeui.core.view`).
  See https://ehmoussi.github.io/composeui/user-guide/translation.html
- **Type a form dialog:** subclass `TypedFormDialogView[YourForm]` with
  `form: YourForm = attrs.Factory(YourForm)`. See
  https://ehmoussi.github.io/composeui/user-guide/organizing-the-window.html#form-dialogs
- **Use a content dialog for a dialog that isn't a form**, such as a table to pick from:
  subclass `ContentDialogView[YourView]` with `content: YourView = attrs.Factory(YourView)`.
  The app sets `is_accept_enabled`. To keep the dialog open on OK, override `accept()` and
  call `super().accept()` only to close it. See
  https://ehmoussi.github.io/composeui/user-guide/organizing-the-window.html#content-dialogs
- **Support Python 3.9 in view fields.** Write `Optional[int]` and `Union[int, str]`, not
  `int | None`, because `attrs` and `cattrs` evaluate the annotations at runtime. Start
  every module with `from __future__ import annotations`, and do not quote annotations.
  Define the views at module level.
- **Test the views without a backend.** Build the app with `Application(build_main_view=...)`
  (or `ModelApplication`) from `composeui.core.application`, not the main view alone, so
  that callbacks get `main_view` and `model`. Set a field, emit its signal, and check the
  fields; call `main_view.jobs.wait()` for the jobs' results.
  See https://ehmoussi.github.io/composeui/user-guide/testing.html
- **Run a code example before you answer with it.** The API moves: check each name against
  `composeui.core.view` or the widget catalog before you use it.

## Where to look

- Which view to use: the widget catalog, https://ehmoussi.github.io/composeui/widgets.html
- Core concepts, views, layout, forms: the user guide,
  https://ehmoussi.github.io/composeui/user-guide.html
- Complete apps to copy from: the examples guide,
  https://ehmoussi.github.io/composeui/examples-guide.html
- Exact signatures: the API reference, https://ehmoussi.github.io/composeui/api/index.html
