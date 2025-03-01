"""Definition of the app for the async view example."""

from composeui import get_version
from composeui.apps.qtbaseapp import QtBaseApp
from composeui.model.mashumaromodel import MashumaroModel
from examples.asyncview.example import ExampleMainView, initialize_navigation
from examples.asyncview.filereader import connect_file_reader, initialize_file_reader

from mashumaro.mixins.json import DataClassJSONMixin
from typing_extensions import TypeAlias

from dataclasses import dataclass


@dataclass
class FileReaderConfig(DataClassJSONMixin):
    filepath: str = ""
    delay: int = 8
    content: str = ""
    output_filepath: str = ""


Model: TypeAlias = MashumaroModel[FileReaderConfig]


class AsyncViewApp(QtBaseApp[ExampleMainView, Model]):
    def __init__(self, main_view: ExampleMainView) -> None:
        super().__init__(
            MashumaroModel("example", get_version("composeui"), FileReaderConfig()),
            main_view,
        )

    def initialize_app(self) -> None:
        initialize_navigation(view=self.main_view.toolbar.navigation)
        initialize_file_reader(view=self.main_view.file_reader, model=self.model)

    def connect_app(self) -> None:
        connect_file_reader(view=self.main_view.file_reader)
