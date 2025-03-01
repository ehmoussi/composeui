from composeui.core.basesignal import BaseSignal
from composeui.core.views.iview import View
from composeui.mainview.views.ifileview import FileView
from composeui.mainview.views.imainmenu import MainMenu
from composeui.mainview.views.imaintoolbar import MainToolBar
from composeui.mainview.views.imessageview import MessageView
from composeui.mainview.views.iprogresspopupview import ProgressPopupView

from dataclasses import dataclass, field


@dataclass(eq=False)
class MainView(View):
    title: str = field(init=False, default="")
    extension_study: str = field(init=False, default="")
    closed: bool = field(init=False, default=False)
    force_close: bool = field(init=False, default=False)
    message_before_closing: str = field(init=False, default="")

    save_before_exit: BaseSignal = field(init=False, default=BaseSignal())
    update_all: BaseSignal = field(init=False, default=BaseSignal())

    menu: MainMenu = field(init=False, default_factory=MainMenu)
    toolbar: MainToolBar = field(init=False, default_factory=MainToolBar)
    message_view: MessageView = field(init=False, default_factory=MessageView)
    file_view: FileView = field(init=False, default_factory=FileView)
    progress_popup_view: ProgressPopupView = field(
        init=False, default_factory=ProgressPopupView
    )
