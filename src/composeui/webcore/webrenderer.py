import html
from abc import abstractmethod
from typing import Any, Callable, Final, TypeVar

from composeui.core.renderer import Renderer
from composeui.core.view import MainView, StatusBar, View
from composeui.webcore.page import get_page

TView = TypeVar("TView", bound=View)


class WebRenderer(Renderer[TView, str]):
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = f"cui-{id(self._view)}"

    @abstractmethod
    def to_html(self) -> str: ...
    @staticmethod
    def _update_state(view: TView, rendered_object: str) -> None:
        pass


class WebStatusBarRenderer(WebRenderer[StatusBar]):
    def to_html(self) -> str:
        class_name = 'class="alert alert-info"'  # if self._view.message else ""
        return (
            f'<div id="{self._rendered_object}" {class_name}>'
            f"{html.escape(self._view.message)}"
            "</div>"
        )


class WebMainRenderer(WebRenderer[MainView]):
    def to_html(self) -> str:
        content = "".join(
            child_view.renderer.to_html()
            for child_view in self._view.children_views
            if isinstance(child_view.renderer, WebRenderer)
        )
        return get_page(self._view.title, content)


RENDERERS: Final[dict[str, Callable[[Any], Renderer[Any, Any]]]] = {
    "main": WebMainRenderer,
    "status_bar": WebStatusBarRenderer,
}
