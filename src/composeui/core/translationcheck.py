"""Check an app's catalogs against the text its code translates.

Run it on the app's main view. It fails on text a catalog misses or on a translation whose
``{placeholders}`` differ from the text's, and lists the entries no code uses::

    python -m composeui.core.translationcheck examples.pipeform:PipeMainView

With ``--write fr``, it first adds the text ``fr.json`` misses to it, translated as "" for a
translator to fill. Until then, the text shows as written. With ``--strict``, it also fails
on the entries no code uses.

The text is found two ways: the string literals passed to ``tr`` or ``T`` (or set in a
``SqliteTable``'s ``refusals``) in the source of every view of the main view and in the
app's modules that they import, and the text the views translate as they show it, which
finds text ``tr`` gets from a variable, e.g. an enum's. The app's modules are those of the
main view's package, and those outside a package beside the main view's module.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import inspect
import json
import re
import string
import sys
from importlib.machinery import PathFinder
from pathlib import Path
from typing import TYPE_CHECKING

import attrs
from typing_extensions import override

from composeui.core._views.base import _retranslate
from composeui.core.translation import CATALOGS_DIR, load_catalog

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

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

    @property
    def is_complete(self) -> bool:
        """Tell whether the catalog is ok and has no unused entries either."""
        return self.is_ok and not self.unused

    @override
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
    """Get the source files of `main_view`'s view classes, their base classes, and imports.

    The imports are the app's modules that these files import, directly or not: text declared
    with ``T`` in a module without a view, such as an error's message, is the app's too.
    """
    is_app_module = _app_modules(type(main_view).__module__)
    names = {cls.__module__ for view in _views(main_view) for cls in type(view).__mro__}
    to_read = list(names)
    paths: set[Path] = set()
    while to_read:
        name = to_read.pop()
        file = _module_file(name)
        if file is None:
            continue
        paths.add(file)
        if is_app_module(name):
            imported = {
                prefix
                for imported in _imported_names(file, name)
                for prefix in _prefixes(imported)
                if is_app_module(prefix)
            }
            to_read.extend(imported - names)
            names |= imported
    return paths


def _app_modules(home: str) -> Callable[[str], bool]:
    """Get what tells whether a module is of the app whose main view is in the module `home`.

    The modules of its package, and the modules outside a package beside `home`, as an app
    made of ``app.py`` and ``dialogs.py`` has. The name alone can't tell these from the
    installed ones: ``dialogs`` and ``numpy`` are both outside a package.
    """
    package = home.partition(".")[0]
    file = _module_file(home)
    folder = None if file is None else file.parent

    def is_app_module(name: str) -> bool:
        if name.partition(".")[0] == package:
            return True
        file = _module_file(name)
        return file is not None and file.parent == folder

    return is_app_module


def _module_file(name: str) -> Path | None:
    """Get the source file of the module `name`, or `None` if `name` isn't a module.

    A module not imported yet, such as one the app imports only in a function, is looked for
    in its package's folders: `importlib.util.find_spec` would import its package, which runs
    it, and a module imported late can need what the check lacks, such as a backend.
    """
    file = None
    folders: Sequence[str] | None = sys.path  # where the package so far looks for its modules
    for prefix in _prefixes(name):
        module = sys.modules.get(prefix)
        if module is not None:
            file, folders = getattr(module, "__file__", None), getattr(module, "__path__", None)
        else:
            spec = None if folders is None else PathFinder.find_spec(prefix, folders)
            if spec is None:  # a name of a module, such as a class
                return None
            file, folders = spec.origin, spec.submodule_search_locations
    return Path(file) if file is not None and file.endswith(".py") else None


def _imported_names(file: Path, name: str) -> Iterator[str]:
    """Yield what the module `name`, in `file`, imports: modules, or names from modules."""
    package = name if file.name == "__init__.py" else name.rpartition(".")[0]
    for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"), filename=str(file))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
            yield module
            yield from (f"{module}.{alias.name}" for alias in node.names if alias.name != "*")


def _prefixes(name: str) -> Iterator[str]:
    """Yield `name` and the packages it is in, which importing it imports too."""
    parts = name.split(".")
    for end in range(1, len(parts) + 1):
        yield ".".join(parts[:end])


def placeholders(text: str) -> set[str] | None:
    """Get the values `text` formats, or `None` if it isn't a valid format.

    A value by its name, or its position: ``{}`` numbered as `str.format` numbers it, so
    ``"{}{}"`` formats ``{"0", "1"}``, as ``"{0}{1}"`` does. ``{name.real}`` formats
    `name`, and so does a field in another's format, such as ``{count:{width}}``'s.
    """
    names: set[str] = set()
    automatic = 0  # the `{}` fields so far
    manual = False

    def add(text: str) -> None:
        nonlocal automatic, manual
        for _, field, spec, _ in string.Formatter().parse(text):
            if field is None:
                continue
            name = re.split(r"[.\[]", field, maxsplit=1)[0]
            if name == "":
                name, automatic = str(automatic), automatic + 1
            elif name.isdigit():
                manual = True
            names.add(name)
            add(spec or "")

    try:
        add(text)
    except ValueError:
        return None
    # both, `str.format` refuses: "cannot switch from automatic field numbering to manual"
    return None if automatic > 0 and manual else names


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
    """Print a report for each catalog of a main view; 1 if one isn't ok (complete), else 0."""
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
    parser.add_argument("--strict", action="store_true", help="also fail on unused entries")
    args = parser.parse_args(argv)
    for language in args.write:
        path, added = write_catalog(args.main_view, language)
        print(f"{path}: {len(added)} entries added to translate")  # noqa: T201
    reports = check_main_view(args.main_view)
    for report in reports:
        print(report)  # noqa: T201
    if not reports:
        print(f"no catalog in {args.main_view.translations_dir}")  # noqa: T201
    if args.strict:
        return 0 if all(report.is_complete for report in reports) else 1
    return 0 if all(report.is_ok for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
