from composeui.core.basesignal import BaseSignal
from composeui.core.interfaces.iview import IView
from composeui.mainview.interfaces.ifileview import IFileView
from composeui.mainview.interfaces.imainmenu import IMainMenu
from composeui.mainview.interfaces.imaintoolbar import IMainToolBar
from composeui.mainview.interfaces.imessageview import IMessageView
from composeui.mainview.interfaces.iprogresspopupview import IProgressPopupView

from dataclasses import dataclass, field


@dataclass(eq=False)
class IMainView(IView):
    title: str = field(init=False, default="")
    extension_study: str = field(init=False, default="")
    closed: bool = field(init=False, default=False)
    force_close: bool = field(init=False, default=False)
    message_before_closing: str = field(init=False, default="")

    save_before_exit: BaseSignal = field(init=False, default=BaseSignal())
    update_all: BaseSignal = field(init=False, default=BaseSignal())

    menu: IMainMenu = field(init=False, default_factory=IMainMenu)
    toolbar: IMainToolBar = field(init=False, default_factory=IMainToolBar)
    message_view: IMessageView = field(init=False, default_factory=IMessageView)
    file_view: IFileView = field(init=False, default_factory=IFileView)
    progress_popup_view: IProgressPopupView = field(
        init=False, default_factory=IProgressPopupView
    )
