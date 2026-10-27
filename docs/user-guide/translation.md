# Translating the app

Write the app's text in one language in the code, and translate it from JSON catalogs. Each
language has one `<language>.json` file, which maps each text to its translation:

```json
{"Radius": "Rayon", "Main Pipe": "Conduite principale"}
```

Declare the text that a view shows with `T`, where the class of the view declares it. Or
set the text through the `tr` of a view once the view is built. Point the main view at the
directory of the catalogs:

```python
from pathlib import Path

from composeui.core.view import GroupFormView, MainView, T, child, define_view


@define_view
class PipeDimensionView(GroupFormView):
    radius: DimensionInputView = child(  # a LabelRowFloatInputView
        DimensionInputView, label=T("Radius")
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.title = self.tr("Main Pipe")


@define_view
class PipeMainView(MainView):
    app_title = T("Pipe Form")
    translations_dir = Path(__file__).parent / "locales"
```

`tr` returns the translation as a `str` that remembers the text as written. `T` is the
same, but the text is translated once a view keeps it and the main view sets a language.

`main_view.set_language("fr")`, or `--language fr` on the command line, changes the
language. Every view field that keeps such text is then translated again: a label or a
title, a status or validator message, the headers and rows of a table, the labels of a
choice (the keys of `values`). Because the views are reactive, every backend shows the new
text at once. On the web, each session has its own language, and the `<html lang>` of the
page follows it.

Until the language changes, `language` is the app's `source_language` (`"en"`, unless a
main view says otherwise). A regional language (`fr-CA`) falls back on the catalog of its
base language (`fr.json`). Text that no catalog translates shows as written.

- **Formatted text follows too.** `self.tr("Picked {color}").format(color=self.tr("Red"))`
  is formatted again in the new language, and its translated arguments are translated too.
- **Text set without `tr` stays as it is,** and so does text made from a translation
  (`self.tr("Name") + ":"`, an f-string). For text that a view builds from other text,
  override `retranslate`. It runs once when the view is built, then on each change of
  language, once the text is translated.
- **A choice keeps its value.** The value stays selected when its labels change. A study
  saves it by a key that no language changes: the name of an enum member, a string value
  itself, else its position.
- **The titles follow too.** The `title` of the main view, from the `app_title` of its
  class, follows the language when it is declared with `T`. It is the title of the window
  on Qt, of the app in Textual, and the header and `<title>` of the page on the web. The
  `page_title` of a page follows the language too.
- **ComposeUI translates its own text** (the File menu, the OK and Cancel of a dialog) from
  its own catalogs. The app's catalog wins over them.
- **A `LanguageMenu` field of the main view lets the user switch:**
  `language_menu: LanguageMenu = Factory(LanguageMenu)`. It offers `source_language` and a
  language per catalog in `translations_dir`, each named in itself ("Français"). It keeps
  the language shown checked, and it is not study data. A language that it can't name shows
  its code. Name it in a subclass: `names = {**LanguageMenu.names, "eo": "Esperanto"}`.

[`src/examples/pipeform.py`](../../src/examples/pipeform.py) is translated into French. Start
it with `uv run python -m examples.pipeform --backend qt --language fr`, or switch from its
Language menu.

## Checking the catalogs

Check the app's catalogs against its code, for example in CI:

```bash
uv run python -m composeui.core.translationcheck examples.pipeform:PipeMainView
```

The check fails:

- on text that a catalog misses, because the text would show as written;
- on a translation whose `{placeholders}` differ from those of the text, because formatting
  it would fail.

It also lists the entries that no code uses any more.

The text that it checks is the literals passed to `tr` or `T` in the source of the views,
plus the text that the views translate as they are built. The second part finds the text
that `tr` gets from a variable, for example the values of an enum.

To start or complete a catalog, `--write fr` first adds the text that `fr.json` misses to the
catalog, translated as `""` for a translator to fill. It creates the file if needed:

```bash
uv run python -m composeui.core.translationcheck examples.pipeform:PipeMainView --write fr
```

- The existing entries are kept.
- A translation left empty counts as missing, and the text shows as written.
- `--write` doesn't add text that the catalog of ComposeUI translates in that language (the
  File menu, OK, and so on).
- A new regional catalog (`fr-CA`) starts from the catalog of its base language.
