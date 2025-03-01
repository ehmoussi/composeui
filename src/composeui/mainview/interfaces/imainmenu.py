from composeui.core.views.iview import IView
from composeui.mainview.interfaces.imenu import IFileMenu, IMenu

from typing_extensions import OrderedDict

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(eq=False)
class IBaseMainMenu(IView):
    menus: Mapping[str, IMenu] = field(init=False, default_factory=OrderedDict[str, IMenu])


@dataclass(eq=False)
class IMainMenu(IView):
    file: IFileMenu = field(init=False, default_factory=IFileMenu)
