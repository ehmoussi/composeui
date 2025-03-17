from composeui.core.basesignal import BaseSignal
from composeui.core.views.view import View
from composeui.mainview.views.fileview import FileView
from composeui.mainview.views.mainmenu import MainMenu
from composeui.mainview.views.maintoolbar import MainToolBar
from composeui.mainview.views.messageview import MessageView
from composeui.mainview.views.progresspopupview import ProgressPopupView
from composeui.network.networkview import NetworkView

from dataclasses import dataclass, field


@dataclass(eq=False)
class MainView(View):
    title: str = field(init=False, default="")
    extension_study: str = field(init=False, default="")
    closed: bool = field(init=False, default=False)
    force_close: bool = field(init=False, default=False)
    message_before_closing: str = field(init=False, default="")

    on_start: BaseSignal = field(init=False, repr=False, default=BaseSignal())
    save_before_exit: BaseSignal = field(init=False, repr=False, default=BaseSignal())
    update_all: BaseSignal = field(init=False, repr=False, default=BaseSignal())

    menu: MainMenu = field(init=False, repr=False, default_factory=MainMenu)
    toolbar: MainToolBar = field(init=False, repr=False, default_factory=MainToolBar)
    message_view: MessageView = field(init=False, repr=False, default_factory=MessageView)
    file_view: FileView = field(init=False, repr=False, default_factory=FileView)
    progress_popup_view: ProgressPopupView = field(
        init=False, repr=False, default_factory=ProgressPopupView
    )
    network_view: NetworkView = field(init=False, repr=False, default_factory=NetworkView)
