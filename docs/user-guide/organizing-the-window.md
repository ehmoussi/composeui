# Organizing the window

These views organize the window: pages, tabs, panes, a list of views, menus, toolbars, a
sidebar, and dialogs.

## Pages

A `Router` shows one page at a time. It adds a toolbar with an entry per page. Each page is
a `PageView` with:

- a `route`: a unique name made of letters, digits, `_`, and `-`;
- a `page_title`: its entry in the toolbar.

The view fields of a page are its content, laid out in a column:

```python
from attrs import Factory

from composeui.core.view import MainView, PageView, Router, TableView, child, define_view


@define_view
class ResultsPage(PageView):
    route = "results"
    page_title = "Results"

    summary: TableView = child(TableView, headers=["Pipe", "Radius"])


@define_view
class Pages(Router):
    form: FormPage = Factory(FormPage)  # another PageView; the first one shows at first
    results: ResultsPage = Factory(ResultsPage)


@define_view
class AppMainView(MainView):
    pages: Pages = Factory(Pages)
```

A click on a toolbar entry triggers the page's `action`, which shows the page. Code does the
same with `pages.navigate("results")`, and reacts to it through `pages.route_changed`.

The page shown is navigation, not study data: saving, opening, and New leave it alone.

On the web, the page shown sets how wide the content grows. A subclass sets its `width`, a
`PageWidth`:

- **`NARROW`,** the default, keeps a column of fields easy to read (at most 48rem).
- **`WIDE`** gives room for views side by side, such as tables (at most 72rem).
- **`FULL`** takes the whole window.

```python
from composeui.core.view import PageWidth


@define_view
class ResultsPage(PageView):
    route = "results"
    width = PageWidth.WIDE
```

On Qt and Textual, the window sets the width, and `width` changes nothing.

Qt docks the toolbar as a `QToolBar`. Textual shows a row of buttons at the top. The web puts the
toolbar in the page header, with a web address per page.
[`src/examples/pipeform.py`](../../src/examples/pipeform.py) is an app with three pages: Inputs,
Results, and Help.

## Tabs

A `TabView` shows its views one tab at a time. The user picks a tab from a row of tabs, for
example the details of a record and its history. Its `TabPage` fields are the tabs, in
order. Each tab shows its `title` and has its view fields as its content, in a column:

```python
from composeui.core.view import LabelView, TabPage, TabView, child, define_view


@define_view
class DetailsTab(TabPage):
    length: LabelView = child(LabelView, text="Length: 12 m")


@define_view
class PipeTabs(TabView):
    details: DetailsTab = child(DetailsTab, title="Details")
    history: HistoryTab = child(HistoryTab, title="History")  # another TabPage
```

The view starts on the first tab. Code shows another tab with `current_index`, counted from
0. `current_tab` is the tab shown. `current_changed` reports the user's picks.

