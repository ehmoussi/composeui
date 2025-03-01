from composeui.mainview.interfaces.imainview import IMainView
from examples.figureview.batman import IBatmanView

from dataclasses import dataclass, field


@dataclass(eq=False)
class IExampleMainView(IMainView):
    batman: IBatmanView = field(init=False)
