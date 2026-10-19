"""Tests for checking catalogs against the text the code translates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from composeui.core.translation import CATALOGS_DIR, load_catalog
from composeui.core.translationcheck import (
    check_catalog,
    check_main_view,
    find_texts,
    main,
    write_catalog,
)
from composeui.core.view import define_view
from examples.pipeform import PipeMainView
from tests.translated import TranslatedMainView


def test_composeui_s_catalogs_translate_all_its_text() -> None:
    texts = find_texts((CATALOGS_DIR.parent / "core").glob("*.py"))
    assert {"File", "OK", "Can't open {name}: {error}."} <= texts

    for path in CATALOGS_DIR.glob("*.json"):
        report = check_catalog(path, texts, load_catalog(CATALOGS_DIR, path.stem))
        assert report.is_ok, report
        assert report.unused == [], report


def test_the_pipe_form_s_catalogs_translate_all_its_text() -> None:
    reports = check_main_view(PipeMainView)

    assert reports
    for report in reports:
        assert report.is_ok, report
        # the edge types and materials too: `tr` gets them from the enums
        assert report.unused == [], report


def test_a_catalog_s_missing_unused_and_mismatched_text_is_reported(tmp_path: Path) -> None:
    catalog = json.loads((Path(__file__).parent / "locales" / "fr.json").read_text("utf-8"))
    del catalog["Large"]
    catalog["Old text"] = "Vieux texte"
    catalog["A name is mandatory"] = "Un {nom} est obligatoire"
    (tmp_path / "fr.json").write_text(json.dumps(catalog), encoding="utf-8")

    @define_view
    class CheckedMainView(TranslatedMainView):
        translations_dir = tmp_path

    (report,) = check_main_view(CheckedMainView)

    assert not report.is_ok
    assert report.missing == ["Large"]  # not "Exit": ComposeUI's catalog translates it
    assert report.unused == ["Old text"]
    assert report.mismatched == [("A name is mandatory", "Un {nom} est obligatoire")]


def test_a_translation_that_isn_t_a_valid_format_is_mismatched(tmp_path: Path) -> None:
    report = check_catalog(
        tmp_path / "fr.json", {"{count} rooms"}, {"{count} rooms": "{count pièces"}
    )

    assert report.mismatched == [("{count} rooms", "{count pièces")]


def test_the_command_fails_only_on_a_catalog_that_isn_t_ok(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["tests.translated:TranslatedMainView"]) == 0
    assert "fr.json: 0 missing, 0 with other placeholders, 0 unused" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        main(["tests.translated:Unknown"])
    assert "isn't a class" in capsys.readouterr().err


def _checked_main_view(directory: Path) -> type[TranslatedMainView]:
    @define_view
    class CheckedMainView(TranslatedMainView):
        translations_dir = directory

    return CheckedMainView


_APP_TEXTS = [
    "A name is mandatory",
    "Large",
    "Name",
    "Remove",
    "Shape",
    "Shape size",
    "Size",
    "Small",
]


def test_a_new_catalog_gets_every_text_to_translate_as_empty(tmp_path: Path) -> None:
    directory = tmp_path / "locales"

    path, added = write_catalog(_checked_main_view(directory), "de")

    assert path == directory / "de.json"
    catalog = json.loads(path.read_text("utf-8"))
    # ComposeUI's text too: it has no German catalog
    assert {"File", "OK", "Can't open {name}: {error}."} <= set(catalog)
    assert set(_APP_TEXTS) <= set(catalog)
    assert set(catalog.values()) == {""}
    assert added == sorted(catalog)


def test_a_catalog_keeps_its_entries_and_gets_only_the_text_it_misses(tmp_path: Path) -> None:
    (tmp_path / "fr.json").write_text('{"Size": "Taille", "Old text": "Vieux texte"}', "utf-8")

    _, added = write_catalog(_checked_main_view(tmp_path), "fr")

    catalog = json.loads((tmp_path / "fr.json").read_text("utf-8"))
    # not "File": ComposeUI's French catalog translates it
    assert added == [text for text in _APP_TEXTS if text != "Size"]
    assert catalog == {
        "Size": "Taille",
        "Old text": "Vieux texte",
        **dict.fromkeys(added, ""),
    }
    assert list(catalog)[:2] == ["Size", "Old text"]
    assert write_catalog(_checked_main_view(tmp_path), "fr")[1] == []


def test_a_regional_catalog_starts_from_its_base_language_s(tmp_path: Path) -> None:
    (tmp_path / "fr.json").write_text('{"Size": "Taille"}', "utf-8")

    path, added = write_catalog(_checked_main_view(tmp_path), "fr-CA")

    assert path == tmp_path / "fr-CA.json"
    assert json.loads(path.read_text("utf-8"))["Size"] == "Taille"
    assert "Size" not in added


def test_text_translated_as_empty_is_missing(tmp_path: Path) -> None:
    report = check_catalog(tmp_path / "fr.json", {"{count} rooms"}, {"{count} rooms": ""})

    assert report.missing == ["{count} rooms"]
    assert report.mismatched == []


def test_the_command_writes_the_catalog_then_checks_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = tmp_path / "app_to_translate.py"
    module.write_text(
        "from pathlib import Path\n"
        "from composeui.core.view import define_view\n"
        "from tests.translated import TranslatedMainView\n"
        "@define_view\n"
        "class AppMainView(TranslatedMainView):\n"
        "    translations_dir = Path(__file__).parent / 'locales'\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        assert main(["app_to_translate:AppMainView", "--write", "fr"]) == 1
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("app_to_translate", None)

    out = capsys.readouterr().out
    assert "fr.json: 8 entries added to translate" in out
    assert "fr.json: 8 missing" in out
    assert (tmp_path / "locales" / "fr.json").is_file()
