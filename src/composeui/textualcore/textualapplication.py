"""The application classes of the Textual backend."""

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
    """The Textual app: it shows the main view in the terminal."""

    def run(self) -> None:
        super().run()
        self.render(RendererType.TEXTUAL)
        if isinstance(self.main_view.renderer, TextualMainRenderer) and (
            self.main_view.renderer.app is not None
        ):
            self.main_view.renderer.app.run()


class TextualModelApplication(ModelApplication[MainViewT, ModelT]):
    """The Textual app with a model, which it closes once the app exits."""

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


#: the backend's applications, for `composeui.core.application.run`
APPLICATION = TextualApplication
MODEL_APPLICATION = TextualModelApplication
