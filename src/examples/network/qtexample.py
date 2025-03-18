from composeui.form.qtformview import QtGroupBoxApplyFormView
from composeui.mainview.qt.qtmaintoolbar import QtMainToolBar
from composeui.mainview.qt.qtmainview import QtMainView
from examples.network.example import ExampleMainToolBar, ExampleMainView
from examples.network.llm import LLMItems, LLMView

from dataclasses import dataclass, field


@dataclass(eq=False)
class QtExampleMainToolBar(QtMainToolBar, ExampleMainToolBar): ...


@dataclass(eq=False)
class QtLLMView(QtGroupBoxApplyFormView[LLMItems], LLMView):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.conversation.field_view.view.setMinimumHeight(400)  # type: ignore[attr-defined]


@dataclass(eq=False)
class QtExampleMainView(QtMainView, ExampleMainView):
    toolbar: QtExampleMainToolBar = field(init=False, repr=False)
    llm: QtLLMView = field(init=False, repr=False)

    def __post_init__(self, with_app: bool) -> None:
        super().__post_init__(with_app)
        self.toolbar = QtExampleMainToolBar(self.view)
        self.llm = QtLLMView()
        self.central_layout.addWidget(self.llm.view)
