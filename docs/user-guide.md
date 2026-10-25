# User guide

This guide shows how to build an app with ComposeUI. It explains each view and feature,
and what each backend shows. To install ComposeUI and write a first window, read the
[README](../README.md) first. To see the features in complete apps, read the
[examples guide](examples-guide.md). To change ComposeUI itself, read the
[technical guide](technical-guide.md).

[Building views](user-guide/building-views.md) is a complete app. The other examples show only the
part of an app that a feature needs. A class name with a comment, such as
`study: StudyTree = attrs.Factory(StudyTree)  # a TreeView`, stands for a view of your app of that
kind. A record type, such as `Run` or `Pipe`, stands for an `attrs` class of your app.

## Pages of this guide

- [Core concepts](user-guide/core-concepts.md)
  - [How ComposeUI maps to MVVM](user-guide/core-concepts.md#how-composeui-maps-to-mvvm)
  - [Views are reactive](user-guide/core-concepts.md#views-are-reactive)
  - [Signals inject arguments](user-guide/core-concepts.md#signals-inject-arguments)
- [Building views](user-guide/building-views.md)
  - [Define a view](user-guide/building-views.md#define-a-view)
  - [`child` or `Factory`](user-guide/building-views.md#child-or-factory)
  - [Lay out views](user-guide/building-views.md#lay-out-views)
  - [Forms and their fields](user-guide/building-views.md#forms-and-their-fields)
  - [Check a form](user-guide/building-views.md#check-a-form)
  - [Compose views from mixins](user-guide/building-views.md#compose-views-from-mixins)
  - [The main view](user-guide/building-views.md#the-main-view)
    - [The status bar](user-guide/building-views.md#the-status-bar)
    - [The app's icon](user-guide/building-views.md#the-apps-icon)
    - [Command-line options of your own](user-guide/building-views.md#command-line-options-of-your-own)
  - [Saving and loading state](user-guide/building-views.md#saving-and-loading-state)
- [Widgets](user-guide/widgets.md)
  - [Label](user-guide/widgets.md#label)
  - [Buttons](user-guide/widgets.md#buttons)
  - [Help on a form row](user-guide/widgets.md#help-on-a-form-row)
  - [Integer input](user-guide/widgets.md#integer-input)
  - [Date input](user-guide/widgets.md#date-input)
  - [File path input](user-guide/widgets.md#file-path-input)
  - [Slider](user-guide/widgets.md#slider)
  - [Progress bar](user-guide/widgets.md#progress-bar)
  - [Metric](user-guide/widgets.md#metric)
  - [Log message](user-guide/widgets.md#log-message)
  - [Expander](user-guide/widgets.md#expander)
  - [Tree](user-guide/widgets.md#tree)
  - [Markdown](user-guide/widgets.md#markdown)
  - [The File menu and picking a file](user-guide/widgets.md#the-file-menu-and-picking-a-file)
- [Organizing the window](user-guide/organizing-the-window.md)
  - [Pages](user-guide/organizing-the-window.md#pages)
  - [Tabs](user-guide/organizing-the-window.md#tabs)
  - [Resizable panes](user-guide/organizing-the-window.md#resizable-panes)
    - [Panes one above the other](user-guide/organizing-the-window.md#panes-one-above-the-other)
  - [A list of views](user-guide/organizing-the-window.md#a-list-of-views)
  - [Menus](user-guide/organizing-the-window.md#menus)
  - [Toolbars](user-guide/organizing-the-window.md#toolbars)
  - [Sidebar](user-guide/organizing-the-window.md#sidebar)
  - [Dialogs](user-guide/organizing-the-window.md#dialogs)
    - [Form dialogs](user-guide/organizing-the-window.md#form-dialogs)
- [Tables](user-guide/tables.md)
  - [A table of records](user-guide/tables.md#a-table-of-records)
    - [Sorting and filtering](user-guide/tables.md#sorting-and-filtering)
    - [Widgets in cells](user-guide/tables.md#widgets-in-cells)
    - [How cells and headers look](user-guide/tables.md#how-cells-and-headers-look)
  - [A large table](user-guide/tables.md#a-large-table)
    - [Order a large table](user-guide/tables.md#order-a-large-table)
    - [Cells, selection, copy, and export](user-guide/tables.md#cells-selection-copy-and-export)
    - [Rows in SQLite](user-guide/tables.md#rows-in-sqlite)
- [Charts](user-guide/charts.md)
  - [Kinds of chart](user-guide/charts.md#kinds-of-chart)
  - [Log axes](user-guide/charts.md#log-axes)
  - [Reference lines](user-guide/charts.md#reference-lines)
  - [Colors, fill, steps, and height](user-guide/charts.md#colors-fill-steps-and-height)
  - [What each backend draws](user-guide/charts.md#what-each-backend-draws)
  - [Clicks on a chart](user-guide/charts.md#clicks-on-a-chart)
  - [Report images](user-guide/charts.md#report-images)
- [Running work in threads](user-guide/threads.md)
  - [Reusable loading tasks](user-guide/threads.md#reusable-loading-tasks)
- [A SQLite model](user-guide/sqlite-model.md)
  - [Importing CSV data](user-guide/sqlite-model.md#importing-csv-data)
    - [CSV URLs](user-guide/sqlite-model.md#csv-urls)
- [Translating the app](user-guide/translation.md)
  - [Checking the catalogs](user-guide/translation.md#checking-the-catalogs)
- [Running the app](user-guide/running-the-app.md)
  - [Backends](user-guide/running-the-app.md#backends)
  - [Reloading the app on a change](user-guide/running-the-app.md#reloading-the-app-on-a-change)
  - [Web backend](user-guide/running-the-app.md#web-backend)
    - [How the web differs from a window](user-guide/running-the-app.md#how-the-web-differs-from-a-window)
    - [Serve the app to other users](user-guide/running-the-app.md#serve-the-app-to-other-users)
- [Using a coding agent](user-guide/coding-agents.md)
  - [Install the skill](user-guide/coding-agents.md#install-the-skill)
  - [Point the agent at the documentation](user-guide/coding-agents.md#point-the-agent-at-the-documentation)

```{toctree}
:hidden:

user-guide/core-concepts
user-guide/building-views
user-guide/widgets
user-guide/organizing-the-window
user-guide/tables
user-guide/charts
user-guide/threads
user-guide/sqlite-model
user-guide/translation
user-guide/running-the-app
user-guide/coding-agents
```
