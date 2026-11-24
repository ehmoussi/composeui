# Building views

This page covers how to define views, lay them out, check forms, structure an app, and save
its state. The first example is a small form, with its layout and its checks:

```python
import enum
from typing import Optional

from attrs import Factory

from composeui.core.application import run
from composeui.core.view import (
    Align,
    ButtonView,
    FormView,
    HorizontalView,
    LabelRowCheckBoxView,
    LabelRowComboBoxView,
    LabelRowFloatInputView,
    LabelRowInputView,
    MainView,
    child,
    define_view,
)


class Material(enum.Enum):
    STEEL = "Steel"
    COPPER = "Copper"


@define_view
class NameRow(LabelRowInputView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.set_validator(self._check_name, self.text_edited)
        self.run_validator()  # shows the error before the first edit

    def _check_name(self) -> Optional[str]:
        return "A name is required" if self.text == "" else None


@define_view
class PipeForm(FormView):
    name: NameRow = child(NameRow, label="Name")
    radius: LabelRowFloatInputView = child(LabelRowFloatInputView, label="Radius", minimum=0)
    material: LabelRowComboBoxView[Material] = child(
        LabelRowComboBoxView,
        label="Material",
        values={material.value: material for material in Material},
        value=Material.STEEL,
    )
    insulated: LabelRowCheckBoxView = child(LabelRowCheckBoxView, label="Insulated")


@define_view
class FormButtons(HorizontalView):
    align = Align.END

    validate: ButtonView = child(ButtonView, text="Validate")


@define_view
class PipeMainView(MainView):
    app_title = "Pipes"
    extension = ".pipe"

    form: PipeForm = Factory(PipeForm)
    buttons: FormButtons = Factory(FormButtons)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.buttons.validate.clicked.connect(self._validate)

    def _validate(self) -> None:
        self.form.check()
        if self.form.is_valid:
            self.status_bar.show_message(f"{self.form.name.text} is valid")


if __name__ == "__main__":
    run(PipeMainView)
```

## Define a view

- **`@define_view` makes an `attrs` class of a view.** A field set with a view is a child
  view. A field set with a plain value, such as `text` or `value`, is state that the
  renderer shows. The fields are keyword-only.
- **A class variable configures the class,** such as `app_title`, `extension`, or `align`.
  It is not a field, so the state does not save it.
- **`__attrs_post_init__` wires the view once it is built.** Call
  `super().__attrs_post_init__()` first, then set values and connect signals.
- **`T("...")` and `self.tr("...")` mark a text for translation.** Later examples of this
  guide write their text so, for example `Column("radius", T("Radius"))`. Import `T` from
  `composeui.core.view`. Until the app has catalogs, the text shows as written. See
  [Translating the app](translation.md).

## `child` or `Factory`

Each view needs its own child views, so a view field takes a function that builds them:

- `Factory(PipeForm)` builds the view with its defaults.
- `child(LabelRowInputView, label="Name")` builds it with these fields. Each view gets
  its own copy of the arguments, so a list among them is never shared.

Use `child` to set a few fields where the view is declared. Use a subclass with an
`__attrs_post_init__`, as `NameRow` does, when the view also needs code: signals, checks,
or text built from other fields.

## Lay out views

- **A main view, a page, and a form put their view fields one above the other,** in the
  order of the fields.
- **A `HorizontalView` puts its view fields side by side.** Each field takes a share of the
  width, from its `STRETCH` metadata:
  `attrs.field(factory=TableView, metadata={STRETCH: 3})`. A button keeps the width of its
  text (`default_stretch = 0`). When no view takes a share, `align` packs them at the
  start or the end of the row, and the views that don't fit the row go on the next line,
  for example a row of buttons on a phone. When a view takes a share, a row narrower than
  42rem stacks its views on the web.
- **A `VerticalView` puts its view fields one above the other,** for a column in a
  `HorizontalView`, for example a table above its buttons.
- **A `GridView` puts each view field in a cell.** `grid_cell` gives the cell, the view,
  and the view's fields, as `child` does: `grid_cell((1, 0), ButtonView, text="Add")`. To
  span cells, give a `GridPosition`:
  `grid_cell(GridPosition(1, 0, column_span=2), TableView, headers=["Name"])`. A field that
  needs other metadata sets its cell itself: `metadata={GRID_POSITION: (1, 0)}`.

