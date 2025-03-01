from composeui.form.formview import GroupBoxApplyFormView
from composeui.mainview.qt.maintoolbar import MainToolBar
from composeui.mainview.qt.mainview import MainView
from examples.asyncview.example import IExampleMainToolBar, IExampleMainView
from examples.asyncview.filereader import FileReaderItems, IFileReaderView

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainToolBar(MainToolBar, IExampleMainToolBar): ...


@dataclass(eq=False)
class FileReaderView(GroupBoxApplyFormView[FileReaderItems], IFileReaderView): ...


@dataclass(eq=False)
class ExampleMainView(MainView, IExampleMainView):
    toolbar: ExampleMainToolBar = field(init=False)
    file_reader: FileReaderView = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.toolbar = ExampleMainToolBar(self.view)
        self.file_reader = FileReaderView()
        self.central_layout.addWidget(self.file_reader.view)
