"""A study picked among the server's files, shared by the backend tests of `server_roots`."""

from __future__ import annotations

from pathlib import Path

from composeui.core.view import LabelRowFilePathInputView, MainView, child, define_view


@define_view
class StudyFileMainView(MainView):
    """Its field lists the files of this folder, until a test gives it roots of its own."""

    app_title = "Study file"
    extension = ".studyfile"

    study: LabelRowFilePathInputView = child(
        LabelRowFilePathInputView,
        label="Study",
        extensions={"Python": (".py",)},
        server_roots=(Path(__file__).parent,),
    )
