from composeui.core.basesignal import BaseSignal
from composeui.core.views.ipendingview import IPendingView
from composeui.core.views.iview import IGroupView

import typing
from dataclasses import dataclass, field
from typing import Optional

if typing.TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


@dataclass(eq=False)
class IFigureView(IPendingView):
    figure: Optional["Figure"] = field(init=False, default=None)
    has_toolbar: bool = field(init=False, default=False)
    last_clicked_axes: Optional["Axes"] = field(init=False, default=None)
    x_last_clicked: Optional[float] = field(init=False, default=None)
    y_last_clicked: Optional[float] = field(init=False, default=None)
    clicked: BaseSignal = field(init=False, default=BaseSignal())


@dataclass(eq=False)
class IFigureGroupView(IFigureView, IGroupView): ...
