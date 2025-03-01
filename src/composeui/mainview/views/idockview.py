"""Dock View."""

from composeui.core.views.iview import View

import enum
from dataclasses import dataclass, field


class DockArea(enum.IntFlag):
    LEFT = 1
    RIGHT = 2
    TOP = 4
    BOTTOM = 8


@dataclass(eq=False)
class DockView(View):
    title: str = field(init=False, default="")
    area: DockArea = field(init=False, default=DockArea.BOTTOM)
