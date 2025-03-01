from composeui.mainview.views.imainview import MainView
from examples.figureview.batman import BatmanView

from dataclasses import dataclass, field


@dataclass(eq=False)
class ExampleMainView(MainView):
    batman: BatmanView = field(init=False)