For panes that the user resizes, see [Resizable panes](organizing-the-window.md#resizable-panes).

### Frame a layout

Set `frame=Frame(title=...)` on a `VerticalView`, `HorizontalView`, or `GridView` to draw a
border around its content. Use `Frame()` for a border without a title, or leave out `frame`
for no border.

```python
from composeui.core.view import T, Frame, LabelView, MainView, VerticalView, child, define_view


@define_view
class ResultsView(VerticalView):
    summary: LabelView = child(LabelView, text=T("No results yet"))


@define_view
class ReportView(MainView):
    results: ResultsView = child(ResultsView, frame=Frame(title=T("Results")))
```

Set the frame when you build the layout. A study does not save or restore it. A title marked
with `T(...)` follows the app's language.

Qt uses a `QGroupBox`. Textual draws a border with the title on its top edge. The web uses a
`<fieldset>` with a `<legend>` for the title. On the web, grids and rows with stretch stack
when the width inside the frame is less than 42rem. To change the web border,
select `[data-cui-frame]` in a [web stylesheet](running-the-app.md#change-the-look-of-the-web-app).

## Forms and their fields

A `FormView` shows its rows one above the other, with their labels aligned. A
`GroupFormView` is a form in a box with a `title`. It can be a row of another form, as the
main pipe and the incident pipe are in `pipeform.py`.

Each field has three views:

| View | Shows | Example |
| --- | --- | --- |
| `InputView` | Only the field, anywhere | A search field in a toolbar |
| `RowInputView` | A row of a form, without a label | A field under a heading |
| `LabelRowInputView` | A row of a form, with a `label` and an optional `help` | Most form fields |

The fields:

| Field | Its value | What the user does |
| --- | --- | --- |
| `InputView` | `text` | Types a line of text |
| `TextAreaView` | `text`, with its lines (see [Text area](widgets.md#text-area)) | Types several lines of text |
| `FloatInputView` | `value`, a `float` or `None`, from `minimum` to `maximum`, with `decimals` | Types a decimal number |
| `IntInputView` | `value`, an `int` or `None` (see [Integer input](widgets.md#integer-input)) | Types a whole number |
| `ParsedInputView` | `value`, read from `text` by the app's `parse` (see [Text read by the app](widgets.md#text-read-by-the-app)) | Types a value in the app's format, such as "4 GB" |
| `DateInputView` | `value`, a `datetime.date` or `None` (see [Date input](widgets.md#date-input)) | Types or picks a date |
| `DateRangeInputView` | `value`, a pair of dates, either `None` (see [Date range](widgets.md#date-range)) | Types or picks the first and the last day |
| `FilePathInputView` | `text`, and `path` (see [File path input](widgets.md#file-path-input)) | Types or picks a file |
| `FolderPathInputView` | `text`, and `path` (see [Folder path input](widgets.md#folder-path-input)) | Types or picks a folder |
| `SavePathInputView` | `text`, and `path` (see [Save path input](widgets.md#save-path-input)) | Types or picks a file to save |
| `CheckBoxView` | `is_checked`, with its `text` beside the box | Checks or unchecks the box (`toggled`) |
| `RadioGroupView` | `value`, one of `values` | Picks one of a few choices |
| `ComboBoxView` | `value`, one of `values` | Picks one choice in a drop-down list |
| `CheckListView` | `selected`, some of `values` (see [Choices of several values](widgets.md#choices-of-several-values)) | Checks several choices in a list |
| `MultiComboBoxView` | `selected`, some of `values` | Checks several choices in a drop-down list |
| `SliderView` | `value`, from `minimum` to `maximum` by `step` (see [Slider](widgets.md#slider)) | Drags a handle |
| `FloatSliderView` | `value`, a decimal number from `minimum` to `maximum` by `step` (see [Decimal slider](widgets.md#decimal-slider)) | Drags a handle |
| `RangeSliderView` | `value`, a pair of ends from `minimum` to `maximum` by `step` (see [Range slider](widgets.md#range-slider)) | Drags two handles |
| `FloatRangeSliderView` | `value`, a pair of decimal ends | Drags two handles |
| `FileUploadView` | `files`, which the study does not save (see [File upload](widgets.md#file-upload)) | Gives the app a file (`uploaded`) |

Each field has its row views too, for example `RowFloatInputView` and
`LabelRowFloatInputView`, or `LabelRowDateInputView` for a date. The
[widget catalog](../widgets.md#form-rows) lists every row view.

A row shows in any view, such as a `SidebarView` or a `VerticalView`, as a form shows it:
its label, its field, and its message. A `FormView` adds what concerns its rows together:
on Qt, it lines up their labels, and its [checks](#check-a-form) compare their values.

A form shows its other views too, such as a table or a `HorizontalView` of buttons. Each one
shows in its place between the rows, as wide as the form. The checks of the form run on its
rows only.

- **The text fields** emit `text_edited` on each change that the user types, and
  `editing_finished` when the user is done with the field, for example on Enter, or as a
  text area loses the focus. `text_changed` also reports a path or a date that the user
  picks. Text or a value that code sets emits neither signal. On the web, `text_edited`
  waits until the user stops typing for 300 ms, or leaves the field. A callback can then get
  `"abc"` only, not `"a"` and `"ab"` before it.
- **A date range** has no text signals. `value_changed` gives the pair of dates, the start
  and the end, either one `None`.
- **A file upload** gives each file as an `UploadedFile`: its `name`, its `size`, and the
  `path` to read it from. The study does not save the file.
- **A check box** shows other views only while it is checked, with `shows`:
  `self.show_raw_data.shows(self.table)`. It sets their `is_visible` at once, and again
  each time the box changes: as the user clicks it, as code sets `is_checked`, and as a
  study opens or New starts one. It follows the box as a
  [reactive method](reactive-methods.md#helpers-that-follow-their-inputs) does: in a
  signal's callbacks, the views change once the callbacks are done.
- **A choice** maps each label to its value: `values = {"Steel": Material.STEEL}`. `value`
  is `None` or one of `values`. `value_changed` reports the user's choice. A `None` value
  selects nothing, unless `None` is one of `values`: then it selects that choice, such as
  the "All" of a filter, `{"All regions": None, "North": "north"}`.
- **A [`LabelView`](widgets.md#label)** shows read-only text, for example a result.
- **The [status bar](#the-status-bar)** of the main view shows a short message, for
  example the result of a form. A [notification](#notifications) shows an error above the
  page until the user closes it.

## Check a form

A check is a function without arguments. It returns an error message, or `None` when the
value is good:

- **A row's own check.** `row.set_validator(check, *signals)` runs `check` each time one of
  the signals emits, and shows its message under the row's field. It does not run at once:
  call `run_validator()` to show the error before the first edit.
- **A check of several rows.** `form.add_validator(check, *signals, rows=(...))` checks the
  values of several rows together. The form shows the messages of the failing checks at its
  end, and marks the fields of `rows` as invalid.
- **Before an action.** `form.check()` runs every check of the form and its nested forms
  now. Then `form.is_valid` tells whether they all pass.
- **Bounds are not checks.** The `minimum` and `maximum` of a `FloatInputView` do not make
  a check: `form.check()` does not refuse a value out of them, such as a radius of `-1`.
  Each backend treats such text differently while the user types:
  - Qt refuses some of it, such as a minus sign when `minimum` is 0, but not a number
    over `maximum`.
  - Textual shows the field as invalid, without a message.
  - The web takes it as typed.

  To refuse the value on every backend, add a check with `set_validator`, as `NameRow`
  does.

In a [form dialog](organizing-the-window.md#form-dialogs), OK stays disabled while a check fails.
[`src/examples/pipeform.py`](../../src/examples/pipeform.py) checks its name field, and has two
checks of several rows.

## Compose views from mixins

You can compose a view by mixing traits. For example, `LabelRowFloatInputView` combines
`FormLabelRowView` and `FloatInputMixin`. The mixins of `composeui.core.view` are the available
building blocks: `InputMixin`, `FloatInputMixin`, `IntInputMixin`, `ParsedInputMixin`,
`DateInputMixin`, `DateRangeInputMixin`, `FilePathInputMixin`, `SliderMixin`, `FloatSliderMixin`,
`RangeSliderMixin`, `FloatRangeSliderMixin`, `CheckBoxMixin`, `ValuesGroupMixin`,
`MultiValuesMixin`, `TableMixin`, `LogMixin`, `LabelMixin`, and `MarkdownMixin`.

Larger views have sections of their own:

- `PageView` and `Router` for an app split into [pages](organizing-the-window.md#pages).
- `TabView` for [tabs](organizing-the-window.md#tabs).
- `SplitterView` for [resizable panes](organizing-the-window.md#resizable-panes).
- `ToolBar` for a [toolbar](organizing-the-window.md#toolbars).
- `DialogView` for [dialogs](organizing-the-window.md#dialogs).
- `SidebarView` for a [sidebar](organizing-the-window.md#sidebar).
- `ListView` for [a list of views](organizing-the-window.md#a-list-of-views), and `Menu` for
  [menus](organizing-the-window.md#menus).
- `TableView`, `RecordTableView`, and `SourceTableView` for [tables](tables.md).
- `ChartView` for [charts](charts.md), and `MapView` for [maps](maps.md).
- `DrawingView` for a [diagram of shapes](widgets.md#drawing).

## The main view

A subclass of `MainView` is the app. Its class variables configure it:

- **`app_title`** is the name of the app, in the title of the window.
- **`extension`** is the file type of its studies, for example `".pipe"`.
- **`has_file_menu = False`** leaves out the File menu, for an app without studies (see
  [The File menu and picking a file](widgets.md#the-file-menu-and-picking-a-file)).
- **`app_icon`** is the icon of the app (see [The app's icon](#the-apps-icon)).
- **`width`** sets the default width of the web content, also in an app without pages
  (see [Page width](organizing-the-window.md#page-width)). Qt and Textual ignore it.
- **`translations_dir`** is the folder of its catalogs (see
  [Translating the app](translation.md)).

Its view fields are the content of the window, one above the other. Its `status_bar` shows
short messages, its `notification` an error until the user closes it, and its `jobs`
[run work in threads](threads.md).

A dashboard's main view, `DashboardView`, is wide and has no File menu: see
[Dashboards from a dataframe](dashboards.md#a-dashboards-main-view).

### The status bar

The `status_bar` of the main view, a `StatusBar`, is a line at the bottom of the window. It shows
a short message to the user, for example "Saved":

```python
main_view.status_bar.show_message("Saved")
```

- **The message goes after `timeout` seconds,** 3 by default. With a `timeout` of 0, it
  stays until the next message, or until `clear_message()`.
- **A new message replaces the previous one,** and its timeout starts again.
- **`message`** holds the message shown, or `""`.

ComposeUI writes in the status bar too, for example when a file is saved or a table is
exported. It shows a failure in a [notification](#notifications). Qt shows a `QStatusBar`,
Textual a line at the bottom of the screen, and the web a footer at the bottom of the page. On
the web, the page clears the message itself after its timeout.

### Notifications

`notify` shows a message above the page, with its severity, a `LogType`, in the main view's
`notification`, a `NotificationBar`. Use it for a message that the user must not miss, such as
why a file can't be saved:

```python
from composeui.core.view import LogType

main_view.notify("Can't save to study.pipe: the disk is full.", LogType.ERROR)
```

- **A warning or an error stays** until the user closes it, the next message replaces it, or
  the app calls `main_view.clear_notification()`.
- **An information goes after `timeout` seconds,** 5 by default (`notification.timeout`). Its
  kind is `LogType.INFO`, the default of `notify`. With a `timeout` of 0, it stays too.
- **One message at a time.** A new message replaces the previous one. The same message again
  starts its timeout again.
- **The user closes it** with the button at its end. Then `notification.closed` emits. It never
  emits when the app clears the message.
- **`notification.message` and `notification.kind`** hold the message shown, or `""`, and its
  kind.
- **Not study data.** A study never saves the notification. New and Open keep it, and it
  doesn't count as an [unsaved change](#unsaved-changes). A web session saved to disk while
  idle, and a [reload](running-the-app.md#reloading-the-app-on-a-change) after a change of the
  code, show none.

ComposeUI shows its own failures this way, for example when a study fails to open, a table refuses
an edit, or the model refuses a change (`refusing`). Qt shows a tinted line with an icon of its kind
above the pages, Textual a bordered line above the content, outside its scrolling, and the web an
alert above the page's card, kept in view below the header as the page scrolls. The web reads an
error or a warning out at once to a screen reader, and an information when the reader is idle.
[`src/examples/markdownviewer.py`](../../src/examples/markdownviewer.py) says in a notification why
a file can't be read.

### The app's icon

A `MainView` shows its `app_icon`, an image file, as the app's icon. The default is
ComposeUI's icon. Set your own in the subclass, or set `None` for no icon:

```python
from pathlib import Path


@define_view
class PipeMainView(MainView):
    app_title = "Pipe Form"
    app_icon = Path(__file__).parent / "images" / "pipe.svg"
```

- **Qt** shows it as the window's icon.
- **The web** shows it in the browser tab and in the page's header, before the title.
  Without an icon, the header shows the first letter of the title in a badge.
- **Textual** shows no icon.

### Command-line options of your own

A `MainView` adds command-line options with its `add_arguments` classmethod. It gets their
values in `apply_arguments`, once it is wired. On the web, this happens for every session.

```python
import argparse
from pathlib import Path


@define_view
class MarkdownMainView(MainView):
    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--markdown", type=Path, metavar="FILE", help="Show the Markdown FILE.")

    def apply_arguments(self, args: argparse.Namespace) -> None:
        if args.markdown is not None:
            self.open_markdown(args.markdown)  # a method of the app
```

[`src/examples/markdownviewer.py`](../../src/examples/markdownviewer.py) adds `--markdown`.

## Structure an app

Split a larger app into components: views that each do one part of the work, such as a
search bar or a history. Each component wires its own views. The main view connects the
components:

```python
from attrs import Factory

from composeui.core.application import run
from composeui.core.signal import Signal
from composeui.core.view import (
    ButtonView,
    HorizontalView,
    InputView,
    LabelView,
    MainView,
    child,
    define_view,
)


@define_view
class SearchBar(HorizontalView):
    query: InputView = child(InputView, placeholder="Search...")
    search: ButtonView = child(ButtonView, text="Search", is_enabled=False)
    searched: Signal[str] = Factory(Signal[str])

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.query.text_edited.connect(self._on_query_edited)
        self.search.clicked.connect(self._on_search_clicked)

    def _on_query_edited(self, text: str) -> None:
        self.search.is_enabled = text != ""

    def _on_search_clicked(self) -> None:
        self.searched.emit(self.query.text)


@define_view
class LastSearch(LabelView):
    def show_search(self, query: str) -> None:
        self.text = f"Last search: {query}"


@define_view
class SearchMainView(MainView):
    app_title = "Search"
    has_file_menu = False

    search_bar: SearchBar = Factory(SearchBar)
    last_search: LastSearch = child(LastSearch, text="No search yet")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.search_bar.searched.connect(self.last_search.show_search)


if __name__ == "__main__":
    run(SearchMainView)
```

- **A component owns its views and their callbacks.** It connects the signals of its views
  and sets their validators in its `__attrs_post_init__`. For example, `SearchBar` enables
  its button when the query has text. Keep in the component the state that only it reads.
- **A component tells the app with a signal of its own,** a `Signal` field such as
  `searched`. The component then needs no other component. The state does not save a
  signal.
- **The main view connects the components** and does the work of the whole app: the
  callback of `loaded`, the menus, the toolbars, the dialogs, and the work that reads
  several components. It does not hold the callback of each button.
- **A callback that reaches another component asks for `main_view`** (see
  [Signals inject arguments](core-concepts.md#signals-inject-arguments)). Never keep a parent
  or another component in a view field: the app reads each view field as a child view, and
  a view that holds its parent makes the app loop forever as it starts.
- **Keep the state in the views and in the model,** not in a module or class variable. On
  the web, each session builds its own main view, but all the users share a module or class
  variable.
- **Keep the data and the slow work out of the views.** Do not import a view in the
  [model](sqlite-model.md) or in the functions of the [jobs](threads.md).
- **Define each view at module level,** not in a function. With
  `from __future__ import annotations`, `attrs` and `cattrs` read the types of the fields
  from the module. A large component can have its own module. Call `run` in the program's
  module, under `if __name__ == "__main__":`.

Split by the work that a component does, not by its number of lines. When a callback of the
main view only calls a method of a component, move the connection into the component too.
To test a component alone, see [Test a component](testing.md#test-a-component).

## Saving and loading state

Save and Open in the File menu save and open the study, in a file with the `extension` of the main
view. On Qt and Textual, Save writes into the file that the study was opened from or saved to, and
asks for a file only the first time. When another app changed that file since, Save asks before it
replaces it. Save As always asks for a file. On the web, Save downloads the study instead,
and the File menu has no Save As. `-f FILE` on the command line opens a study at the start.
Without a model, the study holds the state of the views. A model can add its data to the
study (see [A SQLite model](sqlite-model.md)).

`MainView.save_state(path)` writes the state of the whole view tree as JSON, with `cattrs`,
and `MainView.load_state(path)` reads it back. They skip the `Signal` and `Renderer` fields.
A load changes the views in place, so the renderers and the signal connections stay.

The `CONVERTER` of the views writes a `datetime.date` or a `datetime.datetime` as ISO 8601
text. A datetime keeps its UTC offset and its microseconds. A field of these types needs no
hook of its own.

The text that the user reads rather than enters (labels, titles, headers, button and menu
text) is tagged `UI_TEXT`, and is skipped too. This text comes from the app's code, in its
language, not from a study. Open keeps this text as it is. New sets it back to the text of
the view that `build_initial_view` gives. Tag a text field of your own views the same way:
`attrs.field(default="", metadata={UI_TEXT: True})`.

A study holds what the user enters and what the app computes from it: the values of the
fields, the rows and records of a table with its sort and its filters, and the series of a
chart. It also holds the message of the [status bar](#the-status-bar), which Open shows
again. Save does not write the rest, and Open and New keep it, except where this list says
otherwise:

- **Navigation:** the [page](organizing-the-window.md#pages) and the
  [tab](organizing-the-window.md#tabs) shown, and an open
  [dialog](organizing-the-window.md#dialogs).
- **Layout:** the sizes of [resizable panes](organizing-the-window.md#resizable-panes), and whether
  the [sidebar](organizing-the-window.md#sidebar) is retracted.
- **The app's setup:** class variables, the `icon` of an
  [action](organizing-the-window.md#toolbars), the `extensions` of a
  [file path input](widgets.md#file-path-input), and the `cell_widgets` and `cell_styles` of
  a [table](tables.md#a-table-of-records). The `header_groups` and `row_headers` of a table
  are `UI_TEXT`: New sets them back.
- **The `icon` of a [tree node](widgets.md#tree):** a study holds the nodes, but not their
  icons. Open replaces the nodes, so they show no icon. Set the icons again in a callback of
  `loaded`. New sets the nodes back, with their icons.
- **What the app gives again:** the source and the rows of a
  [large table](tables.md#a-large-table), and the views of a
  [list of views](organizing-the-window.md#a-list-of-views), which belong to the model.
- **The language** shown, which the main view or `--language` sets.

A session keeps some of this as it's saved and opened again: on a
[reload](running-the-app.md#reloading-the-app-on-a-change), and on the web while it's idle
(`session_idle`, see
[Serve the app to other users](running-the-app.md#serve-the-app-to-other-users)). It keeps the tab
shown, the sizes of the panes, and whether the sidebar is retracted. These fields are tagged
`SESSION`, with `OMIT`. Tag a field of your own views the same way, for where the user is rather
than their data: `attrs.field(default=0, metadata={OMIT: True, SESSION: True})`.

The main view emits `loaded` once the views and the model's data are in place: once as the
app starts, after its setup, with the study that `-f FILE` opens or with a new one, then
after each New and Open. On the web, each session emits it as it starts. Connect `loaded` to
give again what a study does not hold, from the fields that it does hold, such as a filter:

```python
from attrs import frozen

from composeui.core.application import run
from composeui.core.model import Model
from composeui.core.view import (
    ListSource,
    MainView,
    SliderView,
    SourceTableView,
    child,
    define_view,
)


@frozen
class Reading:
    sensor: str
    value: int


class ReadingsModel(Model):
    def __init__(self) -> None:
        self.readings = [Reading("A", 3), Reading("B", 8)]


@define_view
class ReadingsMainView(MainView):
    extension = ".readings"

    threshold: SliderView = child(SliderView, maximum=10)
    above: SourceTableView = child(SourceTableView)  # the readings above the threshold

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.loaded.connect(self._show_above)

    def _show_above(self, *, model: ReadingsModel) -> None:
        records = [r for r in model.readings if r.value > self.threshold.value]
        self.above.source = ListSource(Reading, {"sensor": "Sensor"}, records)


if __name__ == "__main__":
    run(ReadingsMainView, build_model=ReadingsModel)
```

A load sets the fields without emitting their signals, such as the slider's `value_changed`,
so a callback connected only to those does not run. On New and Open, a model reacts in
`Model.loaded`, which runs first, so a callback of `loaded` reads the data of the study.
The app's own command-line options apply after `loaded` (see
[Command-line options of your own](#command-line-options-of-your-own)).

If your main view's constructor needs arguments, pass `run` a function that supplies them.
ComposeUI calls that function at startup on Qt and Textual, and for each new session on the web.

For New, Open, and session restore, also override `MainView.build_initial_view`. Use the
current instance's configuration to return a separate view of the same class with its
starting values. ComposeUI uses this view to check saved state without changing the running
view, to start a new study, and to compare starting values across a reload. Do not reuse
child views from the running app. In the example, `OMIT` keeps `owner` out of the saved state.

```python
from __future__ import annotations

from attrs import field

from composeui.core.application import run
from composeui.core.view import OMIT, LabelRowIntInputView, MainView, child, define_view


@define_view
class OwnedMainView(MainView):
    owner: str = field(metadata={OMIT: True})
    number: LabelRowIntInputView = child(LabelRowIntInputView)

    def build_initial_view(self) -> OwnedMainView:
        return OwnedMainView(owner=self.owner)


if __name__ == "__main__":
    run(lambda: OwnedMainView(owner="Ann"))
```

### Unsaved changes

New, Open and Exit ask before they lose the changes of the study: "The study has unsaved
changes. Discard them?", with Discard and Cancel. Cancel leaves the study as it is. The changes
are those since the study was last saved, opened, or started. An app without a File menu
(`has_file_menu = False`) never asks, as the user can't save.

A change is what Save would write differently: a field of the study, or the model's data. A
field changed back to its saved value is no change. UI text, a dialog, a notification, and the tab
shown are not changes (see the list above). The status bar's message is not a change either,
though Save writes it.

A model tells its changes with `Model.data_version`. `DatabaseModel` counts its committed writes,
but not those of the jobs that the study's start started (see below). It does not compare the
data: a write that puts a value back is a change too. A model of your own with data changes
`data_version` as its data changes.

What the app does on its own as the study starts is not a change: its setup, the callbacks of
`loaded`, its command-line options, and the jobs they start, such as a download of the data a
chart shows. The next start gives the same again. A job's result is the user's change when the
user started the job, such as with a button, or when the user changed the study before the
result arrived.

- **`has_unsaved_changes()`** tells whether the study has changes.
- **`ask_discard_changes(proceed)`** calls `proceed()` at once when the study has no changes,
  else once the user agrees. Call it before an action of your own replaces the study.

```python
from pathlib import Path

from composeui.core.study import open_study
from composeui.core.view import ActionView, MainView, Menu, child, define_view

EXAMPLE = Path("example.pipe")


@define_view
class ExamplesMenu(Menu):
    open_example: ActionView = child(ActionView, text="Open the example")


@define_view
class PipeMainView(MainView):
    extension = ".pipe"

    examples: ExamplesMenu = child(ExamplesMenu, title="Examples")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.examples.open_example.triggered.connect(self._open_example)

    def _open_example(self) -> None:
        # Cancel opens nothing
        self.ask_discard_changes(lambda: open_study(self, None, EXAMPLE))
```

Each backend asks in its own way:

- **Qt** asks also when the user closes the window. A
  [reload](running-the-app.md#reloading-the-app-on-a-change) restarts without a question, and
  keeps the changes unsaved.
- **Textual** asks on Ctrl+Q, as on Exit.
- **The web** asks on New and Open. The browser sends the file to open first: a file of
  another type, or a file that is too large, is refused before the question. A closed tab does
  not close the session, so nothing asks. An idle session that the server saves keeps its
  changes unsaved.

### Autosave

On Qt and Textual, a main view with `autosave = True` saves the unsaved work to a folder of
the app's own. When the app ends without a clean close, such as a crash, the next start
offers to restore that work. The app's code calls nothing:

```python
from composeui.core.view import MainView, define_view


@define_view
class PipeMainView(MainView):
    extension = ".pipe"
    autosave = True
```

- **When it saves.** Every `autosave_interval` seconds, 60 by default, while the study has
  [unsaved changes](#unsaved-changes) that the last autosave does not hold. An idle app writes
  nothing. The log says "Autosaved the unsaved work in" and the folder at each autosave. A
  thread writes the views' state, and copies the data of a `DatabaseModel`, so the window does
  not wait. The first autosave copies the data. A later one copies the data of a
  `DatabaseModel` only after a committed write, also a write of a job that the study's start
  started, which `data_version` does not count. The data of a model of your own is copied by
  its `save_data`, on the main thread: at each autosave, unless the model changes its
  `data_version`.
- **What it is not.** An autosave is not the user's save: the study keeps its unsaved
  changes, and its file name. Save, New, and Open delete the autosave, and a clean close
  deletes the folder. A clean close is Exit, or the window closed, after the user saved or
  discarded the changes.
- **When it opens.** At the next start after an unclean end, unless `-f FILE` names a
  study, the app starts with a new study and asks: "The app closed without saving. Restore the
  unsaved work of", the time, with Restore and Discard.
  - **Restore** opens the work. The study has unsaved changes, so New, Open, and Exit ask.
    Save writes into the study file that was open, if any, and asks first when that file
    changed since it was opened.
  - **Discard** deletes the work.
  - **Closing the question,** such as with Escape, keeps the work for the next start.

  Work that no longer opens, such as one of a newer version of the app, is moved aside in its
  folder, and a notification says why.
- **Where it is.** In a folder of the app's own, in a `composeui` folder of the user's data
  directory: `~/.local/share/composeui` on Linux (`$XDG_DATA_HOME`),
  `~/Library/Application Support/composeui` on macOS, and `%LOCALAPPDATA%\composeui` on
  Windows. The environment variable `COMPOSEUI_AUTOSAVE_DIR` names another directory. Each
  running app has a folder of its own in it, so two windows of the same app do not write over
  each other.
- **The app's folder** is named after the main view's module and class. For an app that runs
  as a script (`python app.py`, `composeui run app.py`), it is named after the class and the
  path of the script's file: a script moved after a crash does not find its work. Set
  `app_id = "pipes"` on the main view to give the folder a fixed name. A script without a
  file, such as `python -c`, does not autosave unless it sets `app_id`.

Autosave is off by default: a form that must start empty must not open old values. The web
does not autosave, and neither does an app under `--reload`, which saves the study itself
between two runs of the code. `composeui run app.py` reloads by default: run
`composeui run --no-reload app.py`, or `python app.py`, to autosave.

### Versions of the state

A study file holds the state of the views, and two versions: the version of ComposeUI's
file format, and the app's `state_version`, 1 by default.

A file opens in any version of the app while the views can read its fields. When it has a
field that the views do not have, the views skip that field. When it does not have a field of
the views, that field keeps its value. So most changes need no new version:

- **No new version** for a new field, or a field that you remove. Older and newer versions
  of the app open each other's files.
- **A new version** for a renamed or moved field, or a field whose value changes its form.
  Without it, an older file loses the field's value with no message, or Open refuses the
  file.

Raise `state_version` only for a change of the second kind. A raised version has two
effects:

- **Older versions of the app refuse the new files,** and a notification says why. An older
  version cannot read the changed field. It would show the study without that value, and a
  Save would then lose the value for good. Open also refuses a file of a newer ComposeUI
  file format.
- **The new version upgrades the older files** in `MainView.migrate_state`, which you
  override. It gets the state of an older file, as a `dict`, and the version that saved it.
  It returns the state as the views save it now:

```python
from typing import Any

from attrs import Factory

from composeui.core.view import InputView, MainView, define_view


@define_view
class PipeMainView(MainView):
    extension = ".pipe"
    state_version = 2  # version 1 named this field `name`

    label: InputView = Factory(InputView)

    def migrate_state(self, data: Any, version: int) -> Any:
        if version < 2:
            data["label"] = data.pop("name")
        return data
```

When the upgrade fails, for example on a key that the file does not have, Open refuses the
file. A file saved before ComposeUI wrote the versions opens as version 1.
