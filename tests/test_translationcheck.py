"""Tests for checking catalogs against the text the code translates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from composeui.core.translation import CATALOGS_DIR, load_catalog
from composeui.core.translationcheck import (
    check_catalog,
    check_main_view,
    find_texts,
    main,
    write_catalog,
)
from composeui.core.view import define_view
from examples import pipecatalogue
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


class _Recorded:
    """A value to format, which records its name in `used` when it is formatted."""

    def __init__(self, name: str, used: set[str]) -> None:
        self.name, self.used = name, used

    def __format__(self, spec: str) -> str:
        self.used.add(self.name)
        return "x"

    def __repr__(self) -> str:
        self.used.add(self.name)
        return "x"

    def __getattr__(self, attribute: str) -> _Recorded:  # `{name.real}`: still its value
        return self

    def __getitem__(self, key: object) -> _Recorded:  # `{name[0]}`
        return self


def _used(text: str) -> set[str] | None:
    """Get the values `text` formats, as `str.format` does; None if it fails."""
    used: set[str] = set()
    positional = [_Recorded(str(index), used) for index in range(3)]
    named = {name: _Recorded(name, used) for name in ("name", "count", "width")}
    try:
        text.format(*positional, **named)
    except (ValueError, IndexError, KeyError):
        return None
    return used


#: a text's pieces: words, values by name or position, in a format, escaped braces
_PIECES = st.sampled_from(
    [
        "a ",
        " é",
        "{name}",
        "{count}",
        "{}",
        "{0}",
        "{1}",
        "{name!r}",
        "{count:>3}",
        "{{",
        "}}",
        "{name.real}",
        "{name[0]}",
        "{count:{width}}",
        "{:{}}",
    ]
)


@st.composite
def _translated(draw: st.DrawFn) -> tuple[str, str]:
    """Draw a text and a translation: its pieces moved, one repeated, left out or added."""
    pieces = draw(st.lists(_PIECES, max_size=4))
    moved = list(draw(st.permutations(pieces)))
    if len(moved) > 0 and draw(st.booleans()):
        moved.append(draw(st.sampled_from(moved)))
    if len(moved) > 0 and draw(st.booleans()):
        moved.pop(draw(st.integers(0, len(moved) - 1)))
    if draw(st.booleans()):  # a piece of its own, e.g. a value the text doesn't have
        moved.insert(draw(st.integers(0, len(moved))), draw(_PIECES))
    return "".join(pieces), "".join(moved) + " b"


@given(_translated())
@example(("{}{}", "{} b"))  # loses a value
@example(("{}", "{}{} b"))  # one value more: `IndexError`
@example(("{count}", "{count:{width}} b"))  # a value in a format: `KeyError`
@example(("{name}", "{name.real} b"))  # the same value: no mismatch
@example(("{0}", "{0}{} b"))  # by position and by number: `str.format` refuses it
def test_a_translation_is_accepted_when_it_formats_the_text_s_values(
    translated: tuple[str, str],
) -> None:
    text, translation = translated
    used = _used(text)
    if used is None:
        return  # not a text the app formats: nothing a translation must keep
    report = check_catalog(Path("fr.json"), {text}, {text: translation})
    # as `str.format` finds it: it formats, and the same values
    assert (report.mismatched == []) == (_used(translation) == used)


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


def test_a_table_s_refusals_are_text_to_translate() -> None:
    texts = find_texts([Path(pipecatalogue.__file__)])

    assert set(pipecatalogue.Pipes.refusals.values()) <= texts


@define_view
class _UntranslatedMainView(TranslatedMainView):
    translations_dir = None


def test_an_app_without_catalogs_can_t_be_checked_or_has_none_to_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="sets no translations_dir"):
        check_main_view(_UntranslatedMainView)
    # a directory without a catalog yet, named to the command as module:Class
    monkeypatch.setattr(
        sys.modules[__name__], "_EmptyMainView", _checked_main_view(tmp_path), raising=False
    )

    assert main([f"{__name__}:_EmptyMainView"]) == 0
    assert f"no catalog in {tmp_path}" in capsys.readouterr().out


def test_the_command_refuses_a_module_it_can_t_import(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["examples.no_such_example:MainView"])

    assert "No module named 'examples.no_such_example'" in capsys.readouterr().err
