"""A page's posts, handled in the order the page sent them.

A page sends each request as the user acts, from the control the user used: a field's
value as it loses the focus, then the click on the button that took the focus. Both may
reach the server in the other order, and the click would see the old value. The page
numbers its posts (`page.js`), and each one waits here for the one before it.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

#: the headers of a post: its page's id, made as the page loads, and its number there, from 1
PAGE_HEADER = "X-ComposeUI-Page"
POST_HEADER = "X-ComposeUI-Post"
#: the same, as the fields of a form the page submits itself, such as Save's: no headers
PAGE_FIELD = "page"
POST_FIELD = "post"
#: seconds a post waits for the one before it, which may never come: e.g. aborted
ORDER_TIMEOUT = 2.0
#: the pages a session keeps the order of; past them, the one used least recently is
#: forgotten, e.g. a page reloaded since: one of its posts would wait for nothing
MAX_PAGES = 32
_PAGE_PATTERN = re.compile(r"[0-9a-f]{32}")
_POST_PATTERN = re.compile(r"[1-9][0-9]{0,8}")


class PostOrder:
    """The order of a session's posts: the next number to handle, for each of its pages."""

    def __init__(self) -> None:
        self._next: OrderedDict[str, int] = OrderedDict()
        # made in the event loop, by the first post that waits its turn
        self._turn: asyncio.Condition | None = None

    @contextlib.asynccontextmanager
    async def turn(self, headers: Mapping[str, str]) -> AsyncIterator[None]:
        """Wait for the turn of the post with `headers`, then let the block handle it.

        At most `ORDER_TIMEOUT`: then the post is handled anyway. A post without the
        headers, or with invalid ones, has no turn to wait for.
        """
        post = _post(headers)
        if post is None:
            yield
            return
        page, number = post
        if self._turn is None:
            self._turn = asyncio.Condition()
        turn = self._turn
        if page not in self._next:
            self._keep(page, 1)
        self._next.move_to_end(page)
        async with turn:
            # a page forgotten meanwhile has no turn to wait for
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    turn.wait_for(lambda: self._next.get(page, number) >= number), ORDER_TIMEOUT
                )
        try:
            yield
        finally:
            async with turn:
                # one handled after its turn timed out leaves the later ones' turns
                self._keep(page, max(self._next.get(page, 1), number + 1))
                turn.notify_all()

    def _keep(self, page: str, number: int) -> None:
        self._next[page] = number
        if len(self._next) > MAX_PAGES:
            self._next.popitem(last=False)


def form_order(form: Mapping[str, object]) -> dict[str, str]:
    """Get the headers of a post submitted as a form, from its fields (see `PAGE_FIELD`)."""
    fields = {PAGE_HEADER: form.get(PAGE_FIELD), POST_HEADER: form.get(POST_FIELD)}
    return {name: value for name, value in fields.items() if isinstance(value, str)}


def _post(headers: Mapping[str, str]) -> tuple[str, int] | None:
    """Get a post's page and number from its `headers`; None without both, or invalid."""
    page = headers.get(PAGE_HEADER, "")
    number = headers.get(POST_HEADER, "")
    if _PAGE_PATTERN.fullmatch(page) is None or _POST_PATTERN.fullmatch(number) is None:
        return None
    return page, int(number)
