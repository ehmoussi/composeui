"""A help page in Markdown, shared by the backend tests of `MarkdownView`."""

from attrs import Factory

from composeui.core.view import MainView, MarkdownView, define_view


@define_view
class HelpMainView(MainView):
    app_title = "Help"
    extension = ".help"

    help: MarkdownView = Factory(MarkdownView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.help.text = "# Help\n\n- Open a study\n- Run it\n"
