from composeui.form.qtformview import QtGroupBoxApplyFormView
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.asyncview.example import IExampleMainToolBar, IExampleMainView
from examples.asyncview.filereader import FileReaderItems, IFileReaderView

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainToolBar(QtMainToolBar, IExampleMainToolBar): ...


@dataclass(eq=False)
class FileReaderView(QtGroupBoxApplyFormView[FileReaderItems], IFileReaderView): ...


@dataclass(eq=False)
class ExampleMainView(QtMainView, IExampleMainView):
    toolbar: ExampleMainToolBar = field(init=False)
    file_reader: FileReaderView = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.toolbar = ExampleMainToolBar(self.view)
        self.file_reader = FileReaderView()
        self.central_layout.addWidget(self.file_reader.view)
