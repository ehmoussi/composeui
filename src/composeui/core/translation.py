"""Translate the text views show, from JSON catalogs.

A catalog is a `<language>.json` file mapping the text as written in the code to its
translation: ``{"Radius": "Rayon"}``. Text missing from every catalog is shown as written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from collections.abc import Sequence

#: translates a text as written in the code into a language
Translate = Callable[[str], str]

#: ComposeUI's own catalogs, for the text of the views it defines (menus, dialogs...)
CATALOGS_DIR = Path(__file__).parent.parent / "locales"


def no_translation(text: str) -> str:
    """Show `text` as written in the code."""
    return text


def _language_names(language: str) -> list[str]:
    """Get the catalog names to look for, most specific first: "fr-CA" then "fr"."""
    names = [language, language.replace("_", "-")]
    names.append(names[-1].split("-")[0])
    return list(dict.fromkeys(names))


def load_catalog(directory: Path, language: str) -> dict[str, str]:
    """Load `language`'s catalog in `directory`, or an empty one if it has none.

    A regional language ("fr-CA", "fr_CA") falls back on its base language's ("fr").
    """
    for name in _language_names(language):
        path = directory / f"{name}.json"
        if path.is_file():
            with path.open(encoding="utf-8") as f:
                catalog = json.load(f)
            if not isinstance(catalog, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in catalog.items()
            ):
                msg = f"{path} must map each text to its translation, both strings"
                raise ValueError(msg)
            return catalog
    return {}


def translator(language: str, directories: Sequence[Path]) -> Translate:
    """Get the translation into `language` from the catalogs in `directories`.

    The first directory with a translation of a text wins: an app's catalogs, listed
    before ComposeUI's, can change the text of ComposeUI's views.
    """
    catalog: dict[str, str] = {}
    for directory in reversed(directories):
        catalog.update(load_catalog(directory, language))

    def translate(text: str) -> str:
        return catalog.get(text, text)

    return translate
