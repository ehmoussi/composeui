"""Tests for checking catalogs against the text the code translates."""

import json
from pathlib import Path

import pytest

from composeui.core.translation import CATALOGS_DIR, load_catalog
from composeui.core.translationcheck import check_catalog, check_main_view, find_texts, main
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
