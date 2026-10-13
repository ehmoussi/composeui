"""Model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from composeui.core.signal import Signal

if TYPE_CHECKING:
    from pathlib import Path

    from typing_extensions import Unpack


class InvalidStateError(ValueError):
    """A saved study that can't be opened; the views and the model are left unchanged."""


class RefusedError(Exception):
    """A change the model refused, changing nothing.

    Its message tells the user why, as written in the code (`View.refusing` translates it),
    or translated already by a view's `tr`.
    """


class Model:
    """The app's data beside its views, given to the callbacks asking for `model`.

    A model with data of its own names its file in `data_name`: the study is then saved as
    an archive of the views' state and that file (see `composeui.core.study`), and New,
    Open and Save reach the model through the methods below. Without one, they do nothing
    and the study stays the views' JSON.
    """

    #: the model's file inside a saved study; None for a model with nothing to save
    data_name: ClassVar[str | None] = None

    @property
    def signals(self) -> list[Signal[Unpack[tuple[Any, ...]]]]:
        """Get the model's signals: its attributes that are one, unless a subclass adds some.

        The app gives them the main view and the model, as the views' own signals: a
        callback asking for `main_view` or `model` by name gets it.
        """
        return [value for value in vars(self).values() if isinstance(value, Signal)]

    def new(self) -> None:
        """Start the data of a new study."""

    def save_data(self, path: Path) -> None:
        """Write the data into the file `path`."""

    def open_data(self, path: Path) -> None:
        """Replace the data with the file `path`'s.

        Raises `InvalidStateError`, leaving the data unchanged, for a file that doesn't fit.
        """

    def loaded(self) -> None:
        """React once New or Open has put both the views and the data in place."""

    def close(self) -> None:
        """Release what the data holds (files, connections); the app is done with it."""
