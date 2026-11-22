# Running the app

An app starts on one backend. In development, it reloads the changed code. On the web, it serves
each browser its own session.

## Backends

`run(MainViewClass)` starts the app with the backend that `--backend` names: `qt`,
`textual`, or `web`. The web is the default. Each backend needs its extra:

| `--backend` | Extra | Shows the app |
| --- | --- | --- |
| `qt` | `pyside6` | In a window |
| `textual` | `tui` | In a terminal |
| `web` | `web` | In a web page |

Without `--backend`, the `COMPOSEUI_BACKEND` environment variable picks the backend. An
app can change its default with `run(MainViewClass, default_backend=RendererType.QT)`.

`run` imports only the backend that you choose. Without the extra of that backend, `run`
stops, and says which extra to install, for example `pip install "composeui[web]"`. `run`
leaves the rest of the command line to the app (`--help` lists it). To always start one backend,
build its application yourself, for example `QtApplication(build_main_view=HelloMainView).run()`.

Every application takes a function it can call without arguments to build the main view.
On the web, it calls the function for each new session. If the main view's constructor needs
arguments, pass a function that supplies them, as in
[Saving and loading state](building-views.md#saving-and-loading-state).

- **In development,** `--reload` runs the changed code each time that you save a Python
  file. See [Reloading the app on a change](#reloading-the-app-on-a-change).
- **On the web,** each browser gets its own session, and the server protects the pages from
  other sites. Read [Serve the app to other users](#serve-the-app-to-other-users) before
  other people use the app.

### The composeui command

The `composeui run` command starts an app from a Python file, and reloads the app on a change. The
file needs no `run` call:

```python
from composeui.core.view import LabelView, MainView, child, define_view


@define_view
class HelloMainView(MainView):
    label: LabelView = child(LabelView, text="Hello")
```

```bash
composeui run hello.py                 # the web, reloading on a change
composeui run hello.py --backend qt    # what follows the file goes to the app
composeui run hello.py --help          # lists the app's options
composeui run --no-reload hello.py     # the command's own option goes before the file
```

The command runs the file as `python hello.py` does, so `__name__` is `"__main__"`. Then:

- **When the file starts an app,** for example with `run`, that app runs. A file with a model
  starts its app in this way: `run(HelloMainView, build_model=HelloModel)`.
- **When the file starts no app,** the command starts the `MainView` class that the file defines.
  A class that the file only imports does not count. With no class or with several, the command
  stops and says why. With several, call `run` with one of them.

The command reloads the Python files under the current folder, as `--reload` does (see
[Reloading the app on a change](#reloading-the-app-on-a-change)). The app of a file outside that
folder starts, but it does not reload, and the command logs a warning.

Reloading is for development. Before other people use the app, read
[Serve the app to other users](#serve-the-app-to-other-users).

`composeui translations app.py` checks the app's translation catalogs against its code. See
[Checking the catalogs](translation.md#checking-the-catalogs).

### Adapt the views to the backend

The app knows its backend before it builds its main view. So the views can adapt to it as
they are built:

- **`renders(view_type)`** tells whether the backend shows views of that type. For example,
  Textual shows no `MapView`, and an app can show a table of the points instead. Without
  it, a view that the backend does not show is left out, with no error.
- **`current_backend()`** gives the backend, a `RendererType`, for what depends on it in
  another way, such as a hint that names a mouse action.

Prefer `renders`: its answer stays right when a backend adds a renderer. Both come from
`composeui.core.application`.

```python
from composeui.core.application import current_backend, renders
from composeui.core.registry import RendererType
from composeui.core.view import LabelView, MainView, MapView, TableView, child, define_view


@define_view
class PickupsView(MainView):
    hint: LabelView = child(LabelView)
    map: MapView = child(MapView)
    table: TableView = child(TableView, headers=["Latitude", "Longitude"])

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # a backend that draws no map shows a table of the points instead
        self.table.is_visible = not renders(MapView)
        if current_backend() is RendererType.TEXTUAL:
            self.hint.text = "Select a row, then press Enter to open it."
        else:
            self.hint.text = "Double-click a row to open it."


main_view = PickupsView()  # built outside an app, e.g. in a test: no backend
assert main_view.table.is_visible
```

Before an app is built, for example in a test that builds the main view itself,
`current_backend()` is `None` and `renders` is `False`.

## Reloading the app on a change

Use `--reload` for development, on every backend: the app runs the changed code when a
Python file under the current folder changes. The web restarts its server (see
[Web backend](#web-backend)). On Qt and Textual, the process that you start does not show
the app. That process runs the program again in a child process, with the same command
line, and the child shows the app.

On Qt:

- **On a change of the app's code,** the window stays open, at its place and size. The app
  saves the study (the view state, and the data of the model). Then it runs the program
  again in the same process, with the program's modules imported again, and shows the new
  main view in the window. The new main view opens the study, and keeps its study file and
  the language shown.
  When the saved state no longer fits the changed views, for example after you rename a
  field, the new main view starts as the app starts.
- **When the changed code fails,** for example on a syntax error, the window keeps the
  previous code, and the error is logged. The next change runs the code again.
- **On a change of ComposeUI's own code,** the app saves the study and stops, and a new
  child process starts and opens the study. Its window opens again. A running app cannot
  import ComposeUI again, because its objects keep the old classes. An app that does not
  answer within 5 seconds, for example while it is busy, is terminated, and its state
  since the previous change is lost. While a dialog is open, the app runs the changed code
  once it closes.
- **When you close the window,** the program ends.

On a change of the app's code, the app builds a new model before it closes the previous
one. The previous model stays open until the new main view shows, because the window keeps
the previous code if the changed code fails. So for a moment, two models are open. Most
models allow it: the SQLite model, for example, works on its own copy of the data. A model
that takes something only one user can hold, for example a locked file, a network port, or
an instrument's connection, cannot: the new model fails to open it while the previous model
holds it. Then every change fails as the changed code does, and the window keeps the
previous code. For such a model, start the app again yourself after a change.

On Textual, the app saves the study and exits on every change, and a new child process
starts and opens the study. So the terminal shows the app again as you left it, with the
same study file and language. Quit the app, for example with Ctrl+Q, to end the program.

On every backend, the study brings back the values that you left in the app. A value that you
change in the code goes first: when the initial value of a field changes, the field takes the new
value, for example the `shapes` of a `DrawingView`. The other fields keep their values. Only the
values that the view class sets count. A value that a function sets after it builds the main view
does not count, and a value that a callback computes does not change until the callback runs. To
show such a value again, connect the callback to the `loaded` signal of the main view.

The program runs again on every change, so code that it runs at the start, such as a
log's setup, runs again too. Start the program with `composeui run`, as a script, or with `-m`,
for example `uv run python -m examples.pipeform --backend qt --reload`. With the `reload` extra
(`watchfiles`), the system reports the changes. Without it, the backends check the files
at a fixed interval. They also check them for a project on a Windows drive under WSL
(`/mnt/c/...`), as the system does not report those changes. Set
`WATCHFILES_FORCE_POLLING` to choose for the web yourself.

## Logging

ComposeUI writes its log messages to the standard output, with the date and time. Call `get_logger`
with a name to write the messages of your app in the same way:

```python
from composeui.core.application import get_logger

LOGGER = get_logger("myapp")


def save_results() -> None:
    LOGGER.debug("Writing the results")
    LOGGER.info("Results saved")
```

When the app runs, it shows the `info` messages and above. These options of every app show more:

| Option | Shows |
| --- | --- |
| `--log` | The `debug` messages of ComposeUI and of the loggers of `get_logger` |
| `--log-signals` | Each signal that is emitted |
| `--log-reactivity` | Changed inputs, how many reactions watch them, and what caused each timed run |
| `--debug` | All of the above |

Use `--log-signals` and `--log-reactivity` together to trace both. See
[Debug a method's inputs](reactive-methods.md#debug-a-methods-inputs) for what the trace shows.

The result of `get_logger` is a standard `logging.Logger`. Add a handler to it to write its messages
to a file too.

Textual draws the app on the terminal. So while a Textual app runs, from its start, ComposeUI writes
these messages to `composeui.log` in the current folder. Use `--log-file FILE` to choose another
file. ComposeUI creates the file with the first message, and shows its path when the app exits. At 5
MiB, the file starts again, and the previous content moves to `composeui.log.1`.

The app refuses to start with a `--log-file` that it cannot write. If it cannot write
`composeui.log`, the app starts, shows a warning, and does not keep the messages. ComposeUI does not
change a handler that your app adds: a handler that writes to the terminal draws over the app.

## Web backend

The web backend serves the views as a web page instead of a window.
`run(HelloMainView)` serves http://127.0.0.1:8000. Use `--host` and `--port` to change
the address. `WebApplication(build_main_view=HelloMainView).run()` does the same.

The server renders the pages and updates them with [htmx](https://htmx.org/). When the user
edits a field, the page posts it. The response swaps in every part of the page that changed,
such as the status bar. It never swaps the field that the user types in.

The app itself serves the styles ([daisyUI](https://daisyui.com/) on Tailwind), htmx, and
the scripts of charts, calendars, and maps. These assets work offline.
[Street-map tiles](maps.md#tiles-and-network-access) still need internet access unless
`MapView.tiles` is `False`. An application's own data downloads also need their data source.

For a fuller example, see [`src/examples/webhello.py`](../../src/examples/webhello.py)
(`uv run python -m examples.webhello`), and `pipeform.py` with `--backend web`.

### How the web differs from a window

- **One app state per browser.** A signed session cookie gives each browser its own main
  view. The tabs of one browser share it. A tab still on a page of an ended session, such as
  one from before the server restarted, reloads when the user acts on it.
- **Each session wires its own views.** Connect the signals in the views'
  `__attrs_post_init__`, as the quickstart does: each session builds its views, so each gets
  its connections. Two other places also run once per session:
  - `app.connect(view=..., signals=[...])` records a connection on `app.main_view`, a
    template that no browser shows. The app replays it on the main view of every new
    session, and the callback gets the `view` and `main_view` of that session.
  - `WebApplication.setup_session(main_view)` runs for the main view of each new session.
    Override it in a subclass.
- **Models are per session too.** `run(..., build_model=..., setup_model=...)` builds one
  model per session. `WebModelApplication` takes the same arguments. `setup_model` wires the
  model to its main view, and callbacks that ask for `model` get the model of their session.
  Do not share a model between browsers. Each browser sees only what its own requests
  return, so the other browsers would show stale views.
- **Save and Open** download the state as a file and upload a file. The File menu is in the
  page header. Its shortcuts use Alt+Shift (Alt+Shift+S saves), because browsers keep the
  Ctrl shortcuts for themselves. A study can be at most 5 MiB, and a notification says when a
  file is too large. Open uploads the file, then asks before it loses the unsaved changes (see
  [Unsaved changes](building-views.md#unsaved-changes)).
- **Uploads have a limit that the app sets.** A user can upload a file of at most 5 MiB by
  default. The limit applies to a `PickFileAction`, a file path input, a table's file path
  cell, and a file upload. For an upload of several files, it limits their size together. A
  main view
  sets another limit in `max_upload_size`, in bytes, such as `max_upload_size = 200 * 1024 *
  1024`. A notification says when a file is too large, and the page does not send that file.
  While an upload arrives, the server writes it to a file in the system's temporary folder, and
  then moves this file without another copy. The `TMPDIR` environment variable sets this folder
  on Linux and macOS. Raise the proxy's limit too (see
  [Deploy behind nginx](#deploy-behind-nginx)).
- **Uploads leave room on the disk.** A main view's `min_free_disk`, in bytes, is what uploads
  leave free in that folder: 1 GiB by default. Below it, the server stops writing the file, and
  a notification says that the server has no room. On a small disk, such as a small container, set
  a lower value, or the server refuses every upload. The server checks the free space, not what
  each user holds: one user can take the room down to this limit, and block the uploads of the
  others until that user's session ends. To keep uploads away from other data, point `TMPDIR` at
  a disk of its own. A full disk gives the same message. Open does not check it: a study is small.
- **`--reload` restarts the server when a Python file under the current folder
  changes.** Use it for development. The new server process runs the program again (the
  script, or the `-m` module) with the same command line, to build its app again. The
  sessions stay: the stopping process saves each session's study (the view state, and the
  data of the model), with its study file and language. The next process opens it when
  the session's browser comes back. The page asks the server every second whether it
  restarted, and reloads by itself once it did, so it shows the changed code as you left
  it. When the saved state no longer fits the changed views, the session starts as a new
  one does.
- **Pages have their own address.** With a router (see [Pages](organizing-the-window.md#pages)),
  each page is at `/<route>`, and `/` sends the browser to the first page. The toolbar of the pages
  is in the header. When the user changes pages, the browser's history gets the new address. So
  back, forward, bookmarks, and reloads land on that page. A route cannot be `icon`, `jobs`,
  `reload`, `state`, `static`, or `widget`, because the backend uses these addresses. An
  address that is no page's gives a 404 error, not the first page.
- **Icons** are the image files that actions name (`action.icon = "icons/run.svg"`, the
  path that Qt reads). The backend serves them. An SVG icon is drawn in the color of the
  text, so it follows the light and dark themes: only its shape counts, as with a Lucide or
  Material icon. PNG, JPEG, GIF, WebP, and ICO files show as they are.
- **No push from the server.** The page changes in response to the user's own actions, with two
  exceptions. A status bar message clears itself after its timeout. While
  [jobs](threads.md) run, the page asks every 300 ms for the
  changes from their results.

### Serve the app to other users

Read this section before other people use the app, on a network or behind a reverse proxy.

- **No login.** The app has no users or passwords: anyone who reaches its address uses it.
  Before you give it an address that other people can reach, restrict the access in front
  of it, for example with a password in the reverse proxy (see
  [Deploy behind nginx](#deploy-behind-nginx)).
- **Single process only.** The sessions live in the memory of one server process. A restart
  starts them all over. The server signs the session cookie with a key that it makes when it
  starts. So after a restart, each browser gets a new, empty session, and the work that its
  user did not save is lost.
- **Sessions have limits.** You can change each limit (see
  [Change the server's limits](#change-the-servers-limits)). The server drops a session after
  an hour without use (`session_ttl`). It keeps at most 1000 sessions at a time
  (`max_sessions`). When it is full, a new browser gets an error (503) until a session ends,
  and the open sessions keep working. A session doesn't end while a request, such as a large
  download, is in progress. At most 8 files that a [`StreamContent`](widgets.md#large-files)
  writes are sent at once (`max_download_streams`), and 2 for one session
  (`max_session_download_streams`). A server that stops waits 5 seconds for the requests in
  progress (`shutdown_timeout`), then ends them.
- **Idle sessions can wait on disk.** Set `session_idle`, in seconds, for example
  `WebSettings(session_idle=300.0)`. The server then saves each session that is idle for that
  long to the system's temporary folder, and frees its memory. Its next request
  opens it again, and its page reloads on the same address: the action of that request is
  lost, and the user does it again. A link that downloads, such as a table's CSV or a chart's
  image, fails until the page reloads. The session keeps what a study keeps. It also keeps its
  study file, its language, the uploads of its path fields, and the `SESSION` fields (see
  [Saving and loading state](building-views.md#saving-and-loading-state)). What a callback set
  and a study doesn't hold, such as a label's text, an image or a table's `cell_styles`, comes
  back only if the app gives it again on `loaded`. Sessions on disk don't count in
  `max_sessions`. At most 10 000 are on disk (`max_saved_sessions`): past it, idle sessions stay
  in memory. A session on disk ends after `session_ttl` too, and the server removes the sessions
  on disk when it stops.
- **A session stays in memory while it holds what it can't save.** It stays while:
  - a job runs, or a request is in progress;
  - the page has a file of `MainView.download` to fetch;
  - a dialog is open;
  - an upload view holds a file;
  - a large table shows a source that the app gave other than on `loaded`, for example from a
    file that the user chose (a source given on `loaded` comes back as the session wakes);
  - a console holds text;
  - `MainView.can_hibernate` returns False. Override it when a session holds something that its
    views' state and its model's data don't, for example an object that a callback built. A
    study saves neither the attributes of a view that are not fields nor the variables of a
    callback: a session that wakes doesn't have them.
- **Set `session_idle` when many sessions stay idle.** In memory, a session takes what its views
  and its model hold: about 0.4 to 1 MiB for an app of 20 pages without data. On disk, it takes
  about 83 KiB. With `session_idle`, the server's memory follows the users active in the last
  `session_idle` seconds, not all the open sessions. The first save costs a few MiB once, and
  the saves make some requests slower. So `session_idle` pays off from a few dozen idle
  sessions, for example in a public app, or when users leave their tab open. With a few users,
  keep it at `None`. The [benchmarks](../../benchmarks/README.md#the-long-running-benchmark) give
  the measures.
- **Requests have a size limit.** The server refuses a request body larger than 6 MiB (413) before
  it reads it. A file upload's request can be `max_upload_size` plus 1 MiB.
- **A crafted regular expression can stop the server for a long time.** A table's filter accepts
  regular expressions, and Python can take minutes or more on a crafted one. All the sessions
  wait until it ends. To refuse them, set `WebSettings(filter_patterns=False)`, or set the
  environment variable `COMPOSEUI_FILTER_PATTERNS` to `off`. The `.*` toggle of the filter
  editor then goes away, and a filter between slashes shows an error. A saved filter of this
  kind is dropped when it loads, and an app's own code that sets one gets a `FilterError`.
  `filter_patterns` applies to the web only, and the variable to every backend. The values
  `false`, `0` and `no` also refuse them. An app does not start with a value that it cannot read.
- **Only the app's own pages change a session.** The server refuses a POST from another
  origin (403), as protection against cross-site request forgery. Another origin includes
  another port of the same host. The browser tells the origin in its `Sec-Fetch-Site`,
  `Origin`, or `Referer` header. A request without any of them is refused. Behind a reverse
  proxy, keep these headers and the `Host` header as the browser sent them.
- **No page of the app shows in a frame,** not even in a frame of the app's own site. This
  stops another site from showing the app in a hidden frame to get the user's clicks
  (clickjacking). Every response sends `frame-ancestors 'none'` in its
  `Content-Security-Policy`, and `X-Frame-Options: DENY`.
- **The page runs only the app's own script files.** The same `Content-Security-Policy`
  refuses inline scripts and code that htmx would evaluate. If a text ever got past the
  escaping, the browser would not run it. The page loads scripts, styles, and images only
  from the app. It allows inline `style` attributes, which run no code.
- **Other headers.** Every response also sends `X-Content-Type-Options: nosniff`, so the
  browser keeps to the content type of each file, and `Referrer-Policy: same-origin`, so the
  addresses of the app are not sent to other sites.

### Change the server's limits

Give the limits of the web server to `run` as a `WebSettings`. Each field that you leave out
keeps its default. Qt and Textual ignore the settings, so the same app runs on every backend.

```python
from composeui.core.application import WebSettings, run
from composeui.core.view import MainView, define_view


@define_view
class HelloMainView(MainView):
    pass


if __name__ == "__main__":
    run(
        HelloMainView,
        # for users who keep the page open all day: their sessions wait on disk while idle
        web_settings=WebSettings(session_ttl=8 * 3600.0, session_idle=300.0),
    )
```

The API reference of [`WebSettings`](../api/application.md) describes each field, and when to
change it. A `WebApplication` or a `WebModelApplication` takes them as `settings=`.

### Change the look of the web app

Give the look of the web app to `run` as a `WebStyle`. Its `theme` sets the colors, the
corners, the borders, and the font. Its `stylesheets` add CSS rules of your own, from a
`folder` that holds them with their fonts and images. Qt and Textual ignore the style.

```python
from pathlib import Path

from composeui.core.application import run
from composeui.core.view import MainView, define_view
from composeui.core.webstyle import Palette, Theme, WebStyle


@define_view
class StudioMainView(MainView):
    pass


if __name__ == "__main__":
    run(
        StudioMainView,
        web_style=WebStyle(
            theme=Theme(
                light=Palette(primary="#0b5cad", primary_content="#ffffff"),
                dark=Palette(primary="#6ea8ff", primary_content="#0a1a2f"),
                radius_field="0.125rem",
                radius_box="0.25rem",
                font='"Inter", sans-serif',
            ),
            folder=Path("style"),
            stylesheets=("studio.css",),
        ),
    )
```

- **The theme.** A `Palette` holds the colors of the light theme or of the dark theme, each
  `#rrggbb` or `oklch(L C H)`. A `*_content` color is the text on its color, such as a primary
  button's text on `primary`. Each value that you leave out keeps ComposeUI's. The header's
  Theme menu still picks Light, Dark, or the browser's preference, and the charts take their
  colors from the theme.
- **Readable colors.** When a palette sets a text color or its background, the two must have a
  contrast of at least 4.5:1, the WCAG AA level for text. If one of the two is left out,
  ComposeUI's color is used for it. A pair below 4.5:1 raises `ValueError` and names the two
  colors.
- **The stylesheets.** The page loads them after ComposeUI's stylesheet and the theme, in their
  order, so their rules win. The server serves `folder` at `/style/files/`. A stylesheet names a
  font or an image of the folder by its relative path, such as `url("fonts/inter.woff2")` in an
  `@font-face` rule. The server serves no hidden file, no file outside the folder, and only
  stylesheets, fonts, and images.
- **The checks at start.** The page's policy blocks files from other addresses. So the server
  refuses to start when a stylesheet is missing, uses `@import`, or names in `url(...)` an
  address or a file that the folder doesn't serve. List each stylesheet in `stylesheets`
  instead of importing it. A stylesheet that you edit while the server runs shows at the next
  page load, and the server checks it again when it starts again.
- **The parts to select.** Select a part of the page by its `data-cui` attribute, such as
  `[data-cui="header"] { border-bottom-width: 4px; }`. ComposeUI keeps these attributes. Its
  classes and the rest of its markup are not part of the API.

These are the parts that carry a `data-cui`:

| `data-cui` | Part of the page |
| --- | --- |
| `header` | The header, with the brand, the pages' tabs, the toolbars, and the menus |
| `brand` | The app's icon and title, in the header |
| `page_tabs` | The tabs of the router's pages, in the header |
| `sidebar` | The sidebar |
| `content` | The page's column, under the header |
| `card` | The box of the page's views, in the column |
| `row` | A form row, in a form or alone: its label, its field, and its message |
| The kind of widget | Each widget, such as `button`, `input`, `combobox`, `form`, `group_form`, `table`, `chart`, or `tabs` |

A button also has a `data-variant` that gives its `variant`: `primary`, `secondary`, or
`danger`.

A `WebApplication` or a `WebModelApplication` takes the style as `style=`. The API reference of
[`WebStyle`](../api/webstyle.md) describes each field.

### Deploy behind nginx

The app serves plain HTTP. To give other users the app over HTTPS, put it behind a reverse
proxy such as [nginx](https://nginx.org/), which holds the certificate. Run the app as one
process, on its default address `127.0.0.1:8000`, so that only the proxy reaches it:

```bash
python app.py --backend web
```

If you do not trust all the users, also refuse the regular expressions of table filters, as
[Serve the app to other users](#serve-the-app-to-other-users) explains:

```bash
COMPOSEUI_FILTER_PATTERNS=off python app.py --backend web
```

Keep the process running with your service manager, for example a systemd service. In a
systemd service, set the variable with `Environment=COMPOSEUI_FILTER_PATTERNS=off`. Then
give nginx a `server` block such as this one:

```nginx
server {
    listen 443 ssl;
    server_name app.example.org;
    ssl_certificate /etc/ssl/app.example.org.pem;
    ssl_certificate_key /etc/ssl/app.example.org.key;

    client_max_body_size 6m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        add_header Strict-Transport-Security "max-age=31536000" always;
    }
}
```

Each line keeps a part of the app working:

- **`proxy_set_header Host $http_host`** gives the app the address that the browser used,
  with its port. Without it, nginx sends `127.0.0.1:8000`. With `$host`, the port is lost.
  In both cases, the server refuses the actions of a browser that sends only an `Origin`
  header (403), because the origin does not match the address that the app sees. Browsers
  send `Sec-Fetch-Site` only over HTTPS and to `localhost`, so on plain HTTP this applies
  to every action.
- **`proxy_set_header X-Forwarded-Proto $scheme`** tells the app that the browser used
  HTTPS. The server reads it only from the addresses in the `FORWARDED_ALLOW_IPS`
  environment variable, `127.0.0.1` by default. If nginx runs on another machine, set this
  variable to its address.
- **`client_max_body_size 6m`** lets a study or a file of up to 5 MiB through. nginx's own
  limit is 1 MiB: above it, nginx refuses Open and the file inputs (413) before the app
  sees the request. With a larger `max_upload_size`, set this limit to that size plus 1 MiB.
- **`Strict-Transport-Security`** makes the browser use HTTPS for the site from then on. The
  session cookie has no `Secure` flag, so serve the app over HTTPS only. Redirect plain
  HTTP to HTTPS in a `server` block of its own.

nginx passes the `Origin`, `Referer`, and `Sec-Fetch-*` headers on as the browser sent
them. Do not remove them: the server needs them to accept the app's own requests.

The app has no login. To ask for a password, add these lines to the `location` block:

```nginx
        auth_basic "Pipes";
        auth_basic_user_file /etc/nginx/app.htpasswd;
```

Then add a user to the file. `openssl` asks for the user's password:

```bash
printf "ada:%s\n" "$(openssl passwd -apr1)" >> /etc/nginx/app.htpasswd
```

nginx then asks for a user and a password before the first page, and the browser sends
them with each of the app's requests. Each user still gets their own session in each
browser: the app does not know which user is logged in.
