"""The model: the app's data beside its views, saved and opened with them in a study."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from composeui.core.signal import Signal

if TYPE_CHECKING:
    from pathlib import Path

    from typing_extensions import Unpack

    from composeui.core.view import MainView

__all__ = ["InvalidStateError", "Model", "RefusedError"]


class InvalidStateError(ValueError):
    """A saved study that can't be opened; the views and the model are left unchanged."""


class RefusedError(Exception):
    """A change the model refused, changing nothing.

    Its message tells the user why, as written in the code (`View.refusing` translates it),
    or translated already by a view's `tr`.
    """


class PinnedData(Protocol):
    """A model's data as it was at an instant, to copy from another thread (`Model._pin_data`)."""

    def write(self, path: Path) -> None:
        """Write the pinned data into the file `path`, as `Model.save_data` does."""

    def release(self) -> None:
        """Release what pins the data; called once, written or not."""


class Model:
    """The app's data beside its views, given to the callbacks asking for `model`.

    A model with data of its own names its file in `data_name`. The study is then saved as
    an archive of the views' state and that file (see `composeui.core.study`). New, Open
    and Save reach the model through the methods below. Without a `data_name`, Save and
    Open don't call `save_data` and `open_data`, and the study stays the views' JSON.
    """

    #: the model's file inside a saved study; None for a model with nothing to save
    data_name: ClassVar[str | None] = None

    @property
    def signals(self) -> list[Signal[Unpack[tuple[Any, ...]]]]:
        """Get the model's signals: its attributes that are one, unless a subclass adds some.

        The app gives them the main view and the model, as it does the views' own signals. A
        callback that asks for `main_view` or `model` by name gets it.
        """
        return [value for value in vars(self).values() if isinstance(value, Signal)]

    @property
    def data_version(self) -> int:
        """Get a number that changes with every change of the data, 0 by default.

        `MainView.has_unsaved_changes` compares it with the one the study was saved with.
        A model with data of its own (`data_name`) changes it as its data changes:
        `DatabaseModel` counts its committed writes, but not those of the jobs started with
        the study (as the app starts, New, Open), which the next start makes again.
        """
        return 0

    def new(self) -> None:
        """Start the data of a new study."""

    def save_data(self, path: Path) -> None:
        """Write the data into the file `path`."""

    def open_data(self, path: Path) -> None:
        """Replace the data with the file `path`'s.

        Raises `InvalidStateError`, leaving the data unchanged, for a file that doesn't fit.
        """

    def _data_revision(self) -> int:
        """Get a number that changes with every change of the data, the study's start's too.

        An autosave copies the data again when it changed. `data_version` by default.
        """
        return self.data_version

    def _pin_data(self) -> PinnedData | None:
        """Pin the data as it is now, for an autosave's thread to copy; None if it can't.

        The autosave then calls `save_data` on the main thread instead.
        """
        return None

    def _set_main_view(self, main_view: MainView) -> None:
        """Know the main view of the model's session, which the app gives it once wired."""

    def loaded(self) -> None:
        """React once New or Open has put both the views and the data in place.

        `MainView.loaded` is emitted next, so the views' callbacks read the data in place.
        """

    def close(self) -> None:
        """Release what the data holds (files, connections); the app is done with it."""
