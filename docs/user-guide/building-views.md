# Building views

This section builds a small form, with its layout and its checks:

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

    save: ButtonView = child(ButtonView, text="Save")


@define_view
class PipeMainView(MainView):
    app_title = "Pipes"
    extension = ".pipe"

    form: PipeForm = Factory(PipeForm)
    buttons: FormButtons = Factory(FormButtons)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.buttons.save.clicked.connect(self._save)

    def _save(self) -> None:
        self.form.check()
        if self.form.is_valid:
            self.status_bar.show_message(f"Saved {self.form.name.text}")


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
  start or the end of the row. On the web, a row narrower than 42rem stacks its views.
- **A `VerticalView` puts its view fields one above the other,** for a column in a
  `HorizontalView`, for example a table above its buttons.
- **A `GridView` puts each view field in a cell,** from its `GRID_POSITION` metadata:
  `metadata={GRID_POSITION: (1, 0)}`, or `GridPosition(1, 0, column_span=2)`.

For panes that the user resizes, see [Resizable panes](organizing-the-window.md#resizable-panes).

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
| `FloatInputView` | `value`, a `float` or `None`, from `minimum` to `maximum`, with `decimals` | Types a decimal number |
| `IntInputView` | `value`, an `int` or `None` (see [Integer input](widgets.md#integer-input)) | Types a whole number |
| `DateInputView` | `value`, a `datetime.date` or `None` (see [Date input](widgets.md#date-input)) | Types or picks a date |
| `FilePathInputView` | `text`, and `path` (see [File path input](widgets.md#file-path-input)) | Types or picks a file |
| `CheckBoxView` | `is_checked`, with its `text` beside the box | Checks or unchecks the box (`toggled`) |
| `RadioGroupView` | `value`, one of `values` | Picks one of a few choices |
| `ComboBoxView` | `value`, one of `values` | Picks one choice in a drop-down list |
| `SliderView` | `value`, from `minimum` to `maximum` by `step` (see [Slider](widgets.md#slider)) | Drags a handle |

Each field has its row views too, for example `RowFloatInputView` and
`LabelRowFloatInputView`, or `LabelRowDateInputView` for a date. The
[widget catalog](../widgets.md#form-rows) lists every row view.

- **The text fields** emit `text_edited` on each change that the user makes, and
  `editing_finished` when the user is done with the field, for example on Enter.
- **A choice** maps each label to its value: `values = {"Steel": Material.STEEL}`. `value`
  is `None` or one of `values`. `value_changed` reports the user's choice.
- **A [`LabelView`](widgets.md#label)** shows a line of read-only text, for example a result.
- **The [status bar](#the-status-bar)** of the main view shows a short message, for
  example the result of a form.

## Check a form

A check is a function without arguments. It returns an error message, or `None` when the
value is good:

- **A row's own check.** `row.set_validator(check, *signals)` runs `check` each time one of
  the signals fires, and shows its message under the row's field. It does not run at once:
  call `run_validator()` to show the error before the first edit.
- **A check of several rows.** `form.add_validator(check, *signals, rows=(...))` checks the
  values of several rows together. The form shows the messages of the failing checks at its
  end, and marks the fields of `rows` as invalid.
- **Before an action.** `form.check()` runs every check of the form and its nested forms
  now. Then `form.is_valid` tells whether they all pass.

In a [form dialog](organizing-the-window.md#form-dialogs), OK stays disabled while a check fails.
[`src/examples/pipeform.py`](../../src/examples/pipeform.py) checks its name field, and has two
checks of several rows.

## Compose views from mixins

You can compose a view by mixing traits. For example, `LabelRowFloatInputView` combines
`FormLabelRowView` and `FloatInputMixin`. The mixins in `composeui/core/view.py` are the
available building blocks: `InputMixin`, `FloatInputMixin`, `IntInputMixin`,
`DateInputMixin`, `FilePathInputMixin`, `SliderMixin`, `CheckBoxMixin`, `ValuesGroupMixin`,
`TableMixin`, `LogMixin`, `LabelMixin`, and `MarkdownMixin`.

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

## The main view

A subclass of `MainView` is the app. Its class variables configure it:

- **`app_title`** is the name of the app, in the title of the window.
- **`extension`** is the file type of its studies, for example `".pipe"`.
- **`has_file_menu = False`** leaves out the File menu, for an app without studies (see
  [The File menu and picking a file](widgets.md#the-file-menu-and-picking-a-file)).
- **`app_icon`** is the icon of the app (see [The app's icon](#the-apps-icon)).
- **`width`** sets the default width of the web content, also in an app without pages
  (see [Page width](organizing-the-window.md#page-width)). Qt and Textual ignore it.
- **`translations_dir`** is the directory of its catalogs (see
  [Translating the app](translation.md)).

Its view fields are the content of the window, one above the other. Its `status_bar` shows
short messages, and its `jobs` [run work in threads](threads.md).

### The status bar

The `status_bar` of the main view is a line at the bottom of the window. It shows a short
message to the user, for example "Saved", or why an edit was refused:

```python
main_view.status_bar.show_message("Saved")
```

- **The message goes after `timeout` seconds,** 3 by default. With a `timeout` of 0, it
  stays until the next message, or until `clear_message()`.
- **A new message replaces the previous one,** and its timeout starts again.
- **`message`** holds the message shown, or `""`.

ComposeUI writes in the status bar too, for example when a table refuses an edit or a study
fails to open. Qt shows a `QStatusBar`, Textual a line at the bottom of the screen, and the
web a footer at the bottom of the page. On the web, the page clears the message itself after
its timeout.

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

## Saving and loading state

Save and Open in the File menu save and open the study, in a file with the `extension` of the
main view. `-f FILE` on the command line opens a study at the start. Without a model, the
study holds the state of the views. A model can add its data to the study (see
[A SQLite model](sqlite-model.md)).

`MainView.save_state(path)` writes the state of the whole view tree as JSON, with `cattrs`,
and `MainView.load_state(path)` reads it back. They skip the `Signal` and `Renderer` fields.
A load changes the views in place, so the renderers and the signal connections stay.

The `CONVERTER` of the views writes a `datetime.date` or a `datetime.datetime` as ISO 8601
text. A datetime keeps its UTC offset and its microseconds. A field of these types needs no
hook of its own.

The text that the user reads rather than enters (labels, titles, headers, button and menu
text) is tagged `UI_TEXT`, and is skipped too. This text comes from the app's code, in its
language, not from a study. Tag a text field of your own views the same way:
`attrs.field(default="", metadata={UI_TEXT: True})`.

A study holds what the user enters and what the app computes from it: the values of the
fields, the rows and records of a table with its sort and its filters, and the series of a
chart. Saving, opening, and New leave the rest alone:

- **Navigation:** the [page](organizing-the-window.md#pages) and the
  [tab](organizing-the-window.md#tabs) shown, and an open
  [dialog](organizing-the-window.md#dialogs).
- **Layout:** the sizes of [resizable panes](organizing-the-window.md#resizable-panes), and whether
  the [sidebar](organizing-the-window.md#sidebar) is retracted.
- **The app's setup:** class variables, the `icon` of an [action](organizing-the-window.md#toolbars)
  or a [tree node](widgets.md#tree), the `extensions` of a
  [file path input](widgets.md#file-path-input), and the `cell_widgets`, `cell_styles`,
  `header_groups`, and `row_headers` of a [table](tables.md#a-table-of-records).
- **What the app gives again:** the source and the rows of a
  [large table](tables.md#a-large-table), and the views of a
  [list of views](organizing-the-window.md#a-list-of-views), which belong to the model.
- **The language** shown, which the main view or `--language` sets.

### Versions of the state

A study file holds the state of the views, and two versions: the version of ComposeUI's
file format, and the app's `state_version`, 1 by default.

A file opens in any version of the app while the views can read its fields. When it has a
field that the views don't have, the views skip that field. When it doesn't have a field of
the views, that field keeps its value. So most changes need no new version:

- **No new version** for a new field, or a field that you remove. Older and newer versions
  of the app open each other's files.
- **A new version** for a renamed or moved field, or a field whose value changes its form.
  Without it, an older file loses the field's value with no message, or Open refuses the
  file.

Raise `state_version` only for a change of the second kind. A raised version has two
effects:

- **Older versions of the app refuse the new files,** and the status bar says why. An older
  version can't read the changed field. It would show the study without that value, and a
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

When the upgrade fails, for example on a key that the file doesn't have, Open refuses the
file. A file saved before ComposeUI wrote the versions opens as version 1.
