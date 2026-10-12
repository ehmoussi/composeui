"""Tests for translating views from JSON catalogs."""

from pathlib import Path

import pytest

from composeui.core.application import _add_reference_to_signals
from composeui.core.translation import load_catalog, translator
from tests.translated import Size, TranslatedMainView


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
