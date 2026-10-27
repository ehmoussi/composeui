"""Check an app's catalogs against the text its code translates.

Run it on the app's main view; it fails on text a catalog misses or on a translation whose
``{placeholders}`` differ from the text's, and lists the entries no code uses::

    python -m composeui.core.translationcheck examples.pipeform:PipeMainView

With ``--write fr``, it first adds the text ``fr.json`` misses to it, translated as "" for a
translator to fill; until then, the text shows as written.

The text is found two ways: the string literals passed to ``tr`` or ``T`` (or set in a
``SqliteTable``'s ``refusals``) in the source of every view of the main view, and the text
the views translate as they show it, which finds text ``tr`` gets from a variable, e.g. an
enum's. A table's refusals are found only in a module of a view.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import string
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import attrs

from composeui.core.translation import CATALOGS_DIR, load_catalog
from composeui.core.view import _retranslate

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from composeui.core.view import MainView, View

__all__ = ["CatalogReport", "check_main_view", "main", "placeholders"]


@attrs.define
class CatalogReport:
    """What a catalog lacks, or has too much of, for the text of the code."""

    path: Path
    #: text no catalog translates, or as "": it shows as written in the code
    missing: list[str] = attrs.Factory(list)
    #: text and translation whose ``{placeholders}`` differ: formatting it fails or loses one
    mismatched: list[tuple[str, str]] = attrs.Factory(list)
    #: entries for text the code doesn't translate, or no longer
    unused: list[str] = attrs.Factory(list)

    @property
    def is_ok(self) -> bool:
        """Tell whether every text is translated with its placeholders."""
        return not self.missing and not self.mismatched

    def __str__(self) -> str:
        lines = [
            f"{self.path}: {len(self.missing)} missing, {len(self.mismatched)} with other "
            f"placeholders, {len(self.unused)} unused"
        ]
        lines.extend(f"  missing: {text!r}" for text in self.missing)
        lines.extend(
            f"  other placeholders: {text!r} -> {translation!r}"
            for text, translation in self.mismatched
        )
        lines.extend(f"  unused: {text!r}" for text in self.unused)
        return "\n".join(lines)


def find_texts(paths: Iterable[Path]) -> set[str]:
    """Find the text the code in `paths` translates: `_TEXT_CALLS` literals, `_TEXT_DICTS`."""
    texts: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            texts.update(_literal_texts(node))
    return texts


#: what translates the text it's called with: a view's `tr`, and `T` declaring it
_TEXT_CALLS = ("tr", "T")
#: class variables whose dict values are text to translate: a `SqliteTable`'s refusals
#: (`View.refusing` translates them)
_TEXT_DICTS = ("refusals",)


def _literal_texts(node: ast.AST) -> Iterator[str]:
    if isinstance(node, ast.Call) and node.args:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in _TEXT_CALLS:
            yield from _strings([node.args[0]])
    elif isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(getattr(target, "id", None) in _TEXT_DICTS for target in targets):
            yield from _strings(node.value.values)


def _strings(nodes: Iterable[ast.expr | None]) -> Iterator[str]:
    for node in nodes:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def shown_texts(main_view: MainView) -> set[str]:
    """Find the text `main_view`'s views translate to show it, retranslating them."""
    texts: set[str] = set()

    def record(text: str) -> str:
        texts.add(text)
        return text

    _retranslate(main_view, record)
    return texts


def _views(view: View) -> Iterator[View]:
    yield view
    for child in view.children_views:
        yield from _views(child)


def source_paths(main_view: MainView) -> set[Path]:
    """Get the source files of `main_view`'s view classes and their base classes."""
    paths: set[Path] = set()
    for view in _views(main_view):
        for cls in type(view).__mro__:
            module = sys.modules.get(cls.__module__)
            file = getattr(module, "__file__", None)
            if file is not None and file.endswith(".py"):
                paths.add(Path(file))
    return paths


