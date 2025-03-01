from composeui.core import study
from composeui.core.tasks import progresstask
from composeui.mainview import toolbar
from composeui.mainview.interfaces.ifileview import IFileView
from composeui.mainview.interfaces.imainview import IMainView
from composeui.mainview.interfaces.imenu import IFileMenu
from composeui.mainview.interfaces.imessageview import IMessageView, MessageViewType
from composeui.mainview.interfaces.iprogresspopupview import IProgressPopupView
from composeui.mainview.interfaces.itoolbar import ICheckableToolBar, IFileToolBar
from composeui.salomewrapper.mainview.isalomemainview import ISalomeMainView

from typing import Union


def initialize_main_view(view: IMainView) -> bool:
    """Initialize the main view."""
    view.is_visible = True
    title = str(type(view).__name__)
    if "MainView" in title:
        title = title.split("MainView")[0]
    elif "View" in title:
        title = title.split("View")[0]
    view.title = title
    view.extension_study = title.lower()
    view.message_before_closing = "Are you sure you want to exit the application ?"
    return True


def initialize_file_menu(view: IFileMenu) -> bool:
    r"""Initialize the file menu view."""
    view.title = "File"
    view.new.text = "New"
    view.new.icon = "new.png"
    view.new.shortcut = "Ctrl+n"
    view.open_file.text = "Open"
    view.open_file.icon = "open.png"
    view.open_file.shortcut = "Ctrl+o"
    view.save.text = "Save"
    view.save.icon = "save.png"
    view.save.shortcut = "Ctrl+s"
    view.save_as.text = "Save As"
    view.save_as.icon = "save_as.png"
    view.save_as.shortcut = "Ctrl+Shift+s"
    view.separator_exit.is_separator = True
    view.exit_app.text = "Exit"
    view.exit_app.icon = "exit.png"
    view.exit_app.shortcut = "Ctrl+q"
    return False


def initialize_file_toolbar(view: IFileToolBar) -> bool:
    r"""Initialize the file toolbar view."""
    view.is_visible = True
    view.is_always_visible = True
    view.title = "Study"
    view.new.text = "New"
    view.new.icon = "new.png"
    view.open_file.text = "Open"
    view.open_file.icon = "open.png"
    view.save.text = "Save"
    view.save.icon = "save.png"
    view.save_as.text = "Save As"
    view.save_as.icon = "save_as.png"
    return False


def initialize_progress_popup_view(view: IProgressPopupView, with_tasks: bool = True) -> bool:
    r"""Initialize the progress popup view."""
    view.is_visible = False
    view.title = "Work in progress ..."
    view.label_text = "Wait ..."
    if with_tasks:
        progresstask.update_progress_range(view, True)
    else:
        view.tasks = None
    return False


def initialize_message_view(view: IMessageView) -> bool:
    """Initialize the message view."""
    view.is_visible = False
    view.title = ""
    view.message = ""
    view.message_type = MessageViewType.critical
    return False


def initialize_file_view(view: IFileView) -> bool:
    """Initialize the file view."""
    view.filter_path = ""
    return False


def connect_main_view(main_view: IMainView) -> bool:
    main_view.save_before_exit = [study.save_before_exit]
    return True


def connect_file_menu(view: IFileMenu) -> bool:
    r"""Connect the signals of the menu view."""
    view.exit_app.triggered = [study.exit_app]
    return False


def connect_file_menu_toolbar(
    view: Union[IFileMenu, IFileToolBar], main_view: IMainView
) -> bool:
    r"""Connect the signals of the identical menu/toolbar actions."""
    view.new.triggered = [study.new]
    if isinstance(main_view, ISalomeMainView):
        view.open_file.triggered = [study.open_file_without_update]
    else:
        view.open_file.triggered = [study.open_file]
    view.save.triggered = [study.save]
    view.save_as.triggered = [study.save_as]
    return False


def connect_checkable_toolbar(view: ICheckableToolBar) -> bool:
    r"""Connect the signals of the menu view."""
    view.toggled = [toolbar.display]
    return False
