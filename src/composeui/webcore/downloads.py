"""The files that a session's app gives its user (`MainView.download`), until the page fetches them.

The app makes a file while it handles a request, or in a job's callback, which no request
answers. So the session keeps the file under a ticket, a name that can't be guessed, and each
answer to the page names the tickets not fetched yet (`downloads_marker`). The page's script
fetches each once, from `GET /_composeui/download/{ticket}`, which only reads: the app's code
never runs there, but a `StreamContent`'s writer, made in the request or job that gave the
file, from what it read there. That writer runs once: its first fetch takes it (`take`).

A URL that the app opens (`MainView.open_url`) waits the same way, as an `OpenedUrl`: the
page opens `GET /_composeui/open/{ticket}` in a new tab, which redirects to it.
"""

from __future__ import annotations

import secrets
import time
from typing import Callable, NamedTuple, Optional, Union

from markupsafe import Markup

from composeui.core.view import DownloadedFile, StreamContent

#: the most files kept for one session: the oldest goes past it
MAX_DOWNLOADS = 16
#: the most bytes kept in memory for one session: the oldest go past it. A file that the app
#: wrote (a `Path`) doesn't count: it stays on the disk
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
#: seconds a file is kept: a page that never fetches it (closed, or its answer lost) frees it
DOWNLOAD_TTL = 600.0
#: seconds a file is kept once fetched: a HEAD, or a browser's download manager, asks again
FETCHED_TTL = 60.0


class OpenedUrl(NamedTuple):
    """A URL that the app opens in a new tab of the page (`MainView.open_url`)."""

    url: str


class _Kept(NamedTuple):
    download: Union[DownloadedFile, OpenedUrl]
    #: when the app gave it, then when the page first fetched it
    added: float
    fetched: Optional[float] = None


class Downloads:
    """The files and URLs of one session by ticket, oldest first, until after their fetch."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._kept: dict[str, _Kept] = {}

    def add(self, download: Union[DownloadedFile, OpenedUrl]) -> str:
        """Keep `download` and get its ticket; drop the oldest past the limits."""
        self._drop_expired()
        ticket = secrets.token_urlsafe(16)
        self._kept[ticket] = _Kept(download, self._clock())
        while len(self._kept) > MAX_DOWNLOADS or self._size() > MAX_DOWNLOAD_BYTES:
            del self._kept[next(iter(self._kept))]
        return ticket

    def take(self, ticket: str, *, claim: bool = True) -> DownloadedFile | None:
        """Get the file of `ticket`; kept `FETCHED_TTL` from the first fetch, not named again.

        A `StreamContent` can be written once: the fetch that `claim`s it takes it, and the
        ticket is gone. A fetch that doesn't, e.g. a ``HEAD``, leaves it as it was. A URL's
        ticket gives None, and stays as it was.
        """
        self._drop_expired()
        kept = self._kept.get(ticket)
        if kept is None or not isinstance(kept.download, DownloadedFile):
            return None
        if isinstance(kept.download.content, StreamContent):
            if claim:
                del self._kept[ticket]
            return kept.download
        self._mark_fetched(ticket, kept)
        return kept.download

    def take_url(self, ticket: str) -> OpenedUrl | None:
        """Get the URL of `ticket`, as `take` gets a file; a file's ticket gives None."""
        self._drop_expired()
        kept = self._kept.get(ticket)
        if kept is None or not isinstance(kept.download, OpenedUrl):
            return None
        self._mark_fetched(ticket, kept)
        return kept.download

    def _mark_fetched(self, ticket: str, kept: _Kept) -> None:
        """Start the shorter timeout at the first fetch; later fetches don't extend it."""
        if kept.fetched is None:
            self._kept[ticket] = kept._replace(fetched=self._clock())

    def tickets(self) -> list[tuple[str, Union[DownloadedFile, OpenedUrl]]]:
        """Get the ticket of each file or URL not fetched yet, and it, the oldest first."""
        self._drop_expired()
        return [
            (ticket, kept.download) for ticket, kept in self._kept.items() if kept.fetched is None
        ]

    def _size(self) -> int:
        return sum(
            len(kept.download.content)
            for kept in self._kept.values()
            if isinstance(kept.download, DownloadedFile)
            and isinstance(kept.download.content, bytes)
        )

    def _drop_expired(self) -> None:
        now = self._clock()
        expired = [ticket for ticket, kept in self._kept.items() if _is_expired(kept, now)]
        for ticket in expired:
            del self._kept[ticket]


def _is_expired(kept: _Kept, now: float) -> bool:
    if kept.fetched is None:
        return now - kept.added > DOWNLOAD_TTL
    return now - kept.fetched > FETCHED_TTL


def downloads_marker(
    tickets: list[tuple[str, Union[DownloadedFile, OpenedUrl]]], *, oob: bool = False
) -> Markup:
    """Get the element naming the files the page fetches and the URLs it opens: a link each.

    Each answer that names a ticket carries it, until the page fetches it: an answer can be
    lost, or the page reloaded. The page's script follows each link once. A URL's link
    shows only if the browser refuses the new tab, a popup that no click opened: the user
    then clicks it.
    """
    swap = Markup(' hx-swap-oob="true"') if oob else Markup()
    links = Markup("").join(
        Markup(
            '<a href="/_composeui/open/{ticket}" target="_blank" rel="noopener"'
            ' data-ticket="{ticket}" data-open hidden class="alert alert-info link">{url}</a>'
        ).format(ticket=ticket, url=kept.url)
        if isinstance(kept, OpenedUrl)
        else Markup(
            '<a href="/_composeui/download/{ticket}" download="{name}" data-ticket="{ticket}"></a>'
        ).format(ticket=ticket, name=kept.filename)
        for ticket, kept in tickets
    )
    return Markup('<div id="cui-downloads"{} class="toast toast-end z-50" hidden>{}</div>').format(
        swap, links
    )