def placeholders(text: str) -> set[str] | None:
    """Get the ``{fields}`` `text` formats, or `None` if it isn't a valid format."""
    try:
        return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}
    except ValueError:
        return None


def check_catalog(
    path: Path, texts: set[str], catalog: dict[str, str], others: Sequence[dict[str, str]] = ()
) -> CatalogReport:
    """Check the catalog at `path` (`catalog`) against `texts`.

    `others` are the catalogs it falls back on, e.g. ComposeUI's: their text isn't missing.
    """
    report = CatalogReport(path)
    report.missing = sorted(texts - _translated(catalog, *others))
    report.unused = sorted(set(catalog) - texts)
    report.mismatched = [
        (text, translation)
        for text, translation in catalog.items()
        if translation != "" and placeholders(text) != placeholders(translation)
    ]
    return report


def _translated(*catalogs: dict[str, str]) -> set[str]:
    return {text for catalog in catalogs for text, translation in catalog.items() if translation}


def _app_texts(main_view_class: type[MainView]) -> tuple[Path, set[str]]:
    """Get the directory of the app's catalogs and the text its code translates."""
    directory = main_view_class.translations_dir
    if directory is None:
        msg = f"{main_view_class.__name__} sets no translations_dir"
        raise ValueError(msg)
    main_view = main_view_class()
    return directory, find_texts(source_paths(main_view)) | shown_texts(main_view)


def write_catalog(main_view_class: type[MainView], language: str) -> tuple[Path, list[str]]:
    """Add the text `language`'s catalog misses to it, translated as "" for a translator.

    Its entries are kept, unused ones too. A regional language's new catalog ("fr-CA")
    starts from its base language's: it replaces it. Text ComposeUI's catalog translates
    isn't added: the app's catalog only has it to translate it otherwise.
    Return the catalog's path and the text added.
    """
    directory, texts = _app_texts(main_view_class)
    catalog = load_catalog(directory, language)
    added = sorted(texts - set(catalog) - _translated(load_catalog(CATALOGS_DIR, language)))
    catalog.update(dict.fromkeys(added, ""))
    path = directory / f"{language}.json"
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path, added


def check_main_view(main_view_class: type[MainView]) -> list[CatalogReport]:
    """Check each catalog in `main_view_class.translations_dir` against the app's text."""
    directory, texts = _app_texts(main_view_class)
    reports = []
    for path in sorted(directory.glob("*.json")):
        language = path.stem
        reports.append(
            check_catalog(
                path,
                texts,
                load_catalog(directory, language),
                [load_catalog(CATALOGS_DIR, language)],
            )
        )
    return reports


def _main_view_class(spec: str) -> type[MainView]:
    module_name, _, class_name = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    cls = getattr(module, class_name, None)
    if not inspect.isclass(cls):
        msg = f"{spec} isn't a class: expected module:MainViewClass"
        raise argparse.ArgumentTypeError(msg)
    return cls


def main(argv: Sequence[str] | None = None) -> int:
    """Print a report for each catalog of a main view; 1 if one isn't ok, else 0."""
    parser = argparse.ArgumentParser(
        prog="python -m composeui.core.translationcheck", description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "main_view", type=_main_view_class, help="the app's main view, as module:Class"
    )
    parser.add_argument(
        "--write",
        action="append",
        default=[],
        metavar="LANGUAGE",
        help='first add the text to translate to LANGUAGE\'s catalog, translated as ""',
    )
    args = parser.parse_args(argv)
    for language in args.write:
        path, added = write_catalog(args.main_view, language)
        print(f"{path}: {len(added)} entries added to translate")  # noqa: T201
    reports = check_main_view(args.main_view)
    for report in reports:
        print(report)  # noqa: T201
    if not reports:
        print(f"no catalog in {args.main_view.translations_dir}")  # noqa: T201
    return 0 if all(report.is_ok for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
