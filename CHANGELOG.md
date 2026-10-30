# Changelog

The notable changes of each release of ComposeUI. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow
[Semantic Versioning](https://semver.org/). Before 1.0, a minor version can break the API.

## [Unreleased]

### Added

- `MainView.loaded`, a signal emitted once the views and the model's data are in place: as
  the app starts, with the study of `-f` or a new one, and after New and Open. An app gives
  again there what a study doesn't hold, such as the source of a large table, which a load
  left as it was.
- `composeui.core.dashboard`, for shorter dashboard code: `DashboardView`, a wide main view
  without the File menu, and `bar_chart`, a bar chart as a view field's default.
- `Task.show_state`, which shows a task's loading, progress, or error in a label, and other
  views only once the task has a result.
- `CheckBoxMixin.shows`, which shows other views only while the box is checked.
- `CellWidget.file_path`, a file path in each cell of a table's column: typed, or picked
  with a "…" button. Qt and Textual open their file dialogs, and the web uploads the file.
- `ContentDialogView`, a dialog holding any view with OK and Cancel, such as a table to pick
  a file from. The app enables OK with `is_accept_enabled`, and a subclass can keep the
  dialog open on OK by overriding `accept`.
- `FilePathInputMixin.server_roots`, the folders of the server whose files the web's "…"
  button lists, instead of uploading a copy. The field holds the path of the file on the
  server. A typed path outside the roots gives `path` `None` on the web. Qt and Textual open
  their dialogs in the first root.
- `FolderPathInputView`, `RowFolderPathInputView` and `LabelRowFolderPathInputView`, a
  folder's path, typed or picked in a folder dialog. On the web, the path is typed, or picked
  among the server's folders with `server_roots`.
- `CellWidget.file_path(..., server_roots=...)`, a table's file path cells picked among the
  server's files, as a field's. On the web, a path typed outside the roots is refused: the
  cell keeps its text, and the status bar says why (`TableView.file_texts`).

### Fixed

- On Textual, a file or folder picker loading a folder no longer fails now and then with a
  `KeyError` on a style of its list. textual-fspicker read the styles from its loading
  thread while Textual applied them again; they are read on the app's thread.
- A large table of a `DataFrameSource` whose `id_column` is also one of its columns shows its
  rows. Its cells failed to read on Polars.
- A choice whose value is `None`, such as `{"All regions": None, "North": "north"}`, shows
  as selected when `value` is `None`, and its study saves it as that choice. A combobox
  showed nothing selected instead, on each backend.
- A job started before the main view shows, such as by `setup_model`, gives its result once
  the view shows. A job over before then gave it to no backend: a quick load stayed on its
  "Loading..." text.
- A chart shows the hovered values of a series of whole numbers, such as counts, as
  integers: `45280`, not `4.528e+04`, and `12`, not `12.00`. Qt and the web showed 4
  significant digits for every series. A series with other values still shows 4.
- A form row in another view than a `FormView`, such as a `LabelRowSliderView` in a
  sidebar, shows its label, its field, and its message, as a form shows them. No backend
  showed it, and nothing said why.
- A `FormView` shows its other views, such as a table or a row of buttons, in their place
  between its rows, also in a form dialog. Every backend left them out, and nothing said
  why.
- With reload on, an app that runs the changed code, then exits by itself soon after, such
  as one closing its window, isn't started again in a new process. The supervisor took its
  exit for a request to run the code anew.
- On the web, a click right after typing in a field sees the value typed, and Save or
  Save As saves it. The field posts its value as the click takes the focus, and the server
  could handle the click first.

## [0.1.0] - 2026-10-27

The first release on PyPI.

### Added

- Views as typed `attrs` classes, signals, models, and a `run` function that starts the app
  on the backend that the command line chooses.
- Three backends: Qt (the `pyside6` extra), Textual (the `tui` extra), and the web
  (the `web` extra, the default).
- Layouts, a status bar, menus, toolbars, inputs, forms and their checks, pages, tabs,
  resizable panes, a sidebar, dialogs, tables, large tables, trees, Markdown, charts, and
  street maps (Qt and the web).
- The state of the views saved to a study file and loaded from it. The file holds the
  version of its format and the app's `state_version`, and `migrate_state` upgrades an
  older one.
- Threads, SQLite models, CSV imports, translations, and tests of an app that need no backend.
- A skill for coding agents that write a ComposeUI app.
- `composeui.__version__`, the version of the installed package.

[Unreleased]: https://github.com/ehmoussi/composeui/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ehmoussi/composeui/releases/tag/v0.1.0
