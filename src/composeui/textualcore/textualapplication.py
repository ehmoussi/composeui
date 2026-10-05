from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from composeui.core.application import Application, ModelApplication
from composeui.core.view import RendererType
from composeui.textualcore.textualrenderer import TextualMainRenderer

if TYPE_CHECKING:
    from composeui.core.model import Model
    from composeui.core.view import MainView


MainViewT = TypeVar("MainViewT", bound="MainView")
ModelT = TypeVar("ModelT", bound="Model")


class TextualApplication(Application[MainViewT]):
    def run(self) -> None:
        super().run()
        self.render(RendererType.TEXTUAL)
        if isinstance(self.main_view.renderer, TextualMainRenderer) and (
            self.main_view.renderer.app is not None
        ):
            self.main_view.renderer.app.run()


class TextualModelApplication(ModelApplication[MainViewT, ModelT]):
    def run(self) -> None:
        super().run()
        self.render(RendererType.TEXTUAL)
        try:
            if isinstance(self.main_view.renderer, TextualMainRenderer) and (
                self.main_view.renderer.app is not None
            ):
                self.main_view.renderer.app.run()
        finally:
            self.model.close()
