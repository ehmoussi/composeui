"""One `MainView` per browser session, kept in memory, or on disk while it's idle.

A session is identified by a random id stored in Starlette's signed session cookie.
Every tab of a browser shares that cookie. So they share one session (and one app
state), the way two windows on the same document would. Different browsers or users
get their own. State lives in this process only: a restart starts every session over,
except with ``--reload``, whose server keeps them across its restarts (`SessionStore`).
"""

from __future__ import annotations

import contextlib
import enum
import functools
import logging
import re
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, NamedTuple

from composeui.core.model import InvalidStateError
from composeui.core.reactivity import batch, stop_reactions
from composeui.core.registry import RendererType
from composeui.core.reload import load_reloaded_state, save_reloaded_state
from composeui.core.study import has_data, open_study, save_study
from composeui.core.view import (
    ConsoleView,
    FileUploadMixin,
    SourceTableView,
    UploadedFile,
    View,
    dialogs_in,
)
from composeui.webcore.downloads import downloads_marker
from composeui.webcore.order import PostOrder
from composeui.webcore.page import jobs_poller, page_marker
from composeui.webcore.uploads import UploadRefusal
from composeui.webcore.webrenderer import (
    RenderTarget,
    UnsupportedEventError,
    WebActionRenderer,
    WebChartRenderer,
    WebConsoleRenderer,
    WebFilePathInputRenderer,
    WebFileUploadRenderer,
    WebImageRenderer,
    WebMainRenderer,
    WebSourceTableRenderer,
    WebTableRenderer,
    collect_dirty,
    handle_event,
    page_path,
    render_dirty,
    rendering_into,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from composeui.core.model import Model
    from composeui.core.view import DownloadedFile, MainView, Router
    from composeui.webcore.downloads import Downloads
    from composeui.webcore.streaming import Stream


#: largest state file accepted from an upload, in bytes
MAX_STATE_SIZE = 5 * 1024 * 1024
#: largest a study's archive may unpack to, in bytes (its database compresses well)
MAX_UNPACKED_SIZE = 20 * MAX_STATE_SIZE
#: the longest name of an upload's copy
_MAX_FILE_NAME_LENGTH = 200
#: why the status bar refuses a file that the disk has no room for
_NO_ROOM = "the server has no room for it right now"
#: the file of a saved session that names the directory of its uploads
_UPLOADS_NAME = "uploads"
#: the suffix of a session's directory being saved, renamed without it once complete
_PARTIAL_SUFFIX = ".partial"

LOGGER = logging.getLogger("COMPOSEUI")


def safe_filename(name: str) -> str:
    """Reduce `name` to letters, digits, `.`, `_` and `-`, safe in a response header."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "state"


def _views(main_view: MainView) -> Iterator[View]:
    """Get the views of `main_view`'s tree, it included, its dialogs' too."""
    views: list[View] = [main_view]
    while len(views) > 0:
        view = views.pop()
        yield view
        views.extend(view.children_views)


def _saved_uploads(file: Path) -> Path | None:
    """Get the uploads' directory that a saved session names, only if it's one of ours."""
    if not file.exists():
        return None
    path = Path(file.read_text(encoding="utf-8"))
    is_ours = path.parent == Path(tempfile.gettempdir()) and path.name.startswith("composeui-")
    return path if is_ours and path.is_dir() and not path.is_symlink() else None


class WebSession(RenderTarget):
    """A session's view tree, rendered once and then driven by its browser's requests."""

    def __init__(self, main_view: MainView, model: Model | None = None) -> None:
        super().__init__()
        self.main_view = main_view
        #: names this session in its pages, which send it back with their requests: a page
        #: another session served (e.g. one before the server restarted, whose tab is still
        #: open) then reloads, rather than act on views it doesn't show
        self.page_tag = secrets.token_hex(16)
        # held here: the signals giving it to callbacks only keep a weak reference
        self.model = model
        #: where the file path fields' uploads are kept, made by the first one
        self._uploads: Path | None = None
        #: the directory of the upload that each file field holds, by its widget's id
        self._held_uploads: dict[str, Path] = {}
        #: the directories of uploads that were replaced, removed once no job may read them
        self._replaced_uploads: list[Path] = []
        #: the order of each page's posts, which the routes handle in it
        self.post_order = PostOrder()
        #: the requests that take a while outside the session's lock (an upload's body, a
        #: CSV's stream): the session isn't saved to disk under them (`can_hibernate`)
        self._held = 0
        self._held_lock = threading.Lock()
        #: when the last request that held it ended (`time.monotonic`): it's idle from then
        self.held_until = 0.0
        #: the downloads being written (`StreamContent`), stopped when the session ends;
        #: under `_held_lock`
        self._streams: set[Stream] = set()
        #: the source of each large table as a study left it (`loaded`), which a study
        #: opened again gives again: one that the app gave since (e.g. from the user's file)
        #: can't be saved (`can_hibernate`)
        self._loaded_sources: list[tuple[SourceTableView, object]] = []
        self._note_loaded_sources()
        #: `loaded` was emitted: the sources are noted again once its reactions are done
        self._is_loaded_again = False
        main_view.loaded.connect(self._mark_loaded_again)
        with self.lock, rendering_into(self):
            main_view.render(RendererType.WEB)

    def _mark_loaded_again(self) -> None:
        self._is_loaded_again = True

    def _note_loaded_sources(self) -> None:
        """Note the large tables' sources, as a study left them: a wake gives them again."""
        self._is_loaded_again = False
        self._loaded_sources = [
            (view, view.source)
            for view in _views(self.main_view)
            if isinstance(view, SourceTableView)
        ]

    @contextlib.contextmanager
    def held(self) -> Iterator[None]:
        """Keep the session in memory while the block runs, e.g. while an upload arrives."""
        # not the session's lock: an async route takes it, and a callback may hold that one
        with self._held_lock:
            self._held += 1
        try:
            yield
        finally:
            with self._held_lock:
                self._held -= 1
                self.held_until = time.monotonic()

    @property
    def is_held(self) -> bool:
        """Whether a request holds the session (`held`): it isn't idle, however long it takes."""
        with self._held_lock:
            return self._held > 0

    @contextlib.contextmanager
    def streaming(self, stream: Stream) -> Iterator[None]:
        """Stop `stream` if the session ends while the block runs, or has ended."""
        # the order of `close`: it sets `has_ended`, then stops those it finds here
        with self._held_lock:
            self._streams.add(stream)
            has_ended = self.has_ended
        if has_ended:
            stream.cancel()
        try:
            yield
        finally:
            with self._held_lock:
                self._streams.discard(stream)

    def can_hibernate(self) -> bool:
        """Tell whether `save_to` and `open_saved` give the session back as it is now.

        Not while it's at work: a job, a file the page hasn't fetched, a long request. Nor
        while it shows what its views' state and its model's data don't hold: a dialog's
        question, an uploaded file, a large table's source given since `loaded`, a console's
        text. Nor when the app says so (`MainView.can_hibernate`).
        """
        with self.lock:
            main_view = self.main_view
            jobs = main_view.jobs
            with self._held_lock:
                held = self._held > 0
            return not (
                held
                or self.has_ended
                or self.closed
                or jobs.is_running
                or jobs.has_workers
                or len(self._downloads.tickets()) > 0
                or any(dialog.is_visible for dialog in dialogs_in(main_view))
                or any(view.source is not source for view, source in self._loaded_sources)
                or any(
                    (isinstance(view, FileUploadMixin) and view.file is not None)
                    or (isinstance(view, ConsoleView) and view.text != "")
                    for view in _views(main_view)
                )
                or not main_view.can_hibernate()
            )

    def suspend(self) -> None:
        """Release the session's model, keeping its uploads: `save_to` saved it, to wake."""
        with self.lock:
            self.has_ended = True
            # weak references would free them too, but only once collected
            stop_reactions(self.main_view)
            # not `drop`: its signals would run the app's code in another session's request
            self.main_view.jobs.cancel()
            if self.model is not None:
                self.model.close()

    def close(self) -> None:
        """Release the session's model (e.g. its database file) and its uploads; it's dropped.

        Its downloads being written stop.
        """
        with self.lock:
            self.suspend()
            with self._held_lock:
                streams = list(self._streams)
            for stream in streams:
                stream.cancel()
            if self._uploads is not None:
                # a job may still read them, even dropped: its thread goes on
                self.main_view.jobs.after_workers(
                    functools.partial(shutil.rmtree, self._uploads, ignore_errors=True)
                )
                self._uploads = None
                self._held_uploads.clear()
                self._replaced_uploads.clear()

    @property
    def closed(self) -> bool:
        """Whether the app asked to close (`MainView.close()`, e.g. the Exit action)."""
        renderer = self.main_view.renderer
        return isinstance(renderer, WebMainRenderer) and renderer.is_closed

    def trigger_action(self, widget_id: str) -> None:
        """Fire the `triggered` of one of this session's actions; ignore any other id."""
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if isinstance(renderer, WebActionRenderer):
                # its fragments are dropped: the caller answers with a download or a reload
                handle_event(renderer, "triggered", {})

    @property
    def _router(self) -> Router | None:
        renderer = self.main_view.renderer
        return renderer.router if isinstance(renderer, WebMainRenderer) else None

    def home_path(self) -> str | None:
        """Get the address of the first page; None for an app without pages."""
        router = self._router
        if router is None or len(router.pages) == 0:
            return None
        return page_path(router.pages[0].route)

    def open_route(self, route: str) -> bool:
        """Show the page on `route`, as its address asks; False if no page has it."""
        with self.lock, collect_dirty():  # the whole page is sent: drop the fragments
            router = self._router
            if router is None or router.page(route) is None:
                return False
            router.navigate(route)
            return True

    def page_html(self, reload_instance: str | None = None) -> str:
        """Get the whole page; with `reload_instance`, it reloads once its server restarts."""
        with self.lock:
            assert isinstance(self.main_view.renderer, WebMainRenderer)  # rendered when built
            self.take_pending()  # the whole page shows them
            return self.main_view.renderer.page_html(reload_instance, session_tag=self.page_tag)

    def save_to(self, directory: Path, *, code_edits: bool = True) -> None:
        """Save the session's study, its file and language, for `open_saved` to open.

        With `code_edits`, for a server whose code may have changed (`save_reloaded_state`).
        """
        with self.lock:
            save_reloaded_state(self.main_view, self.model, directory, code_edits=code_edits)
            if self._uploads is not None:
                (directory / _UPLOADS_NAME).write_text(str(self._uploads), encoding="utf-8")

    def open_saved(self, directory: Path) -> None:
        """Open what `save_to` saved, if it still fits the main view (else it's dropped)."""
        with self.lock, collect_dirty():  # the whole page is sent next: drop the fragments
            load_reloaded_state(self.main_view, self.model, directory)
            self._uploads = _saved_uploads(directory / _UPLOADS_NAME)
            self._note_loaded_sources()

    def handle_event(
        self, widget_id: str, event: str, form: Mapping[str, str]
    ) -> tuple[str, str | None] | None:
        """Apply a browser event to one of this session's widgets; None if it isn't one.

        Returns the fragments the event changed, with those changed outside any request
        since the last response, and the address of the page it navigated to, if it did
        (e.g. a toolbar link, or an app's own `navigate`).
        """
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if renderer is None:
                return None
            # as its page shows it: a stale or crafted post can't reach it
            if not renderer.takes_events:
                raise UnsupportedEventError(renderer, event)
            return self._respond(functools.partial(renderer.dispatch, event, form))

    def pick_file(
        self,
        widget_id: str,
        filename: str,
        received: Path,
        form: Mapping[str, str] | None = None,
        media_type: str = "",
    ) -> tuple[str, str | None] | None:
        """Hand an uploaded file to a `PickFileAction`, a file field or a table's path cell.

        None if `widget_id` is none of them; a table's cell is the `form`'s row and column.
        `received` holds the file: it is moved, not copied, and stays if refused.
        The file then has its own name: for an action, gone once its callbacks have run. For
        a file field, kept until the session ends or the field's next upload, and then until
        the jobs are over (see `_remove_replaced_uploads`). For a cell, until the session ends
        or a table's upload finds no cell holding its path. One of a type they don't offer is
        refused in the status bar. Returns what `handle_event` does.
        """
        suffix = Path(filename).suffix.lower()
        name = safe_filename(Path(filename).name)
        # a name of other letters alone, e.g. "データ.csv", would lose its type
        if not name.lower().endswith(suffix):
            name = safe_filename(f"upload{suffix}")
        # a system's limit is near 255 bytes; the end of the name holds its type
        name = name[-_MAX_FILE_NAME_LENGTH:]
        with self.lock:
            # after its session: its body took a while, and nothing would remove what is kept
            renderer = None if self.has_ended else self.renderers.get(widget_id)
            cell = None
            if isinstance(renderer, WebTableRenderer):
                cell = renderer.file_path_cell(form or {})
                if cell is None:  # a stale page: the table as it now is
                    return self._respond(functools.partial(renderer.pick_file, None, None))
                types = renderer.file_types(cell)
            elif isinstance(
                renderer, (WebActionRenderer, WebFilePathInputRenderer, WebFileUploadRenderer)
            ):
                types = renderer.file_types
            else:
                return None
            # before the move below replaces the file that the field holds
            if isinstance(renderer, (WebFilePathInputRenderer, WebFileUploadRenderer)) and (
                not renderer.is_enabled
            ):
                raise UnsupportedEventError(renderer, "file")
            if types and suffix not in types:
                return self._refuse_file(filename, f"expected a {' or '.join(types)} file")
            apply = self._applying_upload(renderer, cell, Path(filename).name, media_type)
            try:
                path = self._moved_upload(renderer, widget_id, name, received)
            except OSError:  # not the app's callbacks' errors, which aren't about the disk
                return self._refuse_file(filename, _NO_ROOM)
            try:
                return self._respond(functools.partial(apply, path))
            finally:
                # an action's file is gone once its callbacks have run
                if isinstance(renderer, WebActionRenderer):
                    shutil.rmtree(path.parent, ignore_errors=True)

    def _applying_upload(
        self,
        renderer: WebTableRenderer
        | WebActionRenderer
        | WebFilePathInputRenderer
        | WebFileUploadRenderer,
        cell: tuple[int, int] | None,
        name: str,
        media_type: str,
    ) -> Callable[[Path], None]:
        """Get what hands a kept upload, at its path, to `renderer`."""
        if isinstance(renderer, WebTableRenderer):
            return functools.partial(renderer.pick_file, cell)
        if isinstance(renderer, WebFileUploadRenderer):
            return functools.partial(self._hand_over, renderer, name, media_type)
        return renderer.pick_file

    def _moved_upload(
        self,
        renderer: WebTableRenderer
        | WebActionRenderer
        | WebFilePathInputRenderer
        | WebFileUploadRenderer,
        widget_id: str,
        name: str,
        received: Path,
    ) -> Path:
        """Move a received file where the session keeps it for `renderer`; get its path."""
        if isinstance(renderer, WebActionRenderer):
            path = Path(tempfile.mkdtemp(prefix="composeui-"), name)
            shutil.move(str(received), str(path))
            return path
        if isinstance(renderer, WebTableRenderer):
            path = self._cell_upload_directory(widget_id, renderer.file_paths()) / name
            shutil.move(str(received), str(path))
            return path
        directory = self._upload_directory(widget_id)
        shutil.move(str(received), str(directory / name))
        # only now: a move that fails leaves the field with the file it holds
        self._hold_upload(widget_id, directory)
        return directory / name

    @staticmethod
    def _hand_over(renderer: WebFileUploadRenderer, name: str, media_type: str, path: Path) -> None:
        size = path.stat().st_size
        renderer.pick_file(UploadedFile(name, size, media_type, path, is_temporary=True))

    def refuse_upload(
        self, widget_id: str, filename: str, refusal: UploadRefusal
    ) -> tuple[str, str | None] | None:
        """Say why a file that arrived isn't kept; None if the widget takes no file."""
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if not isinstance(
                renderer,
                (
                    WebTableRenderer,
                    WebActionRenderer,
                    WebFilePathInputRenderer,
                    WebFileUploadRenderer,
                ),
            ):
                return None
            if refusal is UploadRefusal.NO_ROOM:
                return self._refuse_file(filename, _NO_ROOM)
            size = self.main_view.max_upload_size / 1024**2
            return self._refuse_file(filename, f"the file is larger than {size:g} MiB")

    def _refuse_file(self, filename: str, error: str) -> tuple[str, str | None]:
        message = f"Can't open {filename!r}: {error}."
        return self._respond(functools.partial(self.main_view.status_bar.show_message, message))

    def _upload_directory(self, widget_id: str) -> Path:
        """Get a new directory for a field's upload, which `_hold_upload` makes the field's."""
        if self._uploads is None:
            self._uploads = Path(tempfile.mkdtemp(prefix="composeui-"))
        field = self._uploads / widget_id
        field.mkdir(exist_ok=True)
        return Path(tempfile.mkdtemp(dir=field))

    def _hold_upload(self, widget_id: str, directory: Path) -> None:
        """Make `directory` the field's upload, once its file is there: the last one is replaced."""
        if widget_id in self._held_uploads:
            self._replaced_uploads.append(self._held_uploads[widget_id])
        self._held_uploads[widget_id] = directory

    def _remove_replaced_uploads(self) -> None:
        """Remove the uploads replaced or cleared, once no job is running.

        A job may read a replaced file, and may not have opened it yet: nothing says which
        file a job reads, so any job running keeps them all. A request brings this here: while
        jobs run, the page's poller does.
        """
        for widget_id, directory in list(self._held_uploads.items()):
            renderer = self.renderers.get(widget_id)
            if isinstance(renderer, WebFileUploadRenderer) and not renderer.holds_file_in(
                directory
            ):
                self._replaced_uploads.append(self._held_uploads.pop(widget_id))
        if not self.main_view.jobs.has_workers:
            for directory in self._replaced_uploads:
                shutil.rmtree(directory, ignore_errors=True)
            self._replaced_uploads.clear()

    def _cell_upload_directory(self, widget_id: str, kept: set[str]) -> Path:
        """Get a new directory for a table cell's upload, among the table's.

        The cells' rows move, and one cell's path may be copied to another: each upload has
        its own directory, removed once no path of `kept` is in it.
        """
        if self._uploads is None:
            self._uploads = Path(tempfile.mkdtemp(prefix="composeui-"))
        table = self._uploads / widget_id
        table.mkdir(exist_ok=True)
        for directory in table.iterdir():
            if not any(str(path) in kept for path in directory.iterdir()):
                shutil.rmtree(directory)
        return Path(tempfile.mkdtemp(dir=table))

    def _respond(self, apply: Callable[[], None]) -> tuple[str, str | None]:
        """Run `apply` against the tree and return what changed, as `handle_event` does."""
        with self.lock:
            router = self._router
            route = None if router is None else router.current_route
            main_view = self.main_view
            language, title = main_view.language, main_view.title
            jobs_running = main_view.jobs.is_running
            with collect_dirty() as dirty:
                # the reactive methods run once for all of the event's changes
                with batch():
                    apply()
                # e.g. New: once the reactive methods have run too
                if self._is_loaded_again:
                    self._note_loaded_sources()
                self._remove_replaced_uploads()
                # after: the event may hand changes over with `call_on_main_thread` too
                body = render_dirty({**self.take_pending(), **dirty})
            if main_view.title != title and isinstance(main_view.renderer, WebMainRenderer):
                body += main_view.renderer.brand_html(oob=True)
            if (main_view.language, main_view.title) != (language, title):
                body += page_marker(main_view.language, main_view.title, oob=True)
            if main_view.jobs.is_running != jobs_running:
                body += jobs_poller(is_running=main_view.jobs.is_running, oob=True)
            body += self._downloads_marker()
            if router is None or router.current_route == route:
                return body, None
            return body, page_path(router.current_route)

    def save_state(self) -> tuple[str, bytes, str]:
        """Return a download name, the saved study (`save_study`'s) and its media type."""
        with self.lock, tempfile.TemporaryDirectory(prefix="composeui-") as directory:
            main_view = self.main_view
            if main_view.state_filepath is not None:
                name = main_view.state_filepath.name
            else:
                name = f"{main_view.title.lower()}{main_view.extension}"
            state_filepath = main_view.state_filepath
            path = Path(directory, "study")
            save_study(main_view, self.model, path)
            # the browser's file is wherever it saves the download, not this scratch one
            main_view.state_filepath = state_filepath
            media_type = "application/zip" if has_data(self.model) else "application/json"
            return safe_filename(name), path.read_bytes(), media_type

    def load_state(self, filename: str, content: bytes) -> str | None:
        """Load an uploaded state file; on failure, return the status bar saying why."""
        with self.lock, collect_dirty() as dirty:
            error = self._load_state(filename, content)
            if error is not None:
                self.main_view.status_bar.show_message(f"Can't open {filename!r}: {error}.")
                return render_dirty(dirty)
            self.main_view.state_filepath = Path(Path(filename).name)
            self._note_loaded_sources()
            return None

    def _load_state(self, filename: str, content: bytes) -> str | None:
        extension = self.main_view.extension
        if Path(filename).suffix != extension:
            return f"expected a {extension} file"
        if len(content) > MAX_STATE_SIZE:
            return "the file is too large"
        with tempfile.TemporaryDirectory(prefix="composeui-") as directory:
            path = Path(directory, "study")
            path.write_bytes(content)
            try:
                open_study(self.main_view, self.model, path, max_size=MAX_UNPACKED_SIZE)
            except InvalidStateError as error:
                return str(error)
        return None

    def fragment(self, widget_id: str) -> str | None:
        """Render one of this session's widgets as it is now; None if it isn't one.

        The fragments changed outside any request come along too.
        """
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if renderer is None:
                return None
            pending = self.take_pending()
            pending.pop(widget_id, None)  # swapped in already
            return renderer.to_html() + render_dirty(pending) + self._downloads_marker()

    def chart_image(
        self, widget_id: str, image_format: str, query: Mapping[str, str]
    ) -> tuple[str, bytes] | None:
        """Draw the image of one of this session's charts; None if it isn't one.

        Raises `ValueError` for a format or a range it can't draw.
        """
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if not isinstance(renderer, WebChartRenderer):
                return None
            return renderer.image(image_format, query)

    def picture(self, widget_id: str, version: str) -> tuple[bytes, str] | None:
        """Get the content and media type of one of this session's images; None if not one."""
        with self.lock:
            renderer = self.renderers.get(widget_id)
        if not isinstance(renderer, WebImageRenderer):
            return None
        # outside the lock: a file can take a while to read, and the session's requests go on
        return renderer.picture(version)

    def console_text(self, widget_id: str) -> tuple[str, str] | None:
        """Get the file name and the text of one of this session's consoles; None if not one."""
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if not isinstance(renderer, WebConsoleRenderer):
                return None
            return renderer.text_file()

    def table_csv(self, widget_id: str) -> tuple[str, Iterator[str]] | None:
        """Get the file name and the CSV, in pieces, of one of this session's large tables.

        None if it isn't one.

        The rows shown at the call (`SourceTableView.csv_chunks`), each piece read under the
        session's lock: the session's other requests go on between two pieces.
        """
        with self.lock:
            renderer = self.renderers.get(widget_id)
            if not isinstance(renderer, WebSourceTableRenderer):
                return None
            filename, chunks = renderer.csv_file()

        def locked() -> Iterator[str]:
            # the source must stay open until the last row
            with self.held():
                while True:
                    with self.lock:
                        chunk = next(chunks, None)
                    if chunk is None:
                        return
                    yield chunk

        return filename, locked()

    def poll_jobs(self) -> str:
        """Render the jobs' poller as it is now, and what changed outside any request.

        The poller fetches this while the main view's jobs run (see `jobs_poller`).
        """
        with self.lock:
            pending = render_dirty(self.take_pending())
            self._remove_replaced_uploads()
            downloads = self._downloads_marker()
            return jobs_poller(is_running=self.main_view.jobs.is_running) + pending + downloads

    @property
    def _downloads(self) -> Downloads:
        renderer = self.main_view.renderer
        assert isinstance(renderer, WebMainRenderer)  # the session rendered it on the web
        return renderer.downloads

    def _downloads_marker(self) -> str:
        """Name the files the page hasn't fetched yet, swapped in its own; none without any."""
        tickets = self._downloads.tickets()
        return downloads_marker(tickets, oob=True) if tickets else ""

    def take_download(self, ticket: str, *, claim: bool = True) -> DownloadedFile | None:
        """Get the file of one of this session's tickets; None if it has none.

        A `StreamContent` once, by the fetch that `claim`s it (see `Downloads.take`).
        """
        with self.lock:
            return self._downloads.take(ticket, claim=claim)


#: a session id, as `SessionStore.get_or_create` makes them: also its saved directory's name
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{43}")


def _remove_saved(directory: Path) -> None:
    """Remove a session saved in `directory`, with the uploads it names, if they're ours."""
    uploads = _saved_uploads(directory / _UPLOADS_NAME)
    if uploads is not None:
        shutil.rmtree(uploads, ignore_errors=True)
    shutil.rmtree(directory, ignore_errors=True)


class Hibernation(NamedTuple):
    """When idle sessions go to disk (`WebApplication.session_idle`)."""

    #: seconds a session is idle before it's saved and freed
    idle: float
    #: most sessions on disk at once: past it, the idle ones stay in memory
    max_saved: int


class _Place(enum.Enum):
    """Where a session is: in memory, or on disk, or between the two."""

    LIVE = enum.auto()
    SAVING = enum.auto()
    ON_DISK = enum.auto()
    WAKING = enum.auto()


class _Entry:
    """A session of the store, wherever it is."""

    __slots__ = ("last_seen", "place", "session", "settled", "touched", "unsaveable")

    def __init__(self, session: WebSession | None, place: _Place) -> None:
        self.place = place
        #: None while on disk
        self.session = session
        self.last_seen = time.monotonic()
        #: set once the session is saved or woken: the requests that came meanwhile wait
        self.settled: threading.Event | None = None
        #: a request came while it was being saved: it stays in memory
        self.touched = False
        #: saving it failed: it stays in memory, never tried again
        self.unsaveable = False

    def idle_since(self) -> float:
        """Get when its last request came, or ended if it held the session (`held`)."""
        assert self.session is not None  # in memory: only those are idle
        return max(self.last_seen, self.session.held_until)

    def is_expired(self, now: float, ttl: float) -> bool:
        """Tell whether it was idle for `ttl` seconds at `now`; never while saved or woken."""
        if self.place is _Place.ON_DISK:
            return now - self.last_seen >= ttl
        if self.place is not _Place.LIVE:
            return False
        assert self.session is not None  # in memory
        return not self.session.is_held and now - self.idle_since() >= ttl


class SessionStore:
    """The sessions by id, each dropped once idle for longer than `ttl` seconds.

    Expiry is checked whenever the store is used, so an idle server keeps its sessions
    until the next request. A dropped session's `StatusBar` timer may still fire; it
    then clears a message on a tree nothing displays any more, which is harmless.

    With `hibernation`, `hibernate_idle` saves each session idle for its `idle` seconds to
    a directory of its own, if it `can_hibernate`, and frees it. Its next request builds
    the session again and opens what was saved: its page then reloads, as the session that
    served it is gone. At most its `max_saved` sessions are on disk; past it, they stay in
    memory.

    With `saved`, a ``--reload`` server's directory, `save_all` saves the live sessions
    there as the server stops. The server started next opens one there when its browser
    comes back, under the same id: its cookie, signed with the same key, still names it.
    """

    def __init__(
        self,
        build_session: Callable[[], tuple[MainView, Model | None]],
        *,
        ttl: float,
        max_sessions: int,
        saved: Path | None = None,
        hibernation: Hibernation | None = None,
    ) -> None:
        self._build_session = build_session
        self._ttl = ttl
        self._max_sessions = max_sessions
        self.hibernation = hibernation
        self._entries: dict[str, _Entry] = {}
        #: sessions being built, outside the lock: they count against `max_sessions` too
        self._building = 0
        self._lock = threading.Lock()
        #: where the sessions on disk are, each in the directory of its id
        self._directory: Path | None = saved
        #: whether the store made `_directory`, and so removes it with the server
        self._owns_directory = False
        if saved is not None:
            self._find_saved(saved)
        elif hibernation is not None:
            self._directory = Path(tempfile.mkdtemp(prefix="composeui-sessions-"))
            self._owns_directory = True

    def _find_saved(self, directory: Path) -> None:
        """Take the sessions that the previous process saved; remove what it left unfinished."""
        for path in directory.iterdir():
            if path.name.endswith(_PARTIAL_SUFFIX):
                shutil.rmtree(path, ignore_errors=True)
            elif _SESSION_ID.fullmatch(path.name) is not None and path.is_dir():
                self._entries[path.name] = _Entry(None, _Place.ON_DISK)

    def get(self, session_id: Any) -> WebSession | None:
        """Return the session with this id (from a cookie, so of any type), or None.

        One on disk is woken. One being saved or woken is waited for: the caller is never
        a route's coroutine, which would hold up the event loop.
        """
        found = self._find(session_id, may_create=False)
        return None if found is None else found[1]

    def get_or_create(self, session_id: Any) -> tuple[str, WebSession] | None:
        """Return the session with this id as `get` does, else a new one with its own id.

        None while `max_sessions` are in memory. A full store refuses new sessions rather
        than dropping old ones: requests without a cookie, which anyone can send, would
        otherwise push out the users' own sessions and their unsaved work. A session on disk
        without room to wake is refused too, never replaced by a new one, which would take
        its cookie: the decision is one, under the lock, as a slot can free at any time.
        """
        return self._find(session_id, may_create=True)

    def _find(self, session_id: Any, *, may_create: bool) -> tuple[str, WebSession] | None:
        """Find, wake or build the session, each step decided with the lock held."""
        while True:
            with self._lock:
                self._drop_expired()
                entry = self._entries.get(session_id) if isinstance(session_id, str) else None
                if entry is None:
                    if not may_create or self._in_memory() >= self._max_sessions:
                        return None
                    self._building += 1
                    break
                if entry.place is _Place.LIVE:
                    assert entry.session is not None  # in memory
                    entry.last_seen = time.monotonic()
                    return session_id, entry.session
                if entry.place is _Place.ON_DISK:
                    if self._in_memory() >= self._max_sessions:
                        return None
                    entry.place = _Place.WAKING
                    entry.settled = threading.Event()
                    break
                entry.touched = True
                settled = entry.settled
            assert settled is not None  # saving or waking
            settled.wait()
        if entry is None:
            return self._create()
        return session_id, self._wake(session_id, entry)

    def is_at_hand(self, session_id: Any) -> bool:
        """Tell whether `get` answers at once: the session is in memory, or there is none."""
        with self._lock:
            entry = self._entries.get(session_id) if isinstance(session_id, str) else None
            return entry is None or entry.place is _Place.LIVE

    def _in_memory(self) -> int:
        """Count the sessions in memory, or about to be. Called with the lock held."""
        on_disk = sum(entry.place is _Place.ON_DISK for entry in self._entries.values())
        return len(self._entries) - on_disk + self._building

    def _wake(self, session_id: str, entry: _Entry) -> WebSession:
        """Build the session again and open what `_hibernate` saved, outside the lock.

        Building runs the app's code, which may be slow: the other sessions go on.
        """
        assert self._directory is not None  # only a store with one has sessions on disk
        directory = self._directory / session_id
        try:
            session = self._built_session()
            try:
                session.open_saved(directory)
            except BaseException:
                session.close()
                raise
        except BaseException:
            # its next request starts a new session, rather than fail the same way
            with self._lock:
                self._entries.pop(session_id, None)
                settled = self._settled(entry)
            _remove_saved(directory)
            settled.set()
            raise
        # not its uploads, which the session now holds
        shutil.rmtree(directory, ignore_errors=True)
        with self._lock:
            entry.session = session
            entry.place = _Place.LIVE
            entry.last_seen = time.monotonic()
            settled = self._settled(entry)
        settled.set()
        return session

    @staticmethod
    def _settled(entry: _Entry) -> threading.Event:
        """Take the event that the requests waiting for `entry` wait on, for the caller to set.

        Called with the lock held, in the change of place that ends the wait: a request may
        give the entry a new event as soon as the lock is released.
        """
        settled = entry.settled
        assert settled is not None  # saving or waking
        entry.settled = None
        return settled

    def _create(self) -> tuple[str, WebSession]:
        """Build a new session, which `_find` made room for (`_building`)."""
        try:
            # built outside the store's lock: building runs app code, which may be slow
            session = self._built_session()
            session_id = secrets.token_urlsafe(32)
            with self._lock:
                self._entries[session_id] = _Entry(session, _Place.LIVE)
        finally:
            with self._lock:
                self._building -= 1
        return session_id, session

    def _built_session(self) -> WebSession:
        """Build a session, closing its model if the session can't take it."""
        main_view, model = self._build_session()
        try:
            return WebSession(main_view, model)
        except BaseException:
            if model is not None:
                model.close()
            raise

    def hibernate_idle(self) -> None:
        """Save to disk each session idle for `idle` seconds that can be, and free it.

        One at a time: a request for a session waits only for its own.
        """
        hibernation = self.hibernation
        assert hibernation is not None  # only a store with one is swept
        with self._lock:
            self._drop_expired()
            now = time.monotonic()
            idle = [
                session_id
                for session_id, entry in self._entries.items()
                if entry.place is _Place.LIVE
                and not entry.unsaveable
                and now - entry.idle_since() >= hibernation.idle
            ]
            # counted once: a session kept in memory still counts, until the next sweep
            saved = sum(entry.place is not _Place.LIVE for entry in self._entries.values())
        for session_id in idle:
            if saved >= hibernation.max_saved:
                return
            with self._lock:
                entry = self._entries.get(session_id)
                # used meanwhile, while another one was saved: not idle any more
                if (
                    entry is None
                    or entry.place is not _Place.LIVE
                    or time.monotonic() - entry.idle_since() < hibernation.idle
                ):
                    continue
                saved += 1
                entry.place = _Place.SAVING
                entry.settled = threading.Event()
                entry.touched = False
            self._hibernate(session_id, entry)

    def _hibernate(self, session_id: str, entry: _Entry) -> None:
        """Save `entry`'s session into its directory, then free it, unless a request came."""
        assert self._directory is not None  # made with `hibernation`
        session = entry.session
        assert session is not None  # in memory until now
        directory = self._directory / session_id
        partial = directory.with_name(f"{session_id}{_PARTIAL_SUFFIX}")
        failed = False
        try:
            # its requests wait on the store, but a timer takes the session's lock too
            with session.lock:
                can_hibernate = session.can_hibernate()
                if can_hibernate:
                    shutil.rmtree(partial, ignore_errors=True)
                    partial.mkdir()
                    # the same code opens it, but a `--reload` server's next process: a field
                    # that starts with another value at each build, e.g. a date, would else
                    # be taken for an edit of the code
                    session.save_to(partial, code_edits=not self._owns_directory)
                    # complete, under its id: a crash before leaves only the partial one
                    partial.replace(directory)
        except Exception:
            LOGGER.exception("Can't save an idle session to disk: it stays in memory.")
            failed = True
            can_hibernate = False
        # the store's lock only once the session's is released: `_drop_expired` takes them
        # the other way around
        with self._lock:
            entry.unsaveable = failed
            kept = not can_hibernate or entry.touched
            if kept:
                entry.place = _Place.LIVE
            else:
                entry.place = _Place.ON_DISK
                entry.session = None
            settled = self._settled(entry)
        # only the requests that came during the save wait, and they keep it in memory
        settled.set()
        if kept:
            shutil.rmtree(partial, ignore_errors=True)
            shutil.rmtree(directory, ignore_errors=True)
        else:
            session.suspend()

    def save_all(self) -> None:
        """Save every live session into `saved`, as a ``--reload`` server's process stops."""
        assert self._directory is not None  # only such a server's lifespan calls it
        with self._lock:
            sessions = [
                (session_id, entry.session)
                for session_id, entry in self._entries.items()
                if entry.place is _Place.LIVE and entry.session is not None
            ]
        for session_id, session in sessions:
            directory = self._directory / session_id
            directory.mkdir(exist_ok=True)
            session.save_to(directory)

    def drop(self, session_id: Any) -> None:
        """Close the live session with this id, as its app asked (e.g. Exit)."""
        with self._lock:
            entry = self._entries.get(session_id)
            if entry is None or entry.place is not _Place.LIVE:
                return
            del self._entries[session_id]
        assert entry.session is not None  # live
        entry.session.close()

    def close_all(self) -> None:
        """Close every session as the server stops: nothing else removes their uploads.

        Once no request runs, nor `hibernate_idle`: no session is being saved or woken.
        """
        with self._lock:
            entries = list(self._entries.items())
            self._entries.clear()
        for session_id, entry in entries:
            self._end(session_id, entry)
        if self._owns_directory and self._directory is not None:
            shutil.rmtree(self._directory, ignore_errors=True)

    def _drop_expired(self) -> None:
        """Drop the sessions idle for `ttl`, in memory or on disk. Called with the lock held.

        A session in memory is idle from its last request's end (`idle_since`): a long one,
        such as a large download, keeps it.
        """
        now = time.monotonic()
        expired = [
            session_id
            for session_id, entry in self._entries.items()
            if entry.is_expired(now, self._ttl)
        ]
        for session_id in expired:
            self._end(session_id, self._entries.pop(session_id))

    def _end(self, session_id: str, entry: _Entry) -> None:
        """Close a session dropped from the store, in memory or on disk."""
        if entry.session is not None:
            entry.session.close()
        else:
            assert self._directory is not None  # where it is
            _remove_saved(self._directory / session_id)
