"""The files that a session's app gives its user (`MainView.download`), until the page fetches them.

The app makes a file while it handles a request, or in a job's callback, which no request
answers. So the session keeps the file under a ticket, a name that can't be guessed, and each
answer to the page names the tickets not fetched yet (`downloads_marker`). The page's script
fetches each once, from `GET /download/{ticket}`, which only reads: the app's code never runs
there.
"""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Callable, NamedTuple, Optional

from markupsafe import Markup

if TYPE_CHECKING:
    from composeui.core.view import DownloadedFile

#: the most files kept for one session: the oldest goes past it
MAX_DOWNLOADS = 16
#: the most bytes kept in memory for one session: the oldest go past it. A file that the app
#: wrote (a `Path`) doesn't count: it stays on the disk
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
#: seconds a file is kept: a page that never fetches it (closed, or its answer lost) frees it
DOWNLOAD_TTL = 600.0
#: seconds a file is kept once fetched: a HEAD, or a browser's download manager, asks again
FETCHED_TTL = 60.0


class _Kept(NamedTuple):
    download: DownloadedFile
    #: when the app gave it, then when the page first fetched it
    added: float
    fetched: Optional[float] = None


class Downloads:
    """The files of one session, by ticket, the oldest first, until a while after their fetch."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._kept: dict[str, _Kept] = {}

    def add(self, download: DownloadedFile) -> str:
        """Keep `download` and get its ticket; drop the oldest past the limits."""
        self._drop_expired()
        ticket = secrets.token_urlsafe(16)
        self._kept[ticket] = _Kept(download, self._clock())
        while len(self._kept) > MAX_DOWNLOADS or self._size() > MAX_DOWNLOAD_BYTES:
            del self._kept[next(iter(self._kept))]
        return ticket

    def take(self, ticket: str) -> DownloadedFile | None:
        """Get the file of `ticket`; kept `FETCHED_TTL` from the first fetch, not named again."""
        self._drop_expired()
        kept = self._kept.get(ticket)
        if kept is None:
            return None
        if kept.fetched is None:
            self._kept[ticket] = kept._replace(fetched=self._clock())
        return kept.download

    def tickets(self) -> list[tuple[str, str]]:
        """Get the ticket and the file name of each file not fetched yet, the oldest first."""
        self._drop_expired()
        return [
            (ticket, kept.download.filename)
            for ticket, kept in self._kept.items()
            if kept.fetched is None
        ]

    def _size(self) -> int:
        return sum(
            len(kept.download.content)
            for kept in self._kept.values()
            if isinstance(kept.download.content, bytes)
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


def downloads_marker(tickets: list[tuple[str, str]], *, oob: bool = False) -> Markup:
    """Get the element naming the files the page fetches: a link per ticket.

    Each answer that names a ticket carries it, until the page fetches it: an answer can be
    lost, or the page reloaded. The page's script follows each link once.
    """
    swap = Markup(' hx-swap-oob="true"') if oob else Markup()
    links = Markup("").join(
        Markup('<a href="/download/{ticket}" download="{name}" data-ticket="{ticket}"></a>').format(
            ticket=ticket, name=name
        )
        for ticket, name in tickets
    )
    return Markup('<div id="cui-downloads"{} hidden>{}</div>').format(swap, links)
