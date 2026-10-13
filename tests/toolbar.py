"""A toolbar above a router's pages, shared by the backend tests of toolbars."""

from attrs import Factory

from composeui.core.view import (
    ActionView,
    MainView,
    OpenFileAction,
    SeparatorAction,
    ToolBar,
    define_view,
)
from tests.pages import PagesRouter


@define_view
class EditToolBar(ToolBar):
    open_file: OpenFileAction = Factory(OpenFileAction)
    separator: SeparatorAction = Factory(SeparatorAction)
    run: ActionView = Factory(ActionView)
    wrap: ActionView = Factory(ActionView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = "Edit"
        self.run.text = "Run"
        self.run.shortcut = "Ctrl+r"
        self.wrap.text = "Wrap"
        self.wrap.is_checkable = True


@define_view
class ToolBarMainView(MainView):
    app_title = "Toolbar"
    extension = ".toolbar"

    toolbar: EditToolBar = Factory(EditToolBar)
    router: PagesRouter = Factory(PagesRouter)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        # the File menu's Open, from the toolbar
        self.toolbar.open_file.triggered.connect(self.file_menu.open_file.triggered.emit)
        self.toolbar.run.triggered.connect(self._run)

    def _run(self) -> None:
        self.router.results.total.text = "Ran"
