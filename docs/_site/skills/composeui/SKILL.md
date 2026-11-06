---
name: composeui
description: "Use when writing or changing an app built with ComposeUI, the Python MVVM layer whose views are typed attrs classes that a Qt, Textual or web renderer shows: when the code imports composeui, defines a MainView, a FormView or another view with @define_view, connects a Signal, or starts an app with run(); also when choosing widgets for a screen, or judging whether ComposeUI supports a feature. Holds the rules that keep such an app correct on every backend, a minimal app, and where the documentation is."
metadata:
  composeui-version: "0.3"
---

# ComposeUI

ComposeUI is a small MVVM layer. The app is a tree of views under a `MainView`. A view is a
typed `attrs` class that holds the state of a part of the UI. A renderer of the chosen
backend (Qt, Textual, or the web) binds each view to a widget. Signals carry events between
the views, the model, and the app. The API is early-stage and still moving: when the
documentation and this skill disagree, trust the documentation.

Full documentation: https://ehmoussi.github.io/composeui/ (an index for models is at
https://ehmoussi.github.io/composeui/llms.txt).

This file is a copy, for ComposeUI 0.3. The current skill is at
https://ehmoussi.github.io/composeui/skills/composeui/SKILL.md, published with the
documentation of the `main` branch. `python -c "import composeui; print(composeui.__version__)"`
gives the installed version. When it is newer than 0.3 (its first two numbers), or a name of
this file is not in the installed `composeui`, the copy is older than the code: read the
current skill, and tell the user to download it again.

To upgrade an app to a newer ComposeUI, read the changelog,
https://github.com/ehmoussi/composeui/blob/main/CHANGELOG.md. Read the section of each
release after the app's version, and change the app for each name that was renamed or removed.
Before 1.0, a minor version can break the API.

When the app needs a name that no release has yet, depend on a commit of `main`:
`"composeui[web] @ git+https://github.com/ehmoussi/composeui@<commit>"` in
`[project] dependencies`, which both pip and uv install. `uv add` with a git URL writes
`[tool.uv.sources]` instead, which pip ignores. Check that the name is in that commit, and
install the app with pip and with uv, not only in the current environment.

An installed commit has a version with `.dev`, such as `0.3.1.dev4+g1a2b3c4`. Its first two
numbers can be those of this copy, but the commit can have names that this copy does not
know. Then read the skill of that commit, at
https://raw.githubusercontent.com/ehmoussi/composeui/<commit>/docs/_site/skills/composeui/SKILL.md,
and download it again each time that the app moves to a new commit.

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

Run it with `composeui run app.py`, which reloads on a change, or with `python app.py`. The web
(extra `web`) is the default. After the file, add `--backend qt` (extra `pyside6`) or
`--backend textual` (extra `tui`).

With `composeui run`, a file that defines one `MainView` class needs no `run` call. A file with a
model calls `run(HelloMainView, build_model=...)`.

## Find what ComposeUI already has

Look before you design a screen, and before you tell the user that ComposeUI lacks a
feature. An app often builds by hand what a view already does, such as a navigation that
`Router` and `PageView` give.

1. **Know the version.** Check the installed version, or the commit that the app pins (see
   above). Answer for that version.
2. **Search the public names.** The public API is the `__all__` of each `composeui.core`
   module: `python -c "import composeui.core.view as m; print(m.__all__)"`. Read the
   docstring and the signature of a candidate with `help(...)`. A name outside `__all__`
   can change in any release.
3. **Read the documentation of the need.** The widget catalog lists each view and its
   backends, the user guide has a section per feature, and the examples guide has complete
   apps. The site documents `main`: for an older release, trust the installed docstrings.
4. **Try a minimal example** of the candidate on the backends that the app uses, before you
   build around it or write a workaround. Run each code example before you answer with it.

When you assess a need, say which case it is:

- **Supported directly:** a view, a field, or a signal does it.
- **Supported by composition:** existing views do it together, such as a `ListView` whose
  rows are each a `HorizontalView` of labels and buttons.
