"""The files that a session's app gives its user (`MainView.download`), until the page fetches them.

The app makes a file while it handles a request, or in a job's callback, which no request
answers. So the session keeps the file under a ticket, a name that can't be guessed, and each
answer to the page names the tickets kept (`downloads_marker`). The page's script fetches each
ticket once, from `GET /download/{ticket}`, which only reads: the app's code never runs there.
"""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Callable, NamedTuple, Union

from markupsafe import Markup

if TYPE_CHECKING:
    from pathlib import Path

#: the most files kept for one session: the oldest goes past it
MAX_DOWNLOADS = 16
#: the most bytes kept in memory for one session: the oldest go past it. A file that the app
#: wrote (a `Path`) doesn't count: it stays on the disk
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
#: seconds a file is kept: a page that never fetches it (closed, or its answer lost) frees it
DOWNLOAD_TTL = 600.0


class Download(NamedTuple):
    """A file that the app gives its user: its name, its content and its media type."""

    filename: str
    content: Union[bytes, Path]
    media_type: str


class Downloads:
    """The files of one session not fetched yet, by ticket, the oldest first."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._kept: dict[str, tuple[float, Download]] = {}

    def add(self, download: Download) -> str:
        """Keep `download` and get its ticket; drop the oldest past the limits."""
        self._drop_expired()
        ticket = secrets.token_urlsafe(16)
        self._kept[ticket] = (self._clock(), download)
        while len(self._kept) > MAX_DOWNLOADS or self._size() > MAX_DOWNLOAD_BYTES:
            del self._kept[next(iter(self._kept))]
        return ticket

    def take(self, ticket: str) -> Download | None:
        """Get the file of `ticket` and forget it: a ticket gives its file once."""
        self._drop_expired()
        kept = self._kept.pop(ticket, None)
        return None if kept is None else kept[1]

    def tickets(self) -> list[tuple[str, str]]:
        """Get the ticket and the file name of each file kept, the oldest first."""
        self._drop_expired()
        return [(ticket, download.filename) for ticket, (_, download) in self._kept.items()]

    def _size(self) -> int:
        return sum(
            len(download.content)
            for _, download in self._kept.values()
            if isinstance(download.content, bytes)
        )

    def _drop_expired(self) -> None:
        now = self._clock()
        for ticket in [t for t, (added, _) in self._kept.items() if now - added > DOWNLOAD_TTL]:
            del self._kept[ticket]


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
