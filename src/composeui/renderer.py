from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from composeui.view import View


TView = TypeVar("TView", bound="View")
TObject = TypeVar("TObject")


class NoRenderedObjectError(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Cannot access rendered object because nothing has been rendered yet. "
            "Call `render()` first."
        )


class Renderer(ABC, Generic[TView, TObject]):
    def __init__(self, view: TView) -> None:
        self._view = view
        self._rendered_object: TObject | None = None

    @abstractmethod
    def render(self) -> None:
        """Render the view in the appropriate framework."""

    def refresh(self) -> None:
        """Refresh the framework view object using the view state."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        return self._refresh(self._view, self._rendered_object)

    def update_state(self) -> None:
        """Update the state of the view using framework view object."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        return self._update_state(self._view, self._rendered_object)

    @staticmethod
    @abstractmethod
    def _refresh(view: TView, rendered_object: TObject) -> None: ...
    @staticmethod
    @abstractmethod
    def _update_state(view: TView, rendered_object: TObject) -> None: ...
