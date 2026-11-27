"""A run's `.export` file in a text editor, shared by the backend tests of `TextEditorView`."""

from __future__ import annotations

from pathlib import Path

from attrs import Factory

from composeui.core.view import LanguageMenu, MainView, TextEditorView, child, define_view

#: the file's lines: "comm" twice on the second one, once on the third
EXPORT = "P actions make_etude\nF comm study.comm D 1\nF mess study.mess R 6\nP ncpus 2"


@define_view
class DeckMainView(MainView):
    app_title = "Deck"
    extension = ".deck"

    deck: TextEditorView = child(TextEditorView, text=EXPORT, export_filename="study.export")


#: a Code_Aster command file: Python, "mesh" twice
COMM = "mesh = LIRE_MAILLAGE(UNITE=20)\nmodel = AFFE_MODELE(MAILLAGE=mesh)"


@define_view
class CommMainView(MainView):
    """A command file in a text editor that colors its Python, in a language of a menu."""

    app_title = "Commands"
    extension = ".commands"
    translations_dir = Path(__file__).parent / "locales"  # French, ComposeUI's own text in it

    commands: TextEditorView = child(
        TextEditorView, text=COMM, export_filename="study.comm", language="python"
    )
    language_menu: LanguageMenu = Factory(LanguageMenu)
