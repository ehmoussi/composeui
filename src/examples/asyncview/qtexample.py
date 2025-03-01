from composeui.form.qtformview import QtGroupBoxApplyFormView
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.asyncview.example import IExampleMainToolBar, IExampleMainView
from examples.asyncview.filereader import FileReaderItems, IFileReaderView

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, IExampleMainToolBar): ...


@dataclass(eq=False)
class QtFileReaderView(QtGroupBoxApplyFormView[FileReaderItems], IFileReaderView): ...


@dataclass(eq=False)
class QtExampleMainView(QtMainView, IExampleMainView):
    toolbar: QtExampleMainToolBar = field(init=False)
    file_reader: QtFileReaderView = field(init=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.toolbar = QtExampleMainToolBar(self.view)
        self.file_reader = QtFileReaderView()
        self.central_layout.addWidget(self.file_reader.view)
