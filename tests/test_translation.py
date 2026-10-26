"""Tests for translating views from JSON catalogs."""

from __future__ import annotations

import copy
import enum
import json
from typing import TYPE_CHECKING, Any, Optional

import attrs
import pytest
from attrs import Factory

from composeui.core.application import _add_reference_to_signals
from composeui.core.translation import T, TranslatedText, load_catalog, no_translation, translator
from composeui.core.view import (
    ButtonView,
    CellWidget,
    Column,
    GroupFormView,
    LabelRowComboboxView,
    LanguageMenu,
    MainView,
    PageView,
    RecordTableView,
    Router,
    TableView,
    child,
    define_view,
)
from tests.translated import Size, TranslatedMainView

if TYPE_CHECKING:
    from pathlib import Path


def test_a_regional_language_falls_back_on_its_base_language(tmp_path: Path) -> None:
    (tmp_path / "fr.json").write_text('{"Name": "Nom"}', encoding="utf-8")
    (tmp_path / "fr-CA.json").write_text('{"Size": "Grandeur"}', encoding="utf-8")

    assert load_catalog(tmp_path, "fr_BE") == {"Name": "Nom"}
    assert load_catalog(tmp_path, "fr_CA") == {"Size": "Grandeur"}
    assert load_catalog(tmp_path, "de") == {}


def test_the_first_catalog_wins_and_untranslated_text_shows_as_written(tmp_path: Path) -> None:
    app, library = tmp_path / "app", tmp_path / "library"
    app.mkdir()
    library.mkdir()
    (app / "fr.json").write_text('{"Save": "Sauvegarder"}', encoding="utf-8")
    (library / "fr.json").write_text('{"Save": "Enregistrer", "Open": "Ouvrir"}')

    translate = translator("fr", [app, library])

    assert [translate(text) for text in ("Save", "Open", "Exit")] == [
        "Sauvegarder",
        "Ouvrir",
        "Exit",
    ]


def test_text_translated_as_empty_is_still_to_translate(tmp_path: Path) -> None:
    app, library = tmp_path / "app", tmp_path / "library"
    app.mkdir()
    library.mkdir()
    (app / "fr.json").write_text('{"Save": "", "Name": ""}', encoding="utf-8")
    (library / "fr.json").write_text('{"Save": "Enregistrer"}', encoding="utf-8")

    translate = translator("fr", [app, library])

    assert [translate(text) for text in ("Save", "Name")] == ["Enregistrer", "Name"]


def test_a_catalog_not_mapping_text_to_text_is_refused(tmp_path: Path) -> None:
    (tmp_path / "fr.json").write_text('{"Size": 3}', encoding="utf-8")

    with pytest.raises(ValueError, match=r"fr\.json"):
        load_catalog(tmp_path, "fr")


def test_set_language_translates_every_view() -> None:
    view = TranslatedMainView()
    shape = view.shape

    assert view.language == "en"  # the source language, until set

    view.set_language("fr")

    assert view.language == "fr"
    assert shape.title == "Forme"
    assert shape.name.label == "Nom"
    assert shape.size.label == "Taille de la forme"  # the parent's text, not the row's
    assert view.confirm_remove.accept_text == "Supprimer"
    # ComposeUI's own text, from its catalog unless the app's translates it
    assert view.file_menu.title == "Fichier"
    assert view.file_menu.open_file.text == "Ouvrir"
    assert view.file_menu.save.text == "Sauvegarder"
    assert view.confirm_remove.reject_text == "Annuler"


def test_text_the_app_set_outside_retranslate_is_left_alone() -> None:
    view = TranslatedMainView()

    view.set_language("fr")

    assert view.confirm_discard.accept_text == "Discard"


def test_a_choice_keeps_its_value_when_its_labels_change() -> None:
    main_view = TranslatedMainView()
    size = main_view.shape.size
    seen: list[object] = []
    size.value_changed.connect(seen.append)

    main_view.set_language("fr")

    assert size.values == {"Petite": Size.SMALL, "Grande": Size.LARGE}
    assert size.value is Size.LARGE
    assert seen == []


def test_a_message_on_show_follows_the_language() -> None:
    view = TranslatedMainView()
    name = view.shape.name
    assert name.log_message == "A name is mandatory"

    view.set_language("fr")
    assert name.log_message == "Un nom est obligatoire"

    name.text = "Disc"
    name.run_validator()
    view.set_language("en")  # no catalog: as written in the code
    assert name.log_message == ""
    assert name.label == "Name"
    assert view.file_menu.title == "File"


