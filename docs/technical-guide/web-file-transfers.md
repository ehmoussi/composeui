# File transfers on the web

This page explains how the web backend receives uploads and sends downloads. It also covers how
the Open and Save actions transfer a study file. For request order and session lifetime, see
[Order and sessions](web-backend.md#order-and-sessions).

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
