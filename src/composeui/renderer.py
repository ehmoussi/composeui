from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

    from composeui.view import View


TView = TypeVar("TView", bound="View")
TObject = TypeVar("TObject")


class NoRenderedObjectError(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Cannot access rendered object because nothing has been rendered yet. "
            "Call `render()` first."
        )


class MissingRefreshAttributeFunctionError(Exception):
    def __init__(self, renderer: Renderer[Any, Any], attr_name: str) -> None:
        super().__init__(
            f"The attribute {attr_name} don't have a corresponding "
            f"refresh function in {type(renderer)}"
        )


class Renderer(ABC, Generic[TView, TObject]):
    def __init__(self, view: TView) -> None:
        self._view = view
        self._rendered_object: TObject | None = None
        self._refresh_dispatcher: dict[str, Callable[[TView, TObject, Any], None]] = {}

    @abstractmethod
    def render(self) -> None:
        """Render the view in the appropriate framework."""

    def refresh(self) -> None:
        """Refresh the framework view object using the view state."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        for attr_name in self._refresh_dispatcher:
            if not hasattr(self._view, attr_name):
                msg = (
                    f"{attr_name} is not an attribute of the view "
                    f"{type(self._view).__name__}"
                )
                raise AttributeError(msg)
            refresh = self._refresh_dispatcher[attr_name]
            value = getattr(self._view, attr_name)
            refresh(self._view, self._rendered_object, value)

    def refresh_attribute(self, attr_name: str, value: Any) -> None:
        """Refresh the framework view object using the view state."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        if hasattr(self._view, attr_name):
            if attr_name in self._refresh_dispatcher:
                refresh = self._refresh_dispatcher[attr_name]
                refresh(self._view, self._rendered_object, value)
            else:
                raise MissingRefreshAttributeFunctionError(self, attr_name)
        else:
            msg = f"{attr_name} is not an attribute of the view {type(self._view)}"
            raise AttributeError(msg)

    def update_state(self) -> None:
        """Update the state of the view using framework view object."""
        if self._rendered_object is None:
            raise NoRenderedObjectError
        return self._update_state(self._view, self._rendered_object)

    @staticmethod
    @abstractmethod
    def _update_state(view: TView, rendered_object: TObject) -> None: ...
