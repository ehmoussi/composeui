# Widgets

This page covers the small views: a label, a button, the inputs that need more than the
[table of fields](building-views.md#forms-and-their-fields), and the views that show a result.
The larger views have sections of their own: [tables](tables.md#a-table-of-records),
[charts](charts.md), [maps](maps.md), [dialogs](organizing-the-window.md#dialogs), and the
views that organize the window, from [pages](organizing-the-window.md#pages) to the
[sidebar](organizing-the-window.md#sidebar). The [widget catalog](../widgets.md) lists every
view.

## Label

A `LabelView` shows a line of read-only `text`, for example a caption or a result. Code sets
the text. The user can't edit it.

```python
from composeui.core.view import LabelView, child

summary: LabelView = child(LabelView, text="No pipe yet")
```

Qt shows a `QLabel`, Textual a `Label`, and the web a line of text. For several lines with
headings and links, use a [Markdown view](#markdown).

## Buttons

A `ButtonView` is a button that the user clicks (`clicked`), for example under a form to
submit it. `text` names it.

Its `variant` (`ButtonVariant`) tells the actions apart:

- **`PRIMARY`,** the default, is the main action of the page, for example to submit its form.
- **`SECONDARY`** is an action beside the main one.
- **`DANGER`** is an action that destroys something, for example to remove rows.

In a [`HorizontalView`](building-views.md#lay-out-views), a button keeps the width of its text.

Qt shows a `QPushButton`: a primary button is the default button, and a danger button has
red text. Textual and the web color the button by its variant.

## Help on a form row

The `help` of a labelled row says what to enter. A "?" button beside the label shows it.
A click, a tap, or the keyboard opens it. Textual shows the help as a hint under the label.

## Integer input

An `IntInputView` takes a whole number between its `minimum` and `maximum`, for example
an hour of the day.

- Qt shows a spin box, which keeps the number in range.
- The other backends show a text field for digits. They do not refuse a number out of
  range (Textual marks it), so validate the number.

## Date input

A `DateInputView` takes a `datetime.date`, for example the first day of a booking, or no
date (`None`).

The user types the date in the format that `date_format` gives (`dd`, `MM`, `yyyy`).
ISO 8601 is always understood. The catalogs translate `date_format` as text, so the format
follows the main view's language: "MM/dd/yyyy" in English, "dd/MM/yyyy" in French.

The user can also pick the date from a calendar beside the field:

- Qt shows its own calendar. It names the months and days in the system's language.
- The web shows [Cally](https://wicky.nillia.ms/cally/), in the colors of the theme and in
  the page's language.
- Textual shows ComposeUI's own calendar. It names the months and days with the view's
  `month_names` and `day_names`.

The calendar offers only the dates from `minimum` to `maximum`. But not every backend
refuses a typed date out of range, so validate the date. `value_changed` reports the dates
that the user enters.

## File path input

A `FilePathInputView` takes the path of a file, for example a data file or a template file
for the app to read. The user types the path, or picks the file with the "…" button beside
the field.

```python
from composeui.core.view import FormView, LabelRowFilePathInputView, child, define_view


@define_view
class DataForm(FormView):
    measurements: LabelRowFilePathInputView = child(
        LabelRowFilePathInputView,
        label="Measurements",
        extensions={"CSV": (".csv",)},
        has_reload=True,
    )
```

- `text` holds the path as the user typed it. `path` reads it as a `Path`, or `None` while
  the field is empty.
- `extensions` names the file types that the "…" button offers. On the web, the backend
  refuses a file of another type.
- `path_picked` emits the path of a file that the user picks with the "…" button. A typed
  path comes through the signals of any text field: `text_edited` and `editing_finished`.
- With `has_reload`, a reload button shows beside the "…" button. It emits
  `reload_clicked`, for example to read the file again after it changed.
- `browse_text` and `reload_text` name the two buttons in a tooltip and for a screen
  reader. The catalogs translate them.

The state saves `text` and `has_reload`, but not `extensions` or `server_roots`, which the app
sets.

What the "…" button opens:

- Qt shows its file dialog, in the directory of the field's path.
- Textual shows the file picker of textual-fspicker, in the directory of the field's path.
- The web shows the browser's file picker. The browser cannot give the page a path, so it
  uploads the file. The session keeps a copy, and the field shows the path of that copy. The
  session deletes the copy when the field gets its next upload, or when the session ends. With
  `server_roots`, the web lists the server's files instead (see
  [Files on the server](#files-on-the-server)).

[`src/examples/markdownviewer.py`](../../src/examples/markdownviewer.py) opens a Markdown file
with a file path input, and reads the file again when the user presses reload.

### Files on the server

On the web, the "…" button uploads a copy of the file. A copy is not always what the app
needs: a study file can refer to other files beside it, or the files are on the server
already. Give the field `server_roots`, the folders whose files the web lists:

```python
from pathlib import Path
from typing import Optional

from composeui.core.view import FormView, LabelRowFilePathInputView, child, define_view

STUDIES = Path.home() / "studies"


@define_view
class StudyForm(FormView):
    study: LabelRowFilePathInputView = child(
        LabelRowFilePathInputView,
        label="Study",
        extensions={"Code_Aster": (".export",)},
        server_roots=(STUDIES,),
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.study.set_validator(self._check_study, self.study.text_edited)

    def _check_study(self) -> Optional[str]:
        # `path` is None for a path typed outside the roots
        if self.study.text != "" and self.study.path is None:
            return f"Pick a study in {STUDIES}."
        return None
```

- **What the web lists.** The "…" button opens a dialog with the folders and the files of
  `extensions` in a folder, starting in the folder of the field's file, else in the only
  root. A folder's item shows its files, and "Parent folder" goes up, as far as a root. With
  several roots, the dialog starts with the list of the roots.
- **Only the roots.** The dialog shows nothing outside the roots. It leaves out hidden items,
  whose name starts with a dot, and items that a symbolic link leads out of the roots to. A
  root that doesn't exist is left out. A folder of more than 2,000 items is listed only in
  part: the dialog asks the user to type the file's path.
- **The path picked.** A file's item puts the file's path on the server in the field, and
  `path_picked` emits it. The web copies nothing, so the files beside it stay beside it.
- **A typed path.** The user can still type any path of the server. On the web, `path` is
  `None` for a path outside the roots, symbolic links followed. Read `path`, not `text`, and
  show why it is `None`, as `_check_study` does above.
- **Qt and Textual** open their dialogs in the first root while the field is empty. The user
  can leave the roots: the app runs on the user's own machine.
- **The texts** of the dialog are `parent_folder_text`, `cancel_text`, `unreadable_folder_text`
  and `partial_folder_text`. The catalogs translate them.

Every user of a web app sees the names of the folders and files in the roots. Give only the
folders that every user may see.

## Folder path input

A `FolderPathInputView` takes the path of a folder, for example where the app writes its
results. The user types the path, or picks the folder with the "…" button beside the field.

```python
from pathlib import Path

from composeui.core.view import FormView, LabelRowFolderPathInputView, child, define_view


@define_view
class OutputForm(FormView):
    results: LabelRowFolderPathInputView = child(
        LabelRowFolderPathInputView,
        label="Results folder",
        server_roots=(Path.home() / "studies",),
    )
```

- `text` holds the path as the user typed it. `path` reads it as a `Path`, or `None` while
  the field is empty.
- `path_picked` emits the path of a folder that the user picks with the "…" button. A typed
  path comes through the signals of any text field: `text_edited` and `editing_finished`.
- `browse_text` names the "…" button in a tooltip and for a screen reader. The catalogs
  translate it.

The state saves `text`, but not `server_roots`, which the app sets.

What the "…" button opens:

- Qt shows its folder dialog (`QFileDialog.getExistingDirectory`), in the field's folder,
  else in the first of `server_roots`.
- Textual shows the folder picker of textual-fspicker (`SelectDirectory`), in the same
  folder.
- The browser cannot give the page a folder's path. On the web, without `server_roots`,
  the field has no "…" button: the user types the path. With `server_roots`, the button
  lists the server's folders in them, as a file field lists its files (see
  [Files on the server](#files-on-the-server)). A folder's item shows its folders, and
  "Choose this folder" puts the folder shown in the field. On the web, `path` is `None` for
  a path typed outside the roots.

## Save path input

A `SavePathInputView` takes the path of a file to save, for example a report that the app
writes. The file may not exist yet. The user types the path, or picks it with the "…"
button beside the field.

```python
from pathlib import Path

from composeui.core.view import FormView, LabelRowSavePathInputView, child, define_view


@define_view
class ReportForm(FormView):
    report: LabelRowSavePathInputView = child(
        LabelRowSavePathInputView,
        label="Report",
        extensions={"PDF": (".pdf",)},
        server_roots=(Path.home() / "studies",),
    )
```

- `text` holds the path as the user typed it. `path` reads it as a `Path`, with the first of
  `extensions` added when the name has none of them: "report" reads as `report.pdf`.
  `path` is `None` while the field is empty.
- `path_picked` emits the path that the user picks with the "…" button. A typed path comes
  through the signals of any text field: `text_edited` and `editing_finished`.
- With `confirms_overwrite` (on by default), the user agrees to replace a file that exists
  before it is picked.
- `browse_text` ("Save as"), `file_name_text`, `save_text`, `replace_question_text` and
  `replace_text` name the button and the texts of the dialog. The catalogs translate them.

The state saves `text`, but not `extensions`, `confirms_overwrite` or `server_roots`, which
the app sets.

What the "…" button opens:

- Qt shows its save dialog, on the field's path, else in the first of `server_roots`. It
  asks before it replaces a file. When the first extension, added to the name typed, names
  a file that exists, the field asks too.
- Textual shows the save picker of textual-fspicker, on the same path. Before it replaces a
  file, the field asks in a dialog of its own; Escape keeps the file.
- The browser cannot give the page a path. On the web, without `server_roots`, the field has
  no "…" button: the user types the path. With `server_roots`, the button lists the server's
  folders in them and their files of `extensions` (see
  [Files on the server](#files-on-the-server)). A file's item puts its name in the "File
  name" box. "Save", or Enter in the box, picks the folder shown with that name. The
  dialog asks there before it replaces a file, and refuses a name that is not a file's,
  such as one with a separator, or a folder's. On the web, `path` is `None` for a path typed
  outside the roots.

## Slider

A `SliderView` picks a whole number when the user drags a handle, for example a number of
workers. The number goes from `minimum` to `maximum` by `step`. The handle stops only on a
step. The value shows beside the track, so the row is no taller than the other rows.
`value_changed` reports the user's moves.

Qt shows a horizontal `QSlider`, Textual ComposeUI's own slider, which the arrow keys
move, and the web a range input.

## Progress bar

A `ProgressBarView` shows how far a long task has gone: `value` steps out of `maximum`.
While `maximum` is `None`, the bar shows only that the task runs.

Qt shows a `QProgressBar`, Textual a `ProgressBar`, and the web a `<progress>` bar.

[`src/examples/taskview.py`](../../src/examples/taskview.py) follows tasks that run in
[threads](threads.md) with a progress bar
(`uv run python -m examples.taskview`, or `--backend qt`, or `textual`).

## Metric

A `MetricView` shows a figure to read at a glance, for example the number of jobs running.
It shows its `label` and its `value` in large type. A badge shows the change since some
point: `delta` is the change, and `delta_text` says the point, for example "since
yesterday". The sign of the change sets the color of the badge. To show a row of metrics,
put them in a `HorizontalView`.

Qt and Textual show the value in bold, and the web as a daisyUI stat.

## Log message

A `LogView` shows a message to the user in the page, for example the error of an import.
Set its `log_message`, and its `log_type` (`LogType`: `ERROR`, the default, `WARNING`, or
`INFO`):

```python
from composeui.core.view import LogType

main_view.import_log.log_message = "The file has no column named radius."
main_view.import_log.log_type = LogType.WARNING
```

The view hides while `log_message` is empty. An error shows in red and a warning in orange. A
[check of a row](building-views.md#check-a-form) writes the same two fields of the row, and the row
shows its message under its field.

Qt shows a `QLabel`, Textual a `Label`, and the web a paragraph that screen readers read
when it changes (`aria-live="polite"`).

A new message replaces the last one. To show a stream of output, such as the output of a
process, use a [console](#console).

## Expander

An `ExpanderView` is a collapsible section, for example the details of a record with its
Edit and Delete buttons. The view fields of a subclass are its content, one above the
other. They show only while `is_expanded` is true. The user clicks the `title` to expand
or collapse the section (`toggled`).

Qt shows a header button with an arrow, Textual a `Collapsible`, and the web a `<details>`
element.

## Tree

A `TreeView` shows `nodes` in a tree, for example the buildings, floors, and rooms of a site.
Each node is a `TreeNode` with its `label` and `children`.

A path identifies a node: the `key`s from its top-level node down to it, for example
`("Building A", "Floor 1")`. The key of a node is its label, unless you give one.

The user expands and collapses the nodes (`expanded`, `toggled`), and selects one node
(`selected`, `selection_changed`). When code sets new `nodes`, the tree keeps the expanded
and selected paths that are still in them.

A node can also show the kind and the state of what it stands for, as a study tree does:

```python
from composeui.core.view import NodeMark, TreeNode

TreeNode(
    "Study 1",
    [TreeNode("Monte Carlo", mark=NodeMark.DONE), TreeNode("Sobol", mark=NodeMark.ERROR)],
    icon="icons/study.svg",
    is_bold=True,
)
```

- **`icon`** is the path of an image file before the label, as the `icon` of an action is
  (see [Toolbars](organizing-the-window.md#toolbars)). Qt and the web show it, a terminal does
  not. The app's code sets it, so it is never saved or loaded: build the nodes again from
  the model after a load.
- **`mark`** is a `NodeMark` after the label: `DONE` (a green check), `WARNING` (an orange
  "!") or `ERROR` (a red cross). The tree's `done_text`, `warning_text` and `error_text`
  name the marks: Qt shows the name as the mark's tooltip, and the web gives it to screen
  readers as the node's description.
- **`is_bold`** and **`is_underlined`** style the label.

Qt shows the marks in a second column of the `QTreeWidget`, Textual as a colored glyph
(✓, !, ✗), and the web as an icon in the node's button.

On the web, a label that is too long for the tree ends in an ellipsis.

[`src/examples/pipecatalogue.py`](../../src/examples/pipecatalogue.py) shows its pipes in a
tree, under their material. It builds the tree again from the database whenever the pipes
change.

## Markdown

A `MarkdownView` shows read-only Markdown `text`, for example a help page or the summary of
a report. Its links open in the browser. The view never reads raw HTML in the text as
markup: Qt and the web show it as text, and Textual leaves out its tags.

[`src/examples/pipeform.py`](../../src/examples/pipeform.py) has a help page.
[`src/examples/markdownviewer.py`](../../src/examples/markdownviewer.py) shows a Markdown file
(`uv run python -m examples.markdownviewer --markdown README.md --backend qt`).

## Console

A `ConsoleView` shows plain text that the app adds to as it comes, for example the output of a
solver that a [job](threads.md) runs. To show one message to the user, such as an error, use a
[log message](#log-message) instead.

Call `append` with the new text, such as each line that the job reports as its progress:


```python
import io
import subprocess
import sys

from composeui.core.jobs import Job
from composeui.core.view import ConsoleView, MainView, child, define_view

SOLVER = "print('Step 1'); print('50%', end='\\r'); print('Done')"


def run_solver(job: Job[int, str], command: list[str]) -> int:
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
        assert process.stdout is not None
        # newline="": each line keeps its "\r" or "\n", which text mode reads as "\n"
        for line in io.TextIOWrapper(process.stdout, encoding="utf-8", newline=""):
            job.report_progress(line)
    return process.returncode


@define_view
class SolverView(MainView):
    output: ConsoleView = child(ConsoleView, max_lines=5_000)

    def run(self) -> None:
        self.output.clear()
        job = self.jobs.start(run_solver, [sys.executable, "-c", SOLVER])
        job.progress.connect(self.output.append)


main_view = SolverView()
main_view.run()
main_view.jobs.wait()  # Only for a main view with no toolkit.
assert main_view.output.text == "Step 1\nDone\n"
```

- **Lines.** "\n" ends a line. "\r" starts the line again: the next text replaces it, as a
  terminal shows a progress line. "\r\n" ends the line. Python reads a "\r" in text mode as
  "\n", so read the output with `newline=""`, as the example does.
- **The last lines.** The view keeps the last `max_lines` lines (10,000 by default) and drops
  the oldest. `lines` holds them, and `last_line` the line being written. `line_count` counts
  the lines ended since the view was built, the dropped ones too.
- **Replace and clear.** `text` holds the lines, then the line being written. Set it to
  replace them, or call `clear`.
- **The text as it is.** The view never reads the text as markup: a tag shows as text.
- **Scrolling.** The view scrolls to its end as text comes. When the user scrolls up to read,
  it stays there, until the user scrolls back to the end.
- **Not study data.** The text is the app's output: a study never saves, loads or resets it.

Qt shows a read-only `QPlainTextEdit` in a fixed-width font, Textual a `Log`, and the web a
box of preformatted text. Qt and the web wrap a long line; Textual scrolls sideways. The user
selects and copies the text on each backend. On the web, a change sends only the new lines.

## The File menu and picking a file

The File menu has New, Open, Save, Save As, and Exit. An app without studies sets
`has_file_menu = False` on its `MainView` to leave out the File menu.

A `PickFileAction` is a menu or toolbar action that picks a file for the app to read (not a
study). `extensions` names the types that it offers, for example
`{"Markdown": (".md",)}`. `file_picked` emits the path of the file. On the web, the browser
uploads the file. The path is then a copy, which is deleted once the callbacks have run.

[`src/examples/markdownviewer.py`](../../src/examples/markdownviewer.py) has no File menu. It
opens Markdown files with a [file path input](#file-path-input) instead of a
`PickFileAction`.
