from composeui.core.views.view import View
from composeui.mainview.views.menu import FileMenu, Menu

from typing_extensions import OrderedDict

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(eq=False)
class BaseMainMenu(View):
    menus: Mapping[str, Menu] = field(init=False, default_factory=OrderedDict[str, Menu])


@dataclass(eq=False)
class MainMenu(View):
    file: FileMenu = field(init=False, default_factory=FileMenu)
