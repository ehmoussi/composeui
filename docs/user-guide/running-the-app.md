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
leaves the rest of the command line to the app (`--help` lists it). To always start one backend, build its application yourself,
for example `QtApplication(build_main_view=HelloMainView).run()`.

Every application takes a function that builds the main view, because on the web every
browser gets its own copy of it.

- **In development,** `--reload` runs the changed code each time that you save a Python
  file. See [Reloading the app on a change](#reloading-the-app-on-a-change).
- **On the web,** each browser gets its own session, and the server protects the pages from
  other sites. Read [Serve the app to other users](#serve-the-app-to-other-users) before
  other people use the app.

## Reloading the app on a change

Use `--reload` for development, on every backend: the app runs the changed code when a
Python file under the current directory changes. The web restarts its server (see
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
  child process starts and opens the study. Its window opens again. A running app can't
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
an instrument's connection, can't: the new model fails to open it while the previous model
holds it. Then every change fails as the changed code does, and the window keeps the
previous code. For such a model, start the app again yourself after a change.

On Textual, the app saves the study and exits on every change, and a new child process
starts and opens the study. So the terminal shows the app again as you left it, with the
same study file and language. Quit the app, for example with Ctrl+Q, to end the program.

The program runs again on every change, so code that it runs at the start, such as a
log's set-up, runs again too. Start the program as a script or with `-m`, for example
`uv run python -m examples.pipeform --backend qt --reload`. With the `reload` extra
(`watchfiles`), the system reports the changes. Without it, the backends check the files
at a fixed interval. They also check them for a project on a Windows drive under WSL
(`/mnt/c/...`), as the system does not report those changes. Set
`WATCHFILES_FORCE_POLLING` to choose for the web yourself.

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
  view. The tabs of one browser share it.
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
  Ctrl shortcuts for themselves. An uploaded file can be at most 5 MB, and the status bar
  says when a file is too large.
- **`--reload` restarts the server when a Python file under the current directory
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
  back, forward, bookmarks, and reloads land on that page. A route can't be `icon`, `jobs`,
  `reload`, `state`, `static`, or `widget`, because the backend uses these addresses.
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

- **Single process only.** The sessions live in the memory of one server process. A restart
  starts them all over: the server signs the session cookie with a key that it makes when
  it starts, so after a restart each browser gets a new, empty session, and the work that
  its user didn't save is lost.
- **Sessions have limits.** The server drops a session after an hour without use
  (`session_ttl`). It keeps at most 1000 sessions at a time (`max_sessions`). When it is
  full, a new browser gets an error (503) until a session ends, and the open sessions keep
  working.
- **Requests have a size limit.** The server refuses a request body larger than 6 MB (413)
  before it reads it.
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

### Deploy behind nginx

The app serves plain HTTP. To give other users the app over HTTPS, put it behind a reverse
proxy such as [nginx](https://nginx.org/), which holds the certificate. Run the app as one
process, on its default address `127.0.0.1:8000`, so that only the proxy reaches it:

```bash
python app.py --backend web
```

Keep the process running with your service manager, for example a systemd service. Then
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
  header (403), because the origin doesn't match the address that the app sees. Browsers
  send `Sec-Fetch-Site` only over HTTPS and to `localhost`, so on plain HTTP this applies
  to every action.
- **`proxy_set_header X-Forwarded-Proto $scheme`** tells the app that the browser used
  HTTPS. The server reads it only from the addresses in the `FORWARDED_ALLOW_IPS`
  environment variable, `127.0.0.1` by default. If nginx runs on another machine, set this
  variable to its address.
- **`client_max_body_size 6m`** lets a study or a file of up to 5 MB through. nginx's own
  limit is 1 MB: above it, nginx refuses Open and the file inputs (413) before the app
  sees the request.
- **`Strict-Transport-Security`** makes the browser use HTTPS for the site from then on. The
  session cookie has no `Secure` flag, so serve the app over HTTPS only. Redirect plain
  HTTP to HTTPS in a `server` block of its own.

nginx passes the `Origin`, `Referer`, and `Sec-Fetch-*` headers on as the browser sent
them. Don't remove them: the server needs them to accept the app's own requests.
