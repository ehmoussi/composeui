"""The code examples and the navigation of the documentation follow the code of ComposeUI."""

from __future__ import annotations

import ast
import builtins
import importlib
import re
import runpy
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
#: the pages that an app developer copies code from
PAGES = [
    ROOT / "README.md",
    *sorted(DOCS.glob("*.md")),
    *sorted((DOCS / "user-guide").glob("*.md")),
    DOCS / "_site" / "skills" / "composeui" / "SKILL.md",
]
#: a fenced Python block, also one indented in a list item
FENCE = re.compile(
    r"^(?P<indent> *)```python\n(?P<code>.*?)^(?P=indent)```$", re.MULTILINE | re.DOTALL
)


def _examples() -> Iterator[tuple[str, str]]:
    """Give each Python block of the pages, with its page and its line as an id."""
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        for match in FENCE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            yield f"{page.relative_to(ROOT).as_posix()}:{line}", textwrap.dedent(match["code"])


def _undefined_names(code: str) -> set[str]:
    """Give the names that the code reads but never binds, in any of its scopes."""
    bound = set(dir(builtins)) | {"__file__"}
    read: set[str] = set()
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Name):
            (read if isinstance(node.ctx, ast.Load) else bound).add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.alias):
            bound.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return read - bound


EXAMPLES = [pytest.param(code, id=example_id) for example_id, code in _examples()]
# a fragment reads names that the page defines elsewhere, or that stand for the app's own
COMPLETE_EXAMPLES = [
    pytest.param(code, id=example_id)
    for example_id, code in _examples()
    if not _undefined_names(code)
]


@pytest.mark.parametrize("code", EXAMPLES)
def test_each_name_that_an_example_imports_from_composeui_exists(code: str) -> None:
    missing = [
        f"{node.module}.{alias.name}"
        for node in ast.walk(ast.parse(code))
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("composeui")
        for alias in node.names
        if not hasattr(importlib.import_module(node.module or ""), alias.name)
    ]
    assert not missing


@pytest.mark.parametrize("code", COMPLETE_EXAMPLES)
def test_each_complete_example_runs(
    code: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    tests = [
        node
        for node in ast.parse(code).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    if tests:
        # an example of a test runs as pytest runs it, with its fixtures
        example = tmp_path / "test_example.py"
        example.write_text(code, encoding="utf-8")
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(example)]
        subprocess.run(command, check=True)  # noqa: S603
    else:
        # not as `__main__`: an app's `run` would start its backend
        example = tmp_path / "example.py"
        example.write_text(code, encoding="utf-8")
        runpy.run_path(str(example), run_name="doc_example")


def _anchor(heading: str) -> str:
    """Give the anchor of a heading, as MyST and GitHub make it."""
    return re.sub(r"[^\w\- ]", "", heading.replace("`", "").lower()).replace(" ", "-")


def test_the_user_guide_lists_the_sections_of_its_pages() -> None:
    listed = set(
        re.findall(
            r"\]\(user-guide/([\w-]+\.md)#([\w-]+)\)",
            (DOCS / "user-guide.md").read_text(encoding="utf-8"),
        )
    )
    sections = {
        (page.name, _anchor(heading))
        for page in (DOCS / "user-guide").glob("*.md")
        for heading in re.findall(r"^#{2,3} (.+)$", page.read_text(encoding="utf-8"), re.MULTILINE)
    }
    assert listed == sections


def test_each_relative_link_of_the_readme_is_a_file() -> None:
    # Sphinx checks the links of `docs/`, but the README is read on GitHub and PyPI only
    links = re.findall(r"\]\(([^)#\s]+)", (ROOT / "README.md").read_text(encoding="utf-8"))
    missing = [link for link in links if "://" not in link and not (ROOT / link).exists()]
    assert not missing