- **Needs a new widget:** a new view and a renderer on each backend, which is a change to
  ComposeUI (https://ehmoussi.github.io/composeui/technical-guide.html#add-a-widget). Do not
  draw it with a toolkit in the app: the app then runs on one backend only.
- **Not in the checked version:** a newer release or `main` can have it. Read the changelog.

Name the version or the commit that you checked, and say what you searched: "not found" is
not "not available". Do not choose widgets from memory or from an older answer: read the
catalog and the `__all__` of the version that you checked.

## Structure the app

- **Split the app into components,** views that each do one part of the work. A component
  connects the signals of its views and sets their validators in its
  `__attrs_post_init__`.
- **A component tells the app with a `Signal` field of its own**
  (`searched: Signal[str] = Factory(Signal[str])`, from `composeui.core.signal`), and the
  main view connects it to another component. The main view keeps the work of the whole
  app (`loaded`, menus, toolbars, dialogs), not the callback of each button. When a
  callback of the main view only calls a method of a component, move the connection into
  the component.
- **Never keep a parent or another component in a view field.** The app reads each view
  field as a child view, so a view that holds its parent makes the app loop forever as it
  starts. A callback asks for `main_view` instead.
- **Keep no state in a module or class variable.** On the web, each session builds its own
  main view, but all the users share a module or class variable.
- **Define each view at module level,** not in a function: `attrs` and `cattrs` read the
  types of its fields from the module. Keep the model and the jobs' functions in modules
  that import no view. Call `run` in the program's module, under
  `if __name__ == "__main__":`.
- **Split by the work, not by the number of lines.** Before you simplify an app, read which
  view connects each callback, and which code works around an older ComposeUI.

See https://ehmoussi.github.io/composeui/user-guide/building-views.html#structure-an-app

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
- **Set a new list to change a view's list:** `view.points = [*view.points, point]`, or
  `view.points += [point]`. `append`, `pop`, `x[i] = ...` and the like raise `TypeError` on
  a view's list, its inner lists too.
- **Derive a field from other fields with `@reactive`** (`composeui.core.reactivity`), not
  with a callback on each of their signals. The method takes only `self`. The app runs it at
  start-up, then again once per event (a signal's callbacks, a user's edit, a web request,
  New or Open) in which a view field or a task's state that it read in its last run changed.
  Methods run in a fixed order: down the view tree, then in the order the class defines
  them. Never set a field that the method reads, even to the same value: that raises
  `ReactiveLoopError`, so correct a field from itself in a signal's callback. A model's data
  and plain attributes are not inputs. A main view built without `Application` runs no
  method until `start_reactions(main_view)`. `reactive_inputs(view)` shows what each read.
  See https://ehmoussi.github.io/composeui/user-guide/reactive-methods.html
- **A signal callback asks for `view`, `main_view`, or `model` by parameter name,** and
  `connect` injects them. Spell the names exactly. A callback may take fewer of the
  signal's arguments than it emits.
- **Check a form with a validator:** `self.set_validator(self._check, self.text_edited)`
  where `_check` returns an error message or `None`. Then call `form.check()` and read
  `form.is_valid`.
- **Take a user's file with `FileUploadView`**, not a file path field, on a public app: it has no
  text field, so the user cannot type a path of the server. Connect `uploaded`, which gives an
  `UploadedFile`, and read its `path`. On the web, that copy stays for a job that reads it, until
  the session's end at the latest; `MainView.max_upload_size` sets the largest file.
- **Pick a file on the server with `server_roots`** when the app needs the file where it is,
  not a copy: on the web, a file path field otherwise uploads a copy. The web lists only
  the files in those folders, and `path` is `None` for a path typed outside them: read
  `path`, not `text`. A table's path cell takes them too:
  `CellWidget.file_path(extensions, server_roots=(...))`; the web refuses a path typed
  outside them. A `FolderPathInputView` takes a folder, and a `SavePathInputView` a file to
  save, the same way; on the web, without `server_roots`, their path is typed. Give only folders that every user of the app may see.
  See https://ehmoussi.github.io/composeui/user-guide/widgets.html#files-on-the-server
- **Read a relative path from the study's folder with `base_folder`**, not the process's
  working folder: `path` reads the text from it, and a path picked inside it stays relative.
  See https://ehmoussi.github.io/composeui/user-guide/widgets.html#relative-paths
- **Pick a path by the row's kind with `CellWidget.path_by(kind_column, editors)`**, when
  one column holds files to read, folders and files to write: `editors` maps the kind
  column's text to `CellWidget.file_path`, `folder_path` or `save_path`, and the cell's
  widget follows the kind the user picks. Read a cell's path with
  `table.cell_widget(row, column).path(text)`.
  See https://ehmoussi.github.io/composeui/user-guide/tables.html#paths-by-the-rows-kind
- **Import a Parquet file with `fill_from_frame(table, frame)`**, from
  `composeui.core.dataframesource`: the app reads the file with its own dataframe library.
- **Write a file the user names with `main_view.write_file(field, write)`**: a path typed
  in a save path field is never asked about by its picker. `write_file` asks before
  replacing a file that exists, once per file, then calls `write(path)`. Bind the data when
  the user saves: `functools.partial(write, data=...)`.
  See https://ehmoussi.github.io/composeui/user-guide/organizing-the-window.html#replacing-a-file
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
  `task.cancel_with(stop)`, rather than enabling them in each callback. For an input that
  changes quickly, such as a slider, call `task.start_latest(*args)`: it replaces the run
  going on, and a replaced run's result never shows. A reactive method can call it, but
  must not read the state of the task that it starts.
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
- **Give a dialog buttons of its own**, such as Apply, as `DialogButtonView` fields of a
  form or content dialog: a click leaves the dialog open unless `closes=True`, and waits for
  the checks unless `checks=False`. Check any view the dialog shows with
  `dialog.add_check(validator, *signals)`, where the validator returns a message or `None`.
  Save from `accepting` (OK, the dialog still open) or from a button's `clicked`, inside
  `with dialog.refusing("...{error}"):`, so that a model's refusal shows in the dialog and
  keeps it open. Tell the user of a success while the dialog is open with
  `dialog.show_message(...)`, not the status bar, which the dialog hides. See
  https://ehmoussi.github.io/composeui/user-guide/organizing-the-window.html#buttons-and-checks-of-a-dialog
- **Support Python 3.9 in view fields.** Write `Optional[int]` and `Union[int, str]`, not
  `int | None`, because `attrs` and `cattrs` evaluate the annotations at runtime. Start
  every module with `from __future__ import annotations`, and do not quote annotations.
- **Test the views without a backend.** Build the app with `Application(build_main_view=...)`
  (or `ModelApplication`) from `composeui.core.application`, not the main view alone, so
  that callbacks get `main_view` and `model`. Set a field, emit its signal, and check the
  fields; call `main_view.jobs.wait()` for the jobs' results. Test a component in a main
  view that holds only it, then the whole app. Build two apps and check that they share no
  state.
  See https://ehmoussi.github.io/composeui/user-guide/testing.html

## Where to look

- Which view to use: the widget catalog, https://ehmoussi.github.io/composeui/widgets.html
- Core concepts, views, layout, forms: the user guide,
  https://ehmoussi.github.io/composeui/user-guide.html
- Complete apps to copy from: the examples guide,
  https://ehmoussi.github.io/composeui/examples-guide.html
- Public names: the `__all__` of each `composeui.core` module (see
  "Find what ComposeUI already has")
- Exact signatures: the API reference, https://ehmoussi.github.io/composeui/api/index.html
- What changed in each release: the changelog,
  https://github.com/ehmoussi/composeui/blob/main/CHANGELOG.md
