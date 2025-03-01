"""Dock View."""

from composeui.core.views.iview import IView

import enum
from dataclasses import dataclass, field


class DockArea(enum.IntFlag):
    LEFT = 1
    RIGHT = 2
    TOP = 4
    BOTTOM = 8


@dataclass(eq=False)
class IDockView(IView):
    title: str = field(init=False, default="")
    area: DockArea = field(init=False, default=DockArea.BOTTOM)