- The tab shown is navigation, not study data, as for pages.
- A hidden tab page hides its tab. The user can't pick a disabled tab page.
- Tabs are not [pages](#pages): tabs live inside a page or a form, and have no address of
  their own.

Qt shows a `QTabWidget`, Textual a `TabbedContent`, and the web a row of tabs. On the web,
the arrow keys move between the tabs.
[`src/examples/pipechart.py`](../../src/examples/pipechart.py) shows its chart on one tab, and
the measurements plotted on it, as a table, on another tab.

## Resizable panes

A `SplitterView` lays out its view fields side by side, as panes. The user drags the border
between two panes to resize them, for example a study tree beside its result. Each pane
starts with its share of the width. The `STRETCH` metadata of its field sets the share, as in
a `HorizontalView`:

```python
import attrs

from composeui.core.view import STRETCH, SplitterView, define_view


@define_view
class StudySplitter(SplitterView):
    study: StudyTree = attrs.Factory(StudyTree)  # a TreeView
    result: ResultTabs = attrs.field(factory=ResultTabs, metadata={STRETCH: 3})
```

`sizes` holds the shares of the panes (here `[1, 3]`). To share the width differently, code
sets `sizes`.

The user drags a border, or moves it with the arrow keys once the border has the focus.
After that, `sizes` holds the panes shown, in percent of their width. `resized` reports
them once the user drops the border. It never reports them when code sets `sizes`.

- A pane never shrinks to nothing. A hidden pane leaves its width to the other panes.
- The width of the panes is layout, not study data: it is never saved, loaded, or reset.

Qt shows a `QSplitter`. Textual shows a row of panes with a `│` border between two panes.
The web shows an ARIA window splitter. Side by side, each pane is at least 12rem wide, so
that its text stays readable: the border stops there. When a splitter is narrower than 42rem,
the web stacks its panes without borders. It stacks the views of a row in the same way.
[`src/examples/pipecatalogue.py`](../../src/examples/pipecatalogue.py) shows its tree of pipes
by material in a splitter, beside the expanders of the pipes.

### Panes one above the other

A subclass that sets `orientation` to `Orientation.VERTICAL` lays out its panes one above
the other instead. The panes then share its height, for example a chart above its table:

```python
from composeui.core.view import Orientation


@define_view
class ResultSplitter(SplitterView):
    orientation = Orientation.VERTICAL

    chart: CurveChart = attrs.field(factory=CurveChart, metadata={STRETCH: 2})  # a ChartView
    measurements: Measurements = attrs.Factory(Measurements)  # a TableView
```

Its `sizes` are then shares of its height. The user drags a horizontal border, or moves it
with the up and down keys.

- Qt shares the spare height of the window.
- Textual shares a height of 24 rows, and the web a height of 32rem. Each pane scrolls
  within its share.

The web never stacks the panes of a vertical splitter any other way: it keeps their borders
on a narrow screen.

## A list of views

A `ListView` shows a view per record, one above the other. For example, it shows an
expander per record, with the details of the record and its Delete button. A subclass
builds the view of a record. Set `items` to the records, for example the model's, to show
them:

```python
from composeui.core.view import ExpanderView, LabelView, ListView, View, child, define_view


@define_view
class PipeExpander(ExpanderView):
    length: LabelView = child(LabelView)


@define_view
class PipeList(ListView[Pipe]):  # Pipe: an attrs record
    def build_item(self, item: Pipe) -> View:
        view = PipeExpander(title=item.name)
        self.update_item(view, item)
        return view

    def item_key(self, item: Pipe) -> str:
        return item.name

    def update_item(self, view: View, item: Pipe) -> bool:
        view.length.text = f"Length: {item.length:g} m"
        return True
```

`item_key` tells the records apart. By default, the key is the record itself.

- A new record gets a view of its own.
- A record that is gone takes its view along.
- A record that is still there keeps its view.
- A changed record keeps its view if `update_item` shows the change in the view and returns
  True. The view then keeps what the user did to it: an expander stays expanded. Otherwise,
  the record gets a new view.

A view built later is set up like the other views. Its signals pass `main_view` and `model`
to the callbacks that ask for them, and it shows the main view's language.

The records and their views belong to the model. They are not study data: saving, opening,
and New leave them alone.

On the web, a change swaps only the views of the records that it adds or removes, never the
other views, unless it reorders them.

The list stays compact, however many records there are. On Qt, it scrolls within itself and
takes the spare height of the page. Expanders in a list join in one box on the web, and are
a line apart on Textual.

[`src/examples/pipecatalogue.py`](../../src/examples/pipecatalogue.py) lists its pipes this
way, each with a Delete button.

## Menus

A `Menu` groups actions under a title in the window's menu bar, for example the commands
that act on a pipe. Its `ActionView` and `SeparatorAction` fields are its entries, in order.
Make the menu a field of the main view:

```python
from attrs import Factory

from composeui.core.view import ActionView, MainView, Menu, define_view


@define_view
class PipeMenu(Menu):
    reset_dimensions: ActionView = Factory(ActionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Pipe"
        self.reset_dimensions.text = "Reset Dimensions"
        self.reset_dimensions.shortcut = "Ctrl+r"


@define_view
class AppMainView(MainView):
    pipe_menu: PipeMenu = Factory(PipeMenu)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.pipe_menu.reset_dimensions.triggered.connect(self.reset_state)
```

- `triggered` emits when the user picks the entry, or presses its `shortcut`.
- A checkable entry (`is_checkable`) changes `is_checked` before `triggered` emits, so the
  callbacks see the new state.

Qt shows the menu in the menu bar of the window, as a `QMenu`. The web shows it as a
drop-down list in the page header. Browsers keep the Ctrl shortcuts, so a shortcut of Ctrl
and a letter or a digit becomes Alt+Shift: Ctrl+r becomes Alt+Shift+R. The web has no
equivalent for other shortcuts, such as Ctrl+Shift+s. Textual has no menu bar: an
entry with a `shortcut` is a key binding, which the footer lists. On Textual, the user
can't reach an entry without a shortcut.

The File menu is built in (see
[The File menu and picking a file](widgets.md#the-file-menu-and-picking-a-file)), and a
[`LanguageMenu`](translation.md) lets the user switch languages. In
[`src/examples/pipeform.py`](../../src/examples/pipeform.py), the Pipe menu resets the
dimensions.

## Toolbars

A `ToolBar` is a row of the actions that the user runs most, docked at the top of the window.
Its `ActionView` and `SeparatorAction` fields are its entries, in order. Make the toolbar a
field of the main view:

```python
from attrs import Factory

from composeui.core.view import ActionView, MainView, ToolBar, define_view


@define_view
class RunToolBar(ToolBar):
    run: ActionView = Factory(ActionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Run"  # names it, e.g. for a screen reader
        self.run.text = "Run"
        self.run.shortcut = "Ctrl+r"


@define_view
class AppMainView(MainView):
    toolbar: RunToolBar = Factory(RunToolBar)
```

- A click on an entry triggers its action.
- A checkable entry shows as pressed while it is checked.
- When code disables the toolbar, its entries are disabled too.

Qt docks the toolbar as a `QToolBar`. Textual shows a row of buttons at the top, above the
buttons of a router. The web puts its buttons in the page header, before the menus.

The `icon` of an action is the path of an image file. Qt and the web show it (see
[Web backend](running-the-app.md#web-backend)). A terminal shows the text. The app's code sets an
icon, so an icon is not study data: it is never saved, loaded, or reset.

## Sidebar

A `SidebarView` is a column of views beside the pages. It shows on every page, for example
a form that creates a record. Its view fields are its content, under its `title`. Make it a
field of the main view, not of its router:

```python
from attrs import Factory

from composeui.core.view import ButtonView, MainView, SidebarView, child, define_view


@define_view
class NewRecordSidebar(SidebarView):
    form: NewRecordForm = Factory(NewRecordForm)  # a FormView
    create: ButtonView = child(ButtonView, text="Create")


@define_view
class AppMainView(MainView):
    sidebar: NewRecordSidebar = child(NewRecordSidebar, title="New record")
    pages: Pages = Factory(Pages)
```

Qt docks the sidebar on the left of the window, where the user can't close or move it.
Textual shows it on the left of the content, and the web as a column on the left of the
pages.

The user retracts the sidebar and expands it again with a button that `toggle_text` names:

- On Qt and Textual, the button is an arrow in the header of the sidebar. A retracted
  sidebar leaves a narrow strip.
- On the web, the button is in the page header.

Code does the same with `is_expanded`, and reacts to the user's toggles through `toggled`.
Whether the sidebar is retracted is layout, not study data.

On a phone, the web shows the sidebar as a drawer over the page. The button in the header
opens it. A tap beside it, or Escape, closes it.

In [`src/examples/pipecatalogue.py`](../../src/examples/pipecatalogue.py), the form of the
sidebar adds pipes to the catalogue beside it.

## Dialogs

A `DialogView` is a modal message, or a confirmation with an accept button and a reject
button (`kind=DialogKind.CONFIRM`). It starts closed, and `open()` shows it.

Nothing waits for the answer, because a web request can't wait. Connect to `accepted` and
`rejected` instead. They fire once the dialog is closed.

```python
from attrs import Factory

from composeui.core.view import DialogKind, DialogView, MainView, define_view


@define_view
class ClearDialog(DialogView):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.kind = DialogKind.CONFIRM
        self.title = "Clear the form"
        self.text = "Every field will be emptied."
        self.accept_text = "Clear"  # "OK" otherwise; the other button is `reject_text`


@define_view
class AppMainView(MainView):
    confirm_clear: ClearDialog = Factory(ClearDialog)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.confirm_clear.accepted.connect(self.reset_state)
        # ... and something calls `self.confirm_clear.open()`, e.g. an action
```

Escape, or closing the window of the dialog, rejects a confirmation. It accepts a message,
which has only one answer.

A dialog is not study data: saving, opening, and New leave it alone.

Qt shows a `QMessageBox`, Textual a modal screen, and the web a modal `<dialog>`, wherever
the view is in the tree. In [`src/examples/pipeform.py`](../../src/examples/pipeform.py), Reset
Dimensions in the Pipe menu asks for a confirmation first.

### Form dialogs

A `FormDialogView` holds a form with OK and Cancel, for example to edit a record from its
Edit button. A subclass gives its form as its `form` field. Its `text` shows above the form:

```python
from attrs import Factory

from composeui.core.view import FormDialogView, define_view


@define_view
class EditPipeDialog(FormDialogView):
    form: PipeForm = Factory(PipeForm)  # a FormView, with its checks
```

- The user can't press OK while a check of the form fails. `is_accept_enabled` follows the
  checks as they run.
- Accepting runs every check first, even a check that the user hasn't triggered yet. The
  dialog stays open while a check fails. `FormView.check` runs all the checks, and
  `is_valid` tells whether they pass.
- The answer comes through `accepted` or `rejected`.
- The form keeps its values. The app reads them once the user accepts, or fills them before
  `open()`.

In [`src/examples/pipecatalogue.py`](../../src/examples/pipecatalogue.py), the Edit button of
each pipe changes the pipe in a form dialog.
