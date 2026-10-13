"""Translate the text views show, from JSON catalogs.

A catalog is a `<language>.json` file mapping the text as written in the code to its
translation: ``{"Radius": "Rayon"}``. Text missing from every catalog is shown as written,
like text translated as "": a translation still to fill.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable

from typing_extensions import Self

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: translates a text as written in the code into a language
Translate = Callable[[str], str]

#: ComposeUI's own catalogs, for the text of the views it defines (menus, dialogs...)
CATALOGS_DIR = Path(__file__).parent.parent / "locales"


#: languages by code, each named in itself, as a menu offering them shows them
LANGUAGE_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "ar": "العربية",
        "bg": "Български",
        "ca": "Català",
        "cs": "Čeština",
        "da": "Dansk",
        "de": "Deutsch",
        "el": "Ελληνικά",
        "en": "English",
        "es": "Español",
        "et": "Eesti",
        "fa": "فارسی",
        "fi": "Suomi",
        "fr": "Français",
        "he": "עברית",
        "hi": "हिन्दी",
        "hr": "Hrvatski",
        "hu": "Magyar",
        "id": "Bahasa Indonesia",
        "it": "Italiano",
        "ja": "日本語",
        "ko": "한국어",
        "lt": "Lietuvių",
        "lv": "Latviešu",
        "nb": "Norsk bokmål",
        "nl": "Nederlands",
        "pl": "Polski",
        "pt": "Português",
        "ro": "Română",
        "ru": "Русский",
        "sk": "Slovenčina",
        "sl": "Slovenščina",
        "sr": "Српски",
        "sv": "Svenska",
        "th": "ไทย",
        "tr": "Türkçe",
        "uk": "Українська",
        "vi": "Tiếng Việt",
        "zh": "中文",
    }
)


def language_name(language: str, names: Mapping[str, str] = LANGUAGE_NAMES) -> str:
    """Name `language` in itself, from `names`: "fr-CA" is "Français (CA)".

    A language `names` doesn't know is named by its code.
    """
    if language in names:
        return names[language]
    base, _, region = language.replace("_", "-").partition("-")
    if base not in names:
        return language
    return f"{names[base]} ({region})" if region else names[base]


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
        # "" is still to fill: a catalog after it can translate the text
        catalog.update(
            (text, translation)
            for text, translation in load_catalog(directory, language).items()
            if translation != ""
        )

    def translate(text: str) -> str:
        return catalog.get(text, text)

    return translate


# a `__dict__` for what it remembers: a str subclass can't have non-empty `__slots__`
class TranslatedText(str):  # noqa: SLOT000
    """Text `View.tr` translated, remembering it as written to translate it again.

    `MainView.set_language` translates it again wherever a view keeps it: in a field, a
    list (a table's headers) or a dict's keys (a choice's labels). Formatting it keeps the
    arguments, to format the next translation with them; other str methods return a plain
    str, which stays in its language.

    Built from `text` alone (as `T`), it's the text as written, translated once a view
    keeps it and the main view sets a language: text declared where no view can `tr` it,
    e.g. a field's default or a class variable.
    """

    source: str
    #: the `format` arguments, or `None` if it isn't formatted
    arguments: tuple[tuple[Any, ...], dict[str, Any]] | None

    def __new__(
        cls,
        text: str,
        source: str | None = None,
        arguments: tuple[tuple[Any, ...], dict[str, Any]] | None = None,
    ) -> Self:
        self = super().__new__(cls, text)
        self.source = text if source is None else source
        self.arguments = arguments
        return self

    def __getnewargs__(self) -> tuple[str, str, tuple[tuple[Any, ...], dict[str, Any]] | None]:  # type: ignore[override]
        # copying it (`copy.deepcopy`) keeps what it remembers
        return (str(self), self.source, self.arguments)

    def format(self, *args: Any, **kwargs: Any) -> TranslatedText:
        """Format it, remembering the arguments: translated text among them follows too."""
        return TranslatedText(str.format(self, *args, **kwargs), self.source, (args, kwargs))

    def translated(self, translate: Translate) -> TranslatedText:
        """Translate it again, with `translate`."""
        text = translate(self.source)
        if self.arguments is None:
            return TranslatedText(text, self.source)
        args, kwargs = self.arguments
        args = tuple(translate_again(arg, translate) for arg in args)
        kwargs = {key: translate_again(value, translate) for key, value in kwargs.items()}
        return TranslatedText(text.format(*args, **kwargs), self.source, (args, kwargs))


#: text to translate, as written in the code, wherever it's declared:
#: ``add: ButtonView = child(ButtonView, text=T("Add"))``
T = TranslatedText


def translate_again(value: Any, translate: Translate) -> Any:
    """Translate the `TranslatedText` in `value` again, itself or in a list, tuple or dict.

    Return `value` itself when it holds none, so a caller can tell nothing changed.
    """
    if isinstance(value, TranslatedText):
        return value.translated(translate)
    if isinstance(value, (list, tuple)):
        items = [translate_again(item, translate) for item in value]
        if all(new is old for new, old in zip(items, value)):
            return value
        return type(value)(items) if type(value) in (list, tuple) else value
    if isinstance(value, dict):
        entries = [
            (translate_again(key, translate), translate_again(item, translate))
            for key, item in value.items()
        ]
        if all(k is k0 and v is v0 for (k, v), (k0, v0) in zip(entries, value.items())):
            return value
        return dict(entries)
    return value
