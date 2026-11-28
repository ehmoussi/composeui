"""What a driver does to a backend's widgets, as the user does."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from composeui.core.view import MainView, View


class Driver(Protocol):
    """Shows a main view on one backend and works its fields as the user does."""

    def open(self, main_view: MainView) -> AbstractAsyncContextManager[None]:
        """Render `main_view` and show it until the block ends."""
        ...

    def by_code(self) -> AbstractAsyncContextManager[None]:
        """Make the block's changes as code, then handle what the backend posted for them.

        A widget's report of a change by code can come late, in a message: it comes before
        the test reads what was reported.
        """
        ...

    async def wait_until(self, condition: Callable[[], bool]) -> None:
        """Handle what the backend's threads post until `condition` holds; fail after 10 s.

        For work that another thread hands the main thread, such as a repeating task's run.
        """
        ...

    async def type(self, view: View, text: str, *, part: int = 0) -> None:
        """Put the focus in `view`'s field and replace its text with `text`.

        A line break of `text` is a key, as Enter. `part` is the field's text box: of a
        date range, 0 the start and 1 the end.
        """
        ...

    async def leave(self, view: View) -> None:
        """Move the focus out of `view`'s field."""
        ...

    def shown_text(self, view: View, *, part: int = 0) -> str:
        """Read the text that `view`'s field shows, in its text box `part`."""
        ...

    def edits(self, text: str) -> list[str]:
        """Get the texts that typing `text` reports, each once: each key's, or one post's."""
        ...

    async def toggle(self, view: View) -> None:
        """Check `view`'s box, or uncheck it."""
        ...

    def is_checked(self, view: View) -> bool:
        """Read whether `view`'s box shows checked."""
        ...

    async def slide(self, view: View, end: Literal["start", "end"]) -> None:
        """Move `view`'s handle to the start of the track, or to its end, by key.

        On a range, the key moves the handle on that side.
        """
        ...

    def slider_text(self, view: View) -> str:
        """Read the value that `view`'s slider shows beside its track."""
        ...

    async def pick(self, view: View, label: str) -> None:
        """Pick the choice `label` of `view`'s radio buttons or drop-down list.

        A driver that picks by keys moves from the choice that `view` shows.
        """
        ...

    def chosen(self, view: View) -> Optional[str]:
        """Read the label of the choice that `view` shows picked, None for none."""
        ...

    async def search(self, view: View, text: str) -> None:
        """Replace the text of `view`'s search field with `text`."""
        ...

    async def check(self, view: View, label: str) -> None:
        """Check the box of the choice `label` of `view`, or uncheck it.

        Of a drop-down list, in its list, opened first.
        """
        ...

    def checks(self, view: View) -> list[tuple[str, bool]]:
        """Read the choices that `view`'s list shows: each one's label, and if it's checked."""
        ...

    def check_all_state(self, view: View) -> Optional[bool]:
        """Read whether `view`'s check-all box shows checked, unchecked, or partly (None)."""
        ...

    async def select_node(self, view: View, labels: tuple[str, ...]) -> None:
        """Select the node of `view`'s tree down `labels`, from a top-level node."""
        ...

    async def toggle_node(self, view: View, labels: tuple[str, ...]) -> None:
        """Expand the node of `view`'s tree down `labels`, or collapse it, by its arrow."""
        ...

    def selected_node(self, view: View) -> Optional[tuple[str, ...]]:
        """Read the labels down to the node that `view`'s tree shows selected, None for none."""
        ...

    def expanded_nodes(self, view: View) -> list[tuple[str, ...]]:
        """Read the labels down to each node that `view`'s tree shows expanded, in order."""
        ...
