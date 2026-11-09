# Changelog

The notable changes of each release of ComposeUI. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow
[Semantic Versioning](https://semver.org/). Before 1.0, a minor version can break the API.

## [Unreleased]

### Added

- `WebApplication.filter_patterns = False`, or the `COMPOSEUI_FILTER_PATTERNS` environment variable
  set to `off`, refuses the regular expressions of table filters. A crafted one can stop a deployed
  web app for a long time.
- `get_logger` gives an app a logger that writes as ComposeUI does and follows `--log` and
  `--debug`.
- `DimensionShape` shows a measurement in a `DrawingView`: a line with a tick at each end and a
  label, on Qt, Textual and the web. The ticks keep their size at any scale.
- `fill_color` on `Series`, `PolygonShape` and `CircleShape` gives a filled area a color other than
  its line's, on Qt, Textual and the web, and in a chart's image.
- `DrawingView` shows a diagram of lines, polygons, circles, arrows, and text on Qt,
  Textual, and the web, without an image. A new `shapes` list redraws it. The text and the arrow
  heads keep their size at any scale. A line has a `LineWeight`, and a text a `TextRole`.
- `is_filled` on `SliderView` and `FloatSliderView` turns off the accent color on the track up to
  the handle, on Qt, Textual and the web.
- `FloatSliderView`, with `RowFloatSliderView` and `LabelRowFloatSliderView`, picks a decimal
  number by dragging a handle on Qt, Textual and the web. Its steps are exact: three steps of `0.1`
  give `0.3`.
- `LabelView.role` (`TextRole`) says what a text is: a title, a subtitle, a caption, muted text,
  an error, a warning or a success. Each backend shows the role in its own way, and on the web a
  title and a subtitle are real headings.
- `grid_cell` declares a view field of a `GridView` on one line: its cell, its view, and the view's
  fields, such as `grid_cell((1, 0), ButtonView, text="Add")`.
- `ImageView` shows an image on Qt and the web: a file, bytes, or a Matplotlib figure
  (`show_figure`). The new `figureviewer` example redraws a figure as a slider moves. Textual shows
  its description, or the image with the `terminal-images` extra, on Python 3.12 or later, in a
  terminal that supports Sixel or Kitty graphics.
- `AllowedUrls` limits the URLs that `fill_from_url` and `open_csv_url` take from a user: the hosts,
  the schemes, and the redirects. They refuse any other URL before its request.
- `fill_from_frame`, from `composeui.core.dataframesource`, imports the rows of a dataframe into a
  `CSVSqliteTable`, such as a Parquet file that the app read with Polars or pandas. It works as
  `fill` does, with progress, rollback and the row class's checks, and it needs the `dataframe`
  extra. `CSVSqliteTable.fill_rows` imports rows from any iterable of dictionaries.
- `FileUploadView`, with `RowFileUploadView` and `LabelRowFileUploadView`, lets the user give the
  app a file on Qt, Textual and the web. Its `uploaded` signal gives an `UploadedFile`: the file's
  name, size, type and path. On the web, each session keeps its own copy until the view's next
  upload or `clear()`, once its jobs are over, or the end of the session. On Qt and Textual, the
  path is the user's own file.
- `MainView.min_free_disk` sets what uploads leave free on the disk, 1 GiB by default. Below it, the
  server stops writing the file, and the status bar says that it has no room. A full disk gives the
  same message.
- `MainView.max_upload_size` sets the largest file that a user can upload to the web app. It is
  5 MiB by default. The server refuses an upload's body of more than this size plus 1 MiB. A file
  over the limit stays in the browser, and the status bar says why. Before, a file far over the
  limit failed without a message. An upload goes to a file as it arrives, and the server moves this
  file, so a large upload takes no memory and no second copy, and doesn't block the session.
- The `composeui run app.py` command starts an app from a Python file, and reloads it on a change.
  A file that defines one `MainView` class needs no `run` call. A file with a model calls `run`
  with its model. The options after the file, such as `--backend qt`, go to the app. The
  `--no-reload` option goes before the file.
- Reactive methods: `@reactive`, from `composeui.core.reactivity`, marks a view method that
  ComposeUI runs again each time a view field that it read changes. The application runs it
  once at start-up. One event, such as the callbacks of one signal, runs each method once,
  in a fixed order. A method that sets a field that it reads raises `ReactiveLoopError`.
  `reactive_inputs(view)` lists what each method read in its last run.
  Once a reactive method exists, a write of a view field costs about one Python call more, and
  views build as fast as without one.
- `Task.start_latest(*args)` starts a run that replaces the run going on, for an input that
  changes quickly, such as a slider. It waits `debounce` seconds first (0.2 by default, or
  `jobs.task(work, debounce=...)`), and the result of a replaced run never shows.
- `CSVSqliteTable.indexes` holds the SQL script that creates a CSV table's indexes. Before, a
  `create` set in the table's class was lost without an error, so a CSV table had no direct
  way to declare an index.

### Changed

- `CheckBoxMixin.shows` and `Task.show_state` follow their inputs as reactive methods of the
  view that they change. In a signal's callbacks, the views that they show or hide change
  once the callbacks are done, with the reactive methods, not at once. `reactive_inputs`
  lists them as `shows` and `show_state`. An app that uses them records the reads of its
  view fields, as an app with a reactive method does.
- A list that a view holds, such as a map's `points` or a table's `rows`, can't change in
  place: `append`, `pop`, `x[i] = ...` and the like raise a `TypeError` that names the
  attribute. Such a change reached no renderer, so the screen kept the old list. Set a new
  list instead: `view.points = [*view.points, point]`, or `view.points += [point]`.

### Fixed

- A selection that a study restored stays when rows replace a source without rows, such as an empty
  `DataFrameSource` built before the data is loaded.
- `selection_changed` emits `[]` for rows that replace a selection of positions once they are
  ordered, also when a job orders them. A callback read the old order before.
- New `records` in a `ListSource` without an `id_field` clear a table's selection, as new rows in a
  `DataFrameSource` do, and `selection_changed` emits `[]`. The selection moved silently to the
  records now at those positions. A source of your own can do the same with `row_ids_scope`.
- A study opens without a filter that a `SourceTableView`'s source no longer takes, as it does on
  other tables. It raised an error before.
- A study saves and opens a record's `timedelta` field, as the text a cell shows. Saving one failed.
- A column of lists in a Polars or PyArrow frame no longer makes a large table's search fail. The
  search passes over it, and a filter or a sort on it does nothing.
- A new `frame` of a `DataFrameSource` whose columns have other types no longer makes a table's
  filter fail. A new frame without one of the source's columns is refused with a `ValueError`.
- A pandas column of `Decimal` values sorts and filters as numbers in a large table, as with Polars
  and PyArrow.
- New rows in a `DataFrameSource` without an `id_column` clear a table's selection, and
  `selection_changed` emits `[]`. The selection moved silently to the rows now at those positions.
- A duration column of a large table sorts by length, filters by a length such as `>1d 2h` or a
  number of seconds, and shows as `1d 2h 30m`, with each dataframe library. With Polars, such a
  column made any search of the table fail. A table of records edits a duration in the same format.
- A date filter on a dataframe's column with a time zone no longer fails. A date without a zone
  is the time in the column's zone, and a date with a zone is an instant.
- An empty cell of a pandas text or category column no longer matches a search or a filter for
  "none" or "nan" in a large table, and it sorts with the other empty cells.
- A log message no longer draws over a Textual app: from the start of the app, the messages go to
  `composeui.log`, or the file of `--log-file`, and the app shows the path when it exits.
- `--reload` shows a value changed in the code, such as the `shapes` of a `DrawingView`, instead of
  the value saved by the previous run. The other values stay as the user left them.
- `--reload` runs the changed code on every change of an app started as a script
  (`python app.py --reload`). Before, the second change failed, and the window kept the old code.
- A study whose archive holds a member's name that can't be decoded is refused as invalid. Before,
  opening it raised an uncaught error.
- A study keeps a date's UTC offset of less than a second on Python versions that read it as UTC.
- On Qt, a refresh that raises no longer leaves the widget's signals blocked, which cut the user's
  later edits off from the view. A widget blocked before a refresh stays blocked.
- A failed JSON save or a canceled CSV export keeps the previous file, and a canceled export no
  longer reports success. Before, the failure or the cancel destroyed it.
- A study whose archive marks a member as patched data or as strongly encrypted is refused as an
  invalid file. Before, opening it raised `NotImplementedError`, and the web answered with a server
  error.
- On Qt and Textual, setting a radio group's value to `None` clears its selection, as the view holds
  no choice.
- On Textual, a job that reports progress inside a SQLite transaction no longer deadlocks when its
  callback reads the same model: a job's results are delivered without waiting for them.
- On the web, an upload whose name has only letters outside ASCII before its extension, such as
  `データ.csv`, is no longer refused for its type.
- Chart image exports that overlap, such as two web sessions saving a chart at once, no longer
  corrupt Matplotlib's global settings. Each export keeps its own, one at a time.
- A closed web session no longer runs the callbacks of its jobs, whose progress or outcome arrives
  after the close.
- A CSV row without a value for a required field, such as a short row, is refused. Before, a text
  field stored the text "None", and a boolean field stored false.
- Check-all and a Textual row edit of several cells stay on their records when a `cell_edited`
  callback sorts, replaces or removes the rows. Before, the next edit could land on another record.
- A web session whose setup fails closes the model it built. Before, each failed request leaked one
  model's resources.
- On the web, an upload refused because its file path field is disabled no longer deletes the copy
  that the field holds.
- `DataFrameSource` with an `id_column` keeps the frame's order for rows with equal cells, as
  `ordered_ids` promises. Before, it ordered them by ID.
- A disabled or hidden web control refuses the events of a stale or crafted post, as a button does,
  and a disabled tab can't be selected.
- On the web, a session that ends while a job writes to its `SqliteModel`, such as a session that
  expires during a long import, no longer crashes the server. `SqliteModel.close` closed the
  connection during the job's statement, which could end the process and every session in it.
  `close` still returns at once: the connection now closes when the write's transaction ends. The
  end of a session also cancels its jobs.
- `CSVSqliteTable` imports a CSV file about twice as fast when dates repeat in it. The 1,028,136
  rows of the Uber pickups example take about 10 s, down from about 20 s, with the same checks on
  each row. An import holds more memory for its dates, about 5 MiB for this file, and frees it
  at its end.
- The web server answers a post sent twice with nothing: it no longer repeats its effects, or lets
  later posts run before the original ends.
- On Textual, the date field's calendar opens on the first and last valid dates, and its keys stop
  there. Before, it crashed on December 9999.
- In the SQLite Uber pickups example, moving the hour takes about 0.3 to 0.4 s on the web, down
  from about 1.7 s, and sorting its table about 70 ms, down from about 860 ms. An index on the
  hour replaces a scan of every row. A study saved before the index opens through a migration.
- When Qt reloads in place and the state can't be saved, the window keeps the previous code, and
  later changes still reload. Before, the reload stopped for good.
- On Qt, closing a page of many widgets no longer freezes the app for seconds. Freeing a
  page of 1,000 rows took about 1.6 s, and four times as long for twice the rows. It now takes
  about 0.2 s, and about twice as long for twice the rows. A widget's Qt connections now hold
  its views weakly, as on Textual and the web: an open window no longer keeps alive the views
  that the app dropped.
- On Textual, a callback handed to the app's thread runs once when it raises `RuntimeError`. Before,
  it ran a second time, on the worker's thread.
- A web session restored by `--reload` owns its uploads, and deletes them when it closes or expires.
  Before, they stayed on the disk.
- On the web, a job's `finished` callback can start another job or task. It raised
  `CalledInJobError`: the web hands a job's outcome over in the job's thread, which took the
  callback for the job's own function.
- A `DataFrameSource` sorted by a text column keeps its empty cells, "" and missing ones
  alike, in the frame's order, as `ListSource` and `SqliteSource` do. Before, "" came first.
- A job dropped by New or Open can't write into the study that replaced its own, and a web session's
  uploads stay until every worker that may read them has ended.
- On Textual, a form or message dialog that the app closes while another dialog covers it no longer
  comes back as a modal that Escape can't remove.
- On the web, a download whose `export_filename` holds a control character no longer fails:
  the server refused its header. A quote, a backslash or a "/" in the name no longer goes
  into the header as it is. It broke the name that the browser shows.
- On the web, a chart, map or calendar whose library failed to load asks for it again on the page's
  next change, without a full reload.
- Opening a damaged study no longer fails with an error that the app doesn't catch. Its
  archive may place its directory or its files before the file's start, or ask for a newer
  zip version. The app now refuses such a study as any invalid one: "it isn't a valid ...
  file".
- On Textual, the shortcut of a disabled action does nothing. Before, it still ran the action, such
  as a disabled New.
- On the web, an answer that arrives late no longer overwrites a fragment that a newer answer
  already showed.
- On the web, a click on a chart whose pointer moves a little, up to 3 pixels, is a click
  again: `clicked` emits it. uPlot took any move for a drag. It lost the click, and zoomed
  the chart into the pixels that the pointer moved across.
- A `RecordTableView` edits a field of `decimal.Decimal`, or of an enum of numbers. The
  table refused every edit of such a cell, even of the text that the cell showed. An enum's
  cell now takes a member's value, as the cell shows it, and an enum that is also a `str`
  gets its member, not a plain `str`. A study saves a `Decimal` as its exact text: saving
  one failed.
- The timer of an old status message no longer clears a newer message when it was already firing.
- The catalog check finds a translation that drops or adds a `{}` value, or a value in a
  format such as `{count:{width}}`. It took each `{}` for the same one, and left out the
  values in a format. It no longer tells `{name.real}` and `{name}` apart: both format
  `name`.

## [0.3.0] - 2026-11-02

### Added

- `TextAreaView`, a field for several lines of text, and its form rows `RowTextAreaView`
  and `LabelRowTextAreaView`. The pipe form example has a comment in one.
- `base_folder` on file, folder and save path fields: the folder that a relative path starts
  from, rather than the process's working folder. `path` and the check of `server_roots` read
  the text from it, a picked path inside it shows relative to it, and the "…" button opens in
  it while the field is empty.
- `CellWidget.folder_path` and `CellWidget.save_path`, a folder's path and a path to save a
  file to in a table's cells, beside `CellWidget.file_path`. The three take `base_folder`.
- `CellWidget.path_by`, a path column whose widget is that of each row's kind, the text of
  another cell of the row: a file, a folder, or a file to save. When the user changes the
  kind, the widget follows. `TableMixin.cell_widget(row, column)` gets a cell's widget. The
  study inputs example (`studyinputs.py`) lists a study's files this way.
- `MainView.write_file(field, write)`, which asks before the app saves over a file that
  exists, such as a path typed in a save path field: it calls the app's `write` at once, or
  only once the user agrees to replace the file. When the user already agreed in the field's
  picker (`is_replace_agreed`), it doesn't ask again. The study inputs example saves a
  summary of its table this way.
- `DialogButtonView`, a button of a form or content dialog's own between Cancel and OK, such
  as Apply: it leaves the dialog open, or closes it with `closes=True`, and waits for the
  dialog's checks unless `checks=False`. `add_check` adds a check of the dialog's own, about
  any view it shows: its message stays in the dialog, and OK waits for it. `accepting` fires
  on OK while the dialog is still open, and a refusal in the dialog's `refusing` shows in
  the dialog and keeps it open. The base of the two dialogs is `OkCancelDialogView`. The
  pipe catalogue's Edit dialog has Apply, checks that no other pipe has the name, and shows
  why the database refuses a pipe.
- `OkCancelDialogView.show_message`, a message of information above a dialog's buttons, such
  as "Saved" after Apply: it doesn't stop OK, and goes on the next click, check or opening.
  The pipe catalogue's Apply says so in its dialog.

### Changed

- The web sends only the shown page of a `Router`. A change on another page waits until that
  page shows, so an app's other pages no longer add to each page load and response.
- The web sends only the shown tab of a `TabView`. Its views arrive when the user picks the
  tab.
- Qt builds a page of a `Router` the first time it shows, and the views of a tab of a
  `TabView` the first time the tab shows. An app with many pages or tabs starts as fast as
  one with a few. A page or a tab shows every change made before it was built. Its dialogs
  open from any page, and the title and state of a tab show on its tab at once. Until then,
  the views of the page or tab have no Qt widget (`renderer` is `None`).

## [0.2.0] - 2026-10-30

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
- `SavePathInputView`, `RowSavePathInputView` and `LabelRowSavePathInputView`, the path of a
  file to save, typed or picked in a save dialog, the first extension added to a name that
  has none. The user agrees to replace a file that exists (`confirms_overwrite`). On the
  web, the path is typed, or picked in the server's folders with `server_roots`.
- `FolderPathInputView`, `RowFolderPathInputView` and `LabelRowFolderPathInputView`, a
  folder's path, typed or picked in a folder dialog. On the web, the path is typed, or picked
  among the server's folders with `server_roots`.
- `CellWidget.file_path(..., server_roots=...)`, a table's file path cells picked among the
  server's files, as a field's. On the web, a path typed outside the roots is refused: the
  cell keeps its text, and the status bar says why (`TableView.file_texts`).
- `TableView.row_activated`, which emits a row's index when the user opens it with a double
  click or Enter, as a large table's `row_activated` emits its id. A double click that edits
  a cell, or clicks its button or link, doesn't open the row.
- `ConsoleView`, plain text that the app adds to as it comes, such as a process's output:
  `append` adds text, "\r" starts a line again, and the view keeps the last `max_lines`
  lines. It scrolls to its end unless the user scrolled up. On the web, a change sends only
  the new lines.
- `current_backend()` and `renders(view_type)` in `composeui.core.application`: the views
  that the app builds know its backend, and whether it shows a kind of view, such as a
  `MapView`, which Textual doesn't show.
- `Task.disables` and `Task.cancel_with`: the views disabled while a task runs, and the
  buttons or actions that cancel its run, enabled only until it is asked to stop. They
  follow every start and outcome. `Task.is_canceled` tells a run asked to stop.
- A console saves its text to a file: a "Save output…" button on Qt, the key `s` on
  Textual, and a download link on the web. `ConsoleView.export_text(path)` writes it, and
  `export_filename` names the file at first.
- A console copies its whole text to the clipboard: a "Copy all" button on Qt and the web,
  and the key `c` on Textual.
- A console searches its text: a search field on Qt and the web, `/` on Textual. Its
  matches are highlighted, and a count says which one is current. New lines keep the
  current match. `find_in_lines` finds them as the search does.
- A console removes the escape sequences of a terminal, such as ANSI color codes, from its
  text. With `ConsoleView.ansi_colors`, it shows their colors and styles on every backend
  (`TextStyle`, `line_styles`). Before, their characters showed in the text.
- A large table (`SourceTableView`) opens a row on the web too: a double click or Enter
  emits its id with `row_activated`, as on Qt and Textual.

### Changed

- `Task.cancel` emits `changed` when it cancels a run, so a `changed` callback can show that
  the run is stopping. Called in a job's function, it raises `CalledInJobError`, as
  `Task.start` does: call it on the main thread.

### Fixed

- With reload on, an app that runs the changed code, then exits at once, is no longer started
  again now and then. When the app acknowledged the change and exited between two of the
  supervisor's looks, the supervisor took the exit for a request to run the code anew.
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

[Unreleased]: https://github.com/ehmoussi/composeui/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/ehmoussi/composeui/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ehmoussi/composeui/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ehmoussi/composeui/releases/tag/v0.1.0
