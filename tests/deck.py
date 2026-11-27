"""A run's `.export` file in a text editor, shared by the backend tests of `TextEditorView`."""

from __future__ import annotations

from composeui.core.view import MainView, TextEditorView, child, define_view

#: the file's lines: "comm" twice on the second one, once on the third
EXPORT = "P actions make_etude\nF comm study.comm D 1\nF mess study.mess R 6\nP ncpus 2"


@define_view
class DeckMainView(MainView):
    app_title = "Deck"
    extension = ".deck"

    deck: TextEditorView = child(TextEditorView, text=EXPORT, export_filename="study.export")
