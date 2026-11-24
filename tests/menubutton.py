"""A row with a menu button beside a button, shared by the backend tests of menu buttons."""

from __future__ import annotations

from attrs import Factory
from typing_extensions import override

from composeui.core.view import (
    ActionView,
    Align,
    ButtonView,
    HorizontalView,
    LabelView,
    MainView,
    MenuButtonView,
    SeparatorAction,
    define_view,
)


@define_view
class MoreButton(MenuButtonView):
    reload: ActionView = Factory(ActionView)
    preview: ActionView = Factory(ActionView)
    separator: SeparatorAction = Factory(SeparatorAction)
    wrap: ActionView = Factory(ActionView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.text = "More"
        self.reload.text = "Reload"
        self.reload.shortcut = "Ctrl+r"
        self.preview.text = "Preview"
        self.wrap.text = "Wrap"


@define_view
class StudyActions(HorizontalView):
    """Packed at the row's end, as actions often are: on a phone, its list must open leftward."""

    align = Align.END
    export: ButtonView = Factory(ButtonView)
    more: MoreButton = Factory(MoreButton)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.export.text = "Export"


@define_view
class MenuButtonMainView(MainView):
    app_title = "Menu button"
    has_file_menu = False

    actions: StudyActions = Factory(StudyActions)
    last: LabelView = Factory(LabelView)

    @override
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        more = self.actions.more
        more.reload.triggered.connect(self._reload)
        more.preview.triggered.connect(self._preview)

    def _reload(self) -> None:
        self.last.text = "Reloaded"

    def _preview(self) -> None:
        self.last.text = "Previewed"
