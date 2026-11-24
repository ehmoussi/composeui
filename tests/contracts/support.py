"""What a driver does to a backend's widgets, as the user does."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from composeui.core.view import MainView, View


class Driver(Protocol):
    """Shows a main view on one backend and works its fields as the user does."""

    def open(self, main_view: MainView) -> AbstractAsyncContextManager[None]:
        """Render `main_view` and show it until the block ends."""
        ...

    async def type(self, view: View, text: str) -> None:
        """Put the focus in `view`'s field and replace its text with `text`."""
        ...

    async def leave(self, view: View) -> None:
        """Move the focus out of `view`'s field."""
        ...

    def shown_text(self, view: View) -> str:
        """Read the text that `view`'s field shows."""
        ...