def test_new_keeps_the_language() -> None:
    view = TranslatedMainView()
    _add_reference_to_signals(view, None)
    view.set_language("fr")
    view.shape.name.text = "Disc"
    view.shape.name.run_validator()

    view.file_menu.new.triggered.emit()

    assert view.shape.name.text == ""
    assert view.shape.name.log_message == "Un nom est obligatoire"
    assert view.shape.size.values == {"Petite": Size.SMALL, "Grande": Size.LARGE}
    assert view.file_menu.title == "Fichier"
    assert view.confirm_remove.accept_text == "Supprimer"


class Color(enum.Enum):
    RED = "Red"
    BLUE = "Blue"


@define_view
class ColorRowView(LabelRowComboboxView[Color]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.label = self.tr("Color")
        self.values = {self.tr(color.value): color for color in Color}
        self.value = Color.BLUE


@define_view
class PaletteView(GroupFormView):
    color: ColorRowView = Factory(ColorRowView)
    colors: TableView = Factory(TableView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Palette")
        self.colors.headers = [self.tr("Colors")]
        rows: list[list[str]] = [[self.tr(color.value)] for color in Color]
        self.colors.rows = [*rows, ["#00ff00"]]


def _palette_main_view(directory: Path) -> Any:
    """Build a main view setting its text with `tr` where it's built: no `retranslate`."""
    (directory / "fr.json").write_text(
        json.dumps(
            {
                "Palette": "Palette de couleurs",
                "Color": "Couleur",
                "Red": "Rouge",
                "Blue": "Bleu",
                "Colors": "Couleurs",
                "Picked {color}": "{color} choisie",
                "Untitled": "Sans titre",
            }
        ),
        encoding="utf-8",
    )

    @define_view
    class PaletteMainView(MainView):
        app_title = T("Untitled")
        extension = ".palette"
        translations_dir = directory

        palette: PaletteView = Factory(PaletteView)

        def __attrs_post_init__(self) -> None:
            super().__attrs_post_init__()
            self.palette.color.value_changed.connect(self.show_color)

        def show_color(self, color: Optional[Color]) -> None:
            if color is not None:
                message = self.tr("Picked {color}").format(color=self.tr(color.value))
                self.status_bar.show_message(message)

    main_view = PaletteMainView()
    main_view.status_bar.timeout = 0
    return main_view


def test_text_set_with_tr_where_the_view_is_built_follows_the_language(
    tmp_path: Path,
) -> None:
    main_view = _palette_main_view(tmp_path)
    palette = main_view.palette

    main_view.set_language("fr")

    assert palette.title == "Palette de couleurs"
    assert palette.color.label == "Couleur"
    assert palette.color.values == {"Rouge": Color.RED, "Bleu": Color.BLUE}
    assert palette.color.value is Color.BLUE
    assert palette.colors.headers == ["Couleurs"]
    assert palette.colors.rows == [["Rouge"], ["Bleu"], ["#00ff00"]]
    # set once by the app, but a language translates it
    assert main_view.title == "Sans titre"

    main_view.set_language("en")

    assert palette.title == "Palette"
    assert palette.colors.rows == [["Red"], ["Blue"], ["#00ff00"]]


def test_formatted_text_follows_the_language_with_its_arguments(tmp_path: Path) -> None:
    main_view = _palette_main_view(tmp_path)
    main_view.show_color(Color.RED)
    assert main_view.status_bar.message == "Picked Red"

    main_view.set_language("fr")
    assert main_view.status_bar.message == "Rouge choisie"

    main_view.set_language("en")
    assert main_view.status_bar.message == "Picked Red"


def test_text_made_from_a_translation_stays_in_its_language(tmp_path: Path) -> None:
    main_view = _palette_main_view(tmp_path)
    label = main_view.palette.color
    label.label = label.tr("Color") + ":"

    main_view.set_language("fr")

    assert label.label == "Color:"


def test_a_copied_translation_remembers_its_text() -> None:
    text = TranslatedText("Rouge {n}", "Red {n}").format(n=TranslatedText("un", "one"))

    for copied in (copy.copy(text), copy.deepcopy(text)):
        assert copied == "Rouge un"
        assert copied.translated(no_translation) == "Red one"


def test_new_keeps_the_language_of_text_set_where_the_view_is_built(tmp_path: Path) -> None:
    main_view = _palette_main_view(tmp_path)
    _add_reference_to_signals(main_view, None)
    main_view.set_language("fr")

    main_view.file_menu.new.triggered.emit()

    assert main_view.palette.title == "Palette de couleurs"
    assert main_view.palette.color.values == {"Rouge": Color.RED, "Bleu": Color.BLUE}


@define_view
class GalleryPage(PageView):
    route = "gallery"
    page_title = T("Gallery")

    shapes: TableView = child(TableView, headers=[T("Shape"), "#"])
    draw: ButtonView = child(ButtonView, text=T("Draw"))


@define_view
class GalleryRouter(Router):
    gallery: GalleryPage = Factory(GalleryPage)


def test_text_declared_in_the_class_bodies_follows_the_language(tmp_path: Path) -> None:
    catalog = {"Shapes": "Formes", "Shape": "Forme", "Draw": "Dessiner", "Gallery": "Galerie"}
    (tmp_path / "fr.json").write_text(json.dumps(catalog), encoding="utf-8")

    @define_view
    class GalleryMainView(MainView):
        app_title = T("Shapes")
        extension = ".shapes"
        translations_dir = tmp_path

        router: GalleryRouter = Factory(GalleryRouter)

    main_view = GalleryMainView()
    _add_reference_to_signals(main_view, None)
    page = main_view.router.gallery

    main_view.set_language("fr")

    assert (main_view.title, page.title) == ("Formes", "Galerie")
    assert (page.shapes.headers, page.draw.text) == (["Forme", "#"], "Dessiner")
    # a new study's views start in the language too
    main_view.file_menu.new.triggered.emit()
    assert (page.shapes.headers, page.draw.text) == (["Forme", "#"], "Dessiner")
    main_view.set_language("en")
    assert (main_view.title, page.title, page.draw.text) == ("Shapes", "Gallery", "Draw")


@attrs.define
class Run:
    name: str


@define_view
class RetryMainView(MainView):
    extension = ".retry"

    tasks: TableView = child(
        TableView, headers=[T("Task")], cell_widgets={0: CellWidget.button(T("Retry"))}
    )
    runs: RecordTableView[Run] = child(
        RecordTableView[Run],
        columns=[Column("name", T("Run"), widget=CellWidget.button(T("Retry")))],
    )


def test_a_cell_button_s_text_follows_the_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "fr.json").write_text(json.dumps({"Retry": "Relancer"}), encoding="utf-8")
    monkeypatch.setattr(RetryMainView, "translations_dir", tmp_path)
    main_view = RetryMainView()

    main_view.set_language("fr")

    assert main_view.tasks.cell_widgets[0].text == "Relancer"
    assert main_view.runs.cell_widgets[0].text == "Relancer"
    main_view.runs.columns = list(main_view.runs.columns)  # built again from the columns
    assert main_view.runs.cell_widgets[0].text == "Relancer"
    main_view.set_language("en")
    assert main_view.tasks.cell_widgets[0].text == "Retry"


def test_the_language_menu_offers_the_catalogs_languages(tmp_path: Path) -> None:
    for language in ("fr", "fr-CA", "eo"):
        (tmp_path / f"{language}.json").write_text("{}", encoding="utf-8")

    @define_view
    class LanguagesMainView(MainView):
        translations_dir = tmp_path

        language_menu: LanguageMenu = Factory(LanguageMenu)

    main_view = LanguagesMainView()
    _add_reference_to_signals(main_view, None)
    menu = main_view.language_menu

    # the source's first; a language with no name of its own is named by its code
    assert [action.text for action in menu.actions] == [
        "English",
        "eo",
        "Français",
        "Français (CA)",
    ]
    # "e" and "f" each start two languages: no shortcut picks one
    assert [action.shortcut for action in menu.actions] == [None] * 4
    assert "language_menu" not in main_view.state_data()  # how the app shows, not a study
    main_view.set_language("fr-CA")  # its own catalog: checked rather than French
    assert [action.is_checked for action in menu.actions] == [False, False, False, True]
    # a new study keeps the language, and the menu still switches it
    main_view.file_menu.new.triggered.emit()
    menu.action("fr").triggered.emit()
    assert main_view.language == "fr"
    assert [action.is_checked for action in menu.actions] == [False, False, True, False]
