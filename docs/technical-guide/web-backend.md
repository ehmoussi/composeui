# Design of the web backend

These are the decisions of `composeui.webcore` that the code does not make obvious. Keep them in
mind when you change it. The user guide's
[Web backend](../user-guide/running-the-app.md#web-backend) section covers what users see.

## The web backend

The web backend renders HTML on the server and updates the page with htmx.

- **The id is the rendered object.** The web has no live widget between two requests. A web
  renderer's rendered object is the id of its HTML fragment, `cui-{id(view)}-{role}`.
- **One main view per session.** Each browser session has its own main view, in a `WebSession`
  (`session.py`). `WebApplication.connect` records each connection, and connects it again on the
  main view of each new session.
- **Events go in, fragments come out.** An event goes to the server. The response sends back
  the fragments that the event changed, and htmx swaps them into the page.

## A button click on the web

This is the click of [A button click](architecture.md#a-button-click) on the web, step by step:

![The browser posts the click. The middleware checks it. The route gives it to the session, which dispatches it to the button's renderer under its lock. The callback changes the label, which marks the label's renderer dirty. The session renders the dirty fragments, and htmx swaps them into the page.](../images/web-click.svg)

1. **The browser posts the event.** The button's fragment (`WebButtonRenderer.to_html`) has
   `hx-post="/widget/{id}"` and `hx-vals` with `event=click`. Its `hx-swap="none"` tells htmx
   not to swap the button with the response.
2. **The middleware checks the request.** `create_starlette_app` in `webapplication.py` adds
   the middleware. `SecurityHeadersMiddleware` (`headers.py`) adds the security headers to
   every response. `BodySizeLimitMiddleware` (`limits.py`) refuses a body that is too large.
   `SameOriginMiddleware` (`origin.py`) refuses a request from another origin. Starlette's
   `SessionMiddleware` reads the signed session cookie.
3. **The route finds the session.** `widget_event` (`routes.py`) gets the session from the
   cookie's id. When the session is gone, or did not serve the page, the response has
   `HX-Refresh`. The page reloads, with the cookie's session or a new one. Otherwise, the
   route calls `WebSession.handle_event` in a thread: the app's callbacks are synchronous
   code, and must not block the event loop.
4. **The session dispatches the event.** `handle_event` finds the renderer by its id in the
   session's own `renderers`. An id of another session is not found. `_respond` takes the
   session's lock and opens `collect_dirty()`, a set of dirty renderers for this request. Then
   it calls `WebButtonRenderer.dispatch`, which refuses the click when the button is disabled.
5. **The signal runs the callback.** `dispatch` emits `clicked`. The callback sets
   `label.text = "Done"`.
6. **The label's renderer becomes dirty.** `notify_renderer`, the `on_setattr` hook of every
   view field, calls the renderer's `refresh_attribute("text", ...)`. The handler in the
   `_refresh_dispatcher` of `WebLabelRenderer` is `_mark_dirty`. It only adds the renderer to
   the dirty set: the renderer renders nothing yet.
7. **The session renders the dirty fragments.** `_respond` adds the renderers that a thread
   changed since the last response (`take_pending`) to the dirty ones. `render_dirty` calls
   `to_html(oob=True)` on each, which adds `hx-swap-oob="true"` to the root element. It drops a
   fragment that another dirty fragment contains, else htmx would swap it twice.
8. **The session adds the page's fragments.** When the event changed the main view's title,
   language, or running jobs, `_respond` adds their fragments too. When the event opened
   another page, `_respond` also returns the page's address.
9. **The route responds.** `_widget_response` sends the fragments as HTML. With a new page, it
   adds `HX-Push-Url`, which puts the address in the browser's history. When the app closed
   (the Exit action), it drops the session and responds with `HX-Redirect` to `/`.
10. **htmx swaps the fragments.** htmx puts each `hx-swap-oob` fragment in place of the element
    with the same id. The label shows "Done". The button stays as it is.

When the app has [reactive methods](architecture.md#reactive-methods), they run once `dispatch`
returns, in the batch that `_respond` opens around it, and before step 7. The fields that they set
mark their renderers dirty, as in step 6, so their fragments go out in the same response.

The other routes follow the same steps. `widget_file` gives an upload to the session in place of
a form. `jobs_poll` runs no event: its response sends the changes that the threads made.

## Requests and updates

- **htmx requests and responses.** The page and the server talk through htmx requests and
  responses, with Starlette (not FastAPI) and no JavaScript framework. Each renderer writes its
  HTML by hand (no Jinja2), with `markupsafe.Markup`, which escapes every value put in it.
- **The renderers' modules.** `webrenderer.py` holds the base `WebRenderer` and the helpers that the
  renderers share, such as `_view_html` and the icons. Each family of renderers has its module in
  `_renderers/`: `inputs.py` (text, numbers, dates), `controls.py` (check boxes, buttons, sliders),
  `choices.py` (also the tree), `content.py` (labels, images, Markdown, consoles, logs, metrics, the
  status bar), `charts.py`, `graphics.py` (maps, drawings), `tables.py`, `files.py` (path fields,
  uploads, the server's files), `forms.py`, `actions.py` (menus, toolbars), `dialogs.py`,
  `containers.py` (rows, columns, panes, lists, tabs, pages) and `navigation.py` (the main view, its
  sidebar and router). A module holds one family: split one that starts to mix two, whatever its
  length. Such a module imports `webrenderer.py`. So `renderers.py`, not `webrenderer.py`, maps each
  renderer key to its class, written out, not discovered. The base names no renderer at run time: it
  asks each one, through `is_drawn_apart` (a dialog, drawn at the end of the page) and `shows` (a
  router's or a tab's page shown). A form row's label is always a `WebFormLabelRenderer`, which the
  base only casts to. When the base must treat a renderer apart, add such a hook with a default, not
  an `isinstance` check, which would tie that renderer to the base's module. `changes.py` collects
  the renderers that a request changes (`collect_dirty`), and `rendertarget.py` holds a session's
  view tree and its lock (`RenderTarget`).
- **No code in the markup.** The page's `Content-Security-Policy` (`headers.py`) runs script
  files only, and htmx runs without `allowEval`: no inline handler, `hx-on`, `js:` value, or
  trigger filter. A renderer marks its element (`data-post-event`, `data-close-dialog`, ...) or
  triggers on a custom event (`enter-key`, `escape-key`, `activate`), and the page's scripts do
  the rest (see [The page's scripts](#the-pages-scripts)).
- **Hidden fragments keep their id.** A hidden fragment's root keeps its id (`hidden`
  attribute), so a later swap has a target.
- **Updates.** Setting a view attribute marks its renderer dirty in a request-scoped set
  (`collect_dirty`, a no-op outside requests). The route then renders every dirty fragment as
  an out-of-band (OOB) swap (`render_dirty`). Controls use `hx-swap="none"` and the sender is never
  swapped back, so typing is never interrupted. The one exception is a float field left with
  unparsable text, swapped back to the view's value.
- **Changes from threads.** `call_on_main_thread` runs its callback under the session's lock,
  and keeps what it changed in the session's `pending`. They are sent with the next event's
  response or fetch (a full page drops them). While the main view's jobs run, the page's
  `cui-jobs` poller fetches `/jobs` every `JOBS_POLL_MS`, which brings them. The server pushes
  nothing, so an idle page sends nothing. A response whose event starts or ends the jobs swaps
  the poller in, as it does the page's marker.
- **Choices of several values.** Each box of a check list posts its key and its state, not a
  flip, and the check-all box posts its state too. A post that arrives twice leaves the same
  choice, and a click on a stale page does what the page showed. The user's change swaps only
  the parts that it changes: the check-all box, the list, and a multi-combobox's summary. It
  never swaps the box clicked or the search field, which keep the focus. A post that changes
  nothing, such as one of a stale page, swaps all three back as the view is. The check-all box
  shows partly checked through `tables.js`, which reads `data-indeterminate`.
- **A drop-down list swapped while open.** A change of the app's swaps a multi-combobox whole.
  Each box has an id made from its key, so htmx gives it the focus back. But the dropdown is
  open only while the focus is in it, and a closed one's boxes take no focus. So `page.js` keeps
  it open through the swap with `dropdown-open`, on the element swapped out too: htmx gives the
  new element the old one's classes until it settles.
- **Ranges.** A range slider stacks two range inputs on one track, only their handles taking
  the pointer. The lower input draws the track and the fill between the handles, from the
  handles' positions (`--range-low`, `--range-high`), as daisyUI's fill only reaches one
  handle. The inputs count steps, so a decimal step needs no decimal arithmetic in the page.
  Each posts both positions, as the page shows them, and the server takes them by
  `RangeSliderMixin.moved`. While dragged, `page.js` stops a handle on the other. When the two
  meet in the upper half of the track, the low one goes on top (`data-low-on-top`): the high one
  can't move below it, so a press there moves the low one down. A date range is two date
  fields, each posting its end. The end that followed the one set swaps alone, never the field
  typed in.
- **Downloads** go through a ticket: see [Downloads on the web](#downloads-on-the-web).

## The page's scripts

- **One script per domain.** The scripts are files of `webcore/static/`, in the hashed
  addresses of `page.py`:
  - `page.js` runs in the `<head>`. It applies the theme before the body paints, and holds the
    common controls, the request and session headers, the post numbers, the protection against
    stale fragments, the loading of the libraries, and the `MutationObserver` that runs each
    script's work after a change of the page.
  - `tables.js` runs once after `page.js`, before the body: row activation, cell editing, the
    check-all box, a large table's scroll windows, and its clipboard.
  - `charts.js` loads with uPlot, and `maps.js` with deck.gl, once the page shows the first
    chart or map.
- **Classic scripts, no bundler.** Each script keeps its code in a closure, and shares only
  what the others use, under `window.ComposeUI`: `dispatch` from `page.js`, and the `sync`
  functions of `charts.js` and `maps.js`, which they add once loaded. `page.js` calls them
  from its observer.
- **The library, then the script.** `page.js` loads uPlot, then `charts.js` (deck.gl, then
  `maps.js`), one after the other. A failed load is forgotten, and asked again on a later change
  of the page, up to five times: never as the other file arrives. Once both are there, each
  change of the page goes to the script before any check that a chart is shown, so a chart
  swapped out is destroyed, and a map finalized.
- **A chart's bars.** The server places the bars: the JSON of a chart holds each bar series'
  offset and width (`ChartView.bar_slots`), and the room between two bars' x. A series of
  another kind takes no room, so a line stands at the categories, over the bars. Without
  categories, `charts.js` adds half of that room to each end of the x range, so that the first
  and the last bar show whole. It adds it only when the range is the whole data: uPlot runs a
  scale's range function on a zoom too, and a zoom widened at each draw would drift as the
  series change.
- **A chart's stacked bars.** The server sends each stacked bar series its bars' bases
  (`ChartView.stack_bases`), by the points it sends, and each y axis how far its stacks reach,
  which its range takes in: uPlot fits a series' own values, which the legend keeps. The bars'
  builder draws each from its base (its `y0` and `y1` facets), and the hover shows no dot on a
  stacked bar, which would stand at the series' own value. Textual's plotext has no base:
  each bar goes from 0 to where it ends, the stack's last series first, which the others then
  cover.
- **A chart's bounds.** `charts.js` wraps each scale's range function last, so that an axis'
  bounds (`Axis.minimum`, `Axis.maximum`) win over the bars' 0 and the reference lines. The x
  range keeps a zoom as the user made it, which uPlot also asks the range function for. The
  zoom kept across a swap, and the image's address, take the whole data at the bounds for no
  zoom.
- **A chart's times.** A time axis' values are seconds since 1970, in UTC, on every backend.
  The page shows them in UTC whatever the browser's time zone: uPlot's `tzDate` and the legend
  read them as `Etc/UTC`. So a naive `datetime`, which the core takes as UTC, shows as the app
  wrote it, as Qt (`DateAxisItem(utcOffset=0)`), Textual and matplotlib show it. The server
  sends how precise the times are (`time`: `day`, `minute` or `second`), which the legend shows.
- **The order of the listeners.** Listeners of one event and phase run in the order they were
  added, and `tables.js` adds its after all of `page.js`'s. `page.js`'s captured Enter
  dispatches `activate`, which selects a row, before `tables.js` activates it. A cell's Escape is
  captured: else the sidebar's Escape in `page.js` would first move the focus, and the cell
  would post the text typed.
- **Types without Node.** The scripts carry JSDoc types. `make js-check` checks them with
  TypeScript's compiler, a binary, in strict mode, with `noUncheckedIndexedAccess`: an element
  read from an array or a map may be missing (`js/tsconfig.json`). `js/composeui.d.ts` declares
  the globals, the JSON of a chart and of a map, and the events of htmx; `make web-deps`
  downloads the declarations of htmx and uPlot beside it. deck.gl's bundle has none: its
  classes are unchecked. A JSDoc cast, such as of `event.target`, is not checked: it says what
  the page holds.

## Tables on the web

- **A large table's frame.** `WebSourceTableRenderer` draws a window of rows between two filler
  rows (`style` heights, which the policy allows) that give the scroll bar every row's height.
  `tables.js` posts the first row shown once the scroll stops outside the window. Only the
  `<tbody>` comes back (in a `<template>`, as a table's parts), so the scroll position stays.
  Browsers cap an element's height: past `SOURCE_TABLE_SCROLLED_ROWS`, a filler's row height
  stands for more than one row. The page maps the scroll position through the fillers as drawn,
  and posts the row under the headers with its offset. The server sizes the filler above the
  new window so that this row stays there, the frame's height kept. A new order swaps the whole
  frame, back at the top.
- **A table's parts.** A sort, a search, or a filter swaps only what it changes (the headers'
  row, the `<tbody>`, the count, the filter bar), never the search field being typed in. The
  bar goes last in the response: it may hold the element that sent the request (the filter
  editor's form), and htmx swaps no fragment after that one is gone. The `<tr>` and `<tbody>`
  go each in a `<template>` of its own: bare, they switch htmx's parsing of the whole answer to
  a table's rules, which mangles the fragments after them. An invalid filter value swaps only
  its message, which `syncInvalidFields` marks the field by.
- **A check-all box posts its state.** A click does what the page showed, partly checked to
  checked, not what the server would decide from its own rows, which a stale page may not show.

## Order and sessions

- **Order.** The server handles a page's posts in the order that the page sends them
  (`order.py`). Without it, a field's value, posted as a click on a button blurs the field, can
  reach the server after the click. `page.js` sets a page id and a number on each post in
  `htmx:beforeSend`. The routes await its turn on the event loop, no thread held, for at most
  `ORDER_TIMEOUT` (2 s) for a post that never comes. Scroll windows (`hx-sync="this:replace"`)
  carry none: one that is replaced may never be sent. A session keeps the order of `MAX_PAGES`
  (32) pages. Save's form (`cui-save`), submitted without htmx, carries no header: `page.js`
  sets its hidden `page` and `post` fields as it is submitted. Holding the posts back in
  `page.js` fails instead: htmx drops a held request whose element a swap has since replaced,
  and gives no promise to wait on for a trigger's request.
- **Sessions.** A signed cookie maps to a `WebSession`, which holds its renderers by id and an
  `RLock` (the status bar timer takes it through `call_on_main_thread`). A request whose session
  is gone answers `HX-Refresh`. The tabs of a browser share one cookie. So a tab left open on a
  page of an ended session sends the cookie of a newer tab's session. The session ended when
  the server restarted, or when it expired. The newer session doesn't have the views of the
  page. Worse, `id()` can give one of its views an id that the page shows. So each page names
  its session's `page_tag`. `page.js` sends it with each htmx request (`X-ComposeUI-Session`),
  and Save's form in its `session` field. `_session` in `routes.py` answers a request with
  another tag as if its session were gone. A plain link, such as a download, sends no tag and
  is not checked: it only reads.
- **Idle sessions on disk** (`session_idle`). Each session of the `SessionStore` is in one place: in
  memory, being saved, on disk, or being woken. The lifespan's sweep (`hibernate_idle`, in a thread)
  saves one idle session at a time with `save_to`, into `<id>.partial`, then renames it to `<id>`: a
  crash leaves only the partial folder, which a `--reload` server's next process removes. A request
  for a session being saved or woken waits for it. A request during a save keeps the session in
  memory, and the saved folder is dropped. One that finds the session on disk builds it again,
  outside the store's lock, and `open_saved` opens it. A page's request finds, wakes or makes its
  session in one decision under the lock (`get_or_create`): one on disk without room to wake is
  refused, as a slot can free just after, and a new session would then take its cookie and lose it.
  The async routes look the session up in the threadpool when it's not in memory
  (`_session_off_loop`). The woken session has a new `page_tag`, so the page reloads on its address,
  which brings back its page. Keeping the tag would need the same widget ids, which `id()` doesn't
  give. The sweep asks `WebSession.can_hibernate` under the session's lock, and takes the store's
  lock after it: `_drop_expired` takes them the other way around. `held()` keeps a session in memory
  during the requests that take a while outside its lock, such as an upload's body and a CSV's
  stream, and the session is idle from the end of the last one. A large table's source blocks the
  save if the app gave it since the last `loaded`: the session notes the sources once a request that
  emitted `loaded` is done, its reactive methods included, and after `open_saved` and Open. The save
  skips the "initial" state of a `--reload` (`code_edits`), unless the store's folder is a
  `--reload` server's: the same code opens it, and a field that starts with another value at each
  build, such as a date, would be taken for an edit of the code. A plain link (a CSV, a chart's
  image) sends no tag: after a wake, its widget id is unknown, and it answers 404 until the page
  reloads.

## Uploads and Open

- **Uploads.** `widget_file` reads the multipart body itself (`uploads.py`), not through
  Starlette's form parser, whose spooled file a route can only copy. The body goes to a scratch
  file with no lock held, and `WebSession.pick_file` moves that file. A file over the limit
  keeps being read, to answer in the status bar, but stops going to the disk. Open still reads
  through Starlette: a study is small. A replaced upload stays until `jobs.is_running` is false:
  nothing says which file a job reads, and a job may not have opened it yet. Holding a file
  through the app's code would bring the same failure back each time an app forgets.
- **An upload in the app's folder.** With `upload_folder`, `_keep_in_folder` takes the name
  first with an empty file opened exclusively, so two sessions never share it. A name that a
  table's cell holds counts as taken, even with its file gone: the same text would reach the
  cell, and no edit would say that the file changed. The file is written beside the name, then
  replaces it. The session never tracks the file. It deletes it only when no cell holds its
  path at the end of the edit, since the app would never learn of it. A path with
  `server_roots` refuses any upload, because its page sends none and a crafted one would write
  in that folder.
- **A long upload and the order.** A file's post takes its turn (`order.py`) once its whole body
  has arrived, so a later post runs first after `ORDER_TIMEOUT`. Waiting for the upload would
  hold every click for as long as the network takes. So `page.js` marks only the upload's own
  button, and the docs say that a click does not wait.
- **Open** applies an upload to a scratch instance first (core's `load_state_data`), so a bad
  file never half-loads. Responses send `Cache-Control: no-store` and controls set
  `autocomplete="off"`, so a reload always shows the server's state.
- **Open over unsaved changes.** The browser's picker sends the file at once, so the question
  comes after the upload: `WebSession.load_state` keeps the file's bytes in the dialog's pending
  call (at most `MAX_STATE_SIZE`) until the answer, a post of its own. A second upload replaces
  them. A session that asks doesn't hibernate (an open dialog), so the bytes never need saving.
  A file of another type, or too large, is refused before the question.
- **Save, not a download.** Only Save's post (`POST /state/download`) takes the study as saved.
  `GET /state` downloads it and changes nothing: a link from another site reaches it, and the
  user may never get the file.

## Downloads on the web

A browser downloads a file only from a GET: htmx reads the answer to a POST, and puts it in the
page. The question is where the app's `content` runs. The design keeps it out of every GET.

**The steps.**

1. The click on a `DownloadView` is an htmx POST, like any other click. `content` runs there, and
   `MainView.download` gives its result to `WebMainRenderer.download`.
2. The session keeps the file under a ticket: 128 random bits (`webcore/downloads.py`).
3. The answers to events, the fragments, the jobs poll, and the full page name the tickets not
   fetched yet, as links in `#cui-downloads` (`downloads_marker`).
4. `page.js` follows each ticket's link once (`startDownloads`): `GET /download/{ticket}`.
5. That GET hands over the bytes or the file kept. It runs none of the app's code, but the
   writer of a `StreamContent` (see "Streaming" below).

**Why the click is a POST.** A GET that ran the app's code would have two failures:

- **Another site can send it.** The session's cookie (`SameSite=Lax`) goes with a top-level GET
  from any site, and widget ids come from `id()`, so they can be guessed. The other site cannot
  read the file, but the app's code runs without the user's click. That code can write, for
  example mark a study as exported. `SameOriginMiddleware` refuses such requests for unsafe
  methods only (see the `web-security` skill).
- **It overtakes the posts sent before it.** The page numbers its posts, and the server runs them
  in that order (`order.py`). A GET has no number. If the user edits a cell, then clicks at once,
  `content` can run before the edit, and the file misses it. Save had this bug: its form carries
  its number for this reason.

A POST has neither failure, with no code of its own: `SameOriginMiddleware` and `PostOrder` handle
it.

**Why a ticket.** A job (`in_job`) and `MainView.download` called from the app's code give a file
that no request answers: a job's callback runs on the job's thread. So the file waits in the
session until the page asks for it. The click uses the same path: one mechanism for the three
cases.

**The ticket's states.**

| State | First fetch | 10 minutes pass (`DOWNLOAD_TTL`) | A file past the limits | The session ends |
| --- | --- | --- | --- | --- |
| Not fetched | Send it, and stop naming it | Drop it | Drop the oldest | Freed with the session |
| Fetched | Send it again | Dropped 1 minute after the fetch (`FETCHED_TTL`) | Drop the oldest | Freed with the session |
| A stream, not fetched | Take it: drop the ticket, and write it | Drop it | Drop the oldest | Freed with the session |
| A stream, taken | 404: its writer runs once | Cannot happen: it has no ticket | Cannot happen | Its writer stops |

A `HEAD` of a stream answers its headers, without `Content-Length`, and doesn't take it.

- **Named until fetched.** An answer can be lost: a duplicate post answered with 204, or a page
  reloaded. So every answer names the tickets not fetched yet, and `page.js` remembers the ones
  that it followed.
- **Kept a minute after the fetch.** A `HEAD` (which Starlette answers from the GET's route), or a
  browser's download manager, asks again.
- **The limits.** A session keeps at most `MAX_DOWNLOADS` files, and `MAX_DOWNLOAD_BYTES` of bytes
  in memory. A `Path` stays on the disk, and does not count.
- **The answers.** Without the session, the GET answers 404, not a redirect: a redirect would save
  the page as the file. The link's `download` attribute keeps the page when the file is gone, so
  the browser shows a failed download.

**Why not a generator.** Calling a generator runs none of its code: its code runs as the answer
reads its pieces, in the GET. With a ticket, that GET comes after the click, on another thread,
while the user's posts change the views. A generator could read the views before and after an
edit in one file.

**The GET that was rejected.** A click without `in_job` could be a GET that streams, safely, with
six rules:

1. The same origin check as the posts (`is_same_origin`).
2. Its number in the page's posts, which the server waits for.
3. No `HEAD` and no prefetch (`Sec-Purpose`); a `<button>`, so that the browser has no link to
   prefetch.
4. The check of `takes_events`.
5. Each piece read under the session's lock, as `table_csv` does.
6. The connection broken on an error in the middle.

It would still need the ticket for `in_job` and `MainView.download`: two mechanisms to save one
round trip. Streaming would also work only without `in_job`, and the pieces could read the views
before and after an edit.

**Streaming.** A `StreamContent` splits the file in two. `content`, or the app's code, makes it
in the post or the job, in order with the user's edits, and reads the views there. Its `write`
function runs later, from what `content` gave it. The ticket and the steps above stay the same.
Only the GET changes: it runs `write` (`webcore/streaming.py`).

- **Why the GET may run it.** Another site can't send the GET: it can't guess the ticket, of its
  session only. The order is the click's, where `content` read the views. `write` reads no view:
  that rule is the app's, in `StreamContent`'s docstring and the user guide, and nothing
  enforces it.
- **Once.** The first GET takes the ticket (`Downloads.take`): a writer can't run twice, and a
  second fetch answers 404. A `HEAD` doesn't take it.
- **A thread of its own.** `write` runs on a daemon thread, not on AnyIO's pool, whose 40 threads
  the sync routes share: a long export would hold one for its whole transfer. The session's lock
  is never held meanwhile.
- **Backpressure.** `DownloadSink` gathers the writes into pieces of 256 KiB
  (`DOWNLOAD_CHUNK_SIZE`), and cuts larger ones. The writer waits on a `threading.Condition`
  while 1 MiB (`MAX_QUEUED_BYTES`) waits to be sent. The answer reads the pieces on the event
  loop, woken by `call_soon_threadsafe`: it never blocks the loop. uvicorn waits for the socket
  to drain, so a slow browser slows the writer.
- **Cancel.** A browser that leaves, or the session's end (`WebSession.close`, through
  `streaming`), cancels the stream: the writer's next write raises `DownloadCanceledError`, and
  every one after. The answer then waits for the thread before it frees the session and its
  place, whatever cancels it meanwhile (`Stream.ended`): an anyio shield stops anyio's cancels,
  not asyncio's `task.cancel`, which uvicorn and then `asyncio.run` send as the server stops. A
  writer that doesn't write for a while holds them that long.
- **A server that stops.** uvicorn's graceful shutdown waits for the open answers before the
  lifespan closes the sessions, and tells the app nothing. So `run` gives uvicorn
  `WebSettings.shutdown_timeout` as `timeout_graceful_shutdown`, which the processes of a
  `--reload` server get too. Past it, uvicorn cancels the answers, and their `finally` cancels
  the streams. A writer that doesn't write still holds the stop until its next write.
- **Errors.** The answer waits for the first piece before it sends its headers. A writer that
  fails before it gets a 500, and the error is logged. One that fails after it raises
  `StreamFailedError`, which breaks the connection: the browser shows a failed download, not a
  short file.
- **Limits.** At most `WebSettings.max_download_streams` streams run at once on the server,
  and `max_session_download_streams` for one session (`StreamPlaces`, AnyIO `CapacityLimiter`s);
  the next wait. A stream takes its session's place first: one that waits for it holds none of
  the server's, so one browser that reads slowly can't take them all. A client that opens many
  sessions still can, as for `max_sessions`. The waiting answer notices a browser that left
  only at its first piece.
- **Held.** The answer holds the session (`held`): it isn't saved to disk, and doesn't expire,
  while the file is sent. A session is idle from its last request's end (`_Entry.is_expired`).
  The GET takes the ticket before its answer holds the session. The lookup of the GET counts as
  a request, so only a `session_idle` shorter than that gap could save the session meanwhile;
  the stream would then answer 404.
- **Not compressed.** `GZipMiddleware` would compress each piece on the event loop. The app's
  downloads (`/download/`) skip it, the bytes and the files too.

## Pages, tabs, and dialogs

- **Pages and tabs.** The router sends only the shown page. A change on another page is not
  sent: the page brings it once shown, as navigating swaps the router. Tabs send only the shown
  tab's views, and the other panels stay empty. The browser shows the tab picked at once. Then
  the answer to its post fills the tab picked and empties the tab left.
- **Pages and tabs built once shown.** As Qt does, the router and the tabs build the views of a
  page or a tab the first time it shows: by an address, a link, a tab picked, or the app's code.
  Each session of an app with many pages then takes less memory, and its first page comes
  sooner. A page or a tab not built has a renderer of its own, without its views. Until it's
  built, it adopts the dialogs inside it, which the app opens whatever is shown, so they follow
  its enabled state. A post to a view not built finds no widget in the session, and is refused
  as any unknown widget is.
- **Dialogs** render at the end of the page, outside the shown page's slot: a page not shown
  is not sent, and would take them with it. The browser opens a modal `<dialog>` only from a
  script: `page.js` opens each one swapped in shown, once. A button closes its dialog in the
  browser first, so the focus returns where it was, then posts its answer. The server swaps it
  closed.

## The header, icons, and images

- **Header.** A web app's header, not a desktop menu bar: File's New, Open, and Save are buttons
  of their own (Save As and Exit left out). Any other menu is a drop-down under its title, marked
  with a chevron so it reads apart from the buttons. A `ToolBar`'s buttons go before the menus.
  A drop-down is as wide as its longest item, the shortcut a faded hint beside it. On a phone,
  the buttons with an icon keep only their icon, and the app's title is cut short. So the header
  holds on one line. The pages' toolbar has a row of its own.
- **Icons.** An action's `icon` is a file path, as Qt reads it: `icons.py` serves the file at
  `/icon/<digest><suffix>`, an address naming its content, cached for good. Only image files
  that a view has named are served, and `icon` is never loaded from a study, so no request can
  name a file. An SVG is drawn as a CSS mask in the text's color, so it follows the theme like
  the built-in New, Open, and Save icons. Another image shows as it is.
- **Images.** An `ImageView` has its own route, `/widget/{id}/picture`, that answers its session
  only: an image can be private, so it stays out of the process's registry of icons. A `data:`
  address would send it again with each swap. The address names the content by its digest, so a
  browser can keep it, and an older digest answers 404, never another image. The route serves
  only what starts as an image, as an app may set a path that a user typed. `image` is never
  loaded from a study, as `icon` is not.
- **Drawings.** A `DrawingView` is SVG that the server makes from validated shapes, with no
  script. The element keeps the proportions of `bounds`, so a percentage of it places a point.
  Each shape is in a nested `<svg>` with a `viewBox`, which clips it to `bounds`, and its stroke
  does not scale. A text, an arrow head, and a dimension's ticks stand at a percentage and are sized
  in pixels, so they keep their size. They stay outside the nested `<svg>`: a text near the edge
  is not cut. Only the browser knows the scale on the page, so an arrow's line stops inside its head
  by a length computed at the largest size that the view can have.
- **By design:** `Menu.is_visible` is ignored (a drop-down is always shown). An action's `data`
  is not displayed. Ctrl shortcuts become Alt+Shift. An unknown page address is a 404, not a
  redirect: browsers ask for addresses of their own, like `/favicon.ico`.

## Testing the web backend

Tests drive the examples over HTTP with Starlette's `TestClient`
(`tests/test_webrenderer.py`). The behavior that only a browser shows (the caret, shortcuts,
the `aria-invalid` sync, the offline page, history, opening dialogs) is in
`tests/test_browser.py` (`make browser-test`).
