"""The code examples and the navigation of the documentation follow the code of ComposeUI."""

from __future__ import annotations

import ast
import builtins
import importlib
import importlib.util
import re
import runpy
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from packaging.version import Version

import composeui
from composeui.core import view
from composeui.core.registry import RendererType

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
#: where the README links to the site and to the other files of the repository
SITE_URL = "https://ehmoussi.github.io/composeui/"
REPOSITORY_URL = "https://github.com/ehmoussi/composeui/blob/main/"
GUIDES = {"user-guide": "Pages of this guide", "technical-guide": "Contents"}
#: the pages with Python examples
PAGES = [
    ROOT / "README.md",
    *sorted(DOCS.glob("*.md")),
    *(page for guide in GUIDES for page in sorted((DOCS / guide).glob("*.md"))),
    DOCS / "_site" / "skills" / "composeui" / "SKILL.md",
]
#: the skill that users install for their agents
SKILL = DOCS / "_site" / "skills" / "composeui" / "SKILL.md"
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


#: the example apps too: users copy from them as from the guides
IMPORTING_EXAMPLES = [
    *EXAMPLES,
    *(
        pytest.param(path.read_text(encoding="utf-8"), id=path.relative_to(ROOT).as_posix())
        for path in sorted((ROOT / "src" / "examples").glob("*.py"))
    ),
]


def _is_public(module_name: str, name: str) -> bool:
    """Tell whether a module gives `name` to apps: in its `__all__`, if it has one."""
    module = pytest.importorskip(module_name)  # a backend's, without its extra
    public = getattr(module, "__all__", None)
    return hasattr(module, name) if public is None else name in public


@pytest.mark.parametrize("code", IMPORTING_EXAMPLES)
def test_each_name_that_an_example_imports_from_composeui_is_public(code: str) -> None:
    hidden = [
        f"{node.module}.{alias.name}"
        for node in ast.walk(ast.parse(code))
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("composeui")
        for alias in node.names
        if not _is_public(node.module or "", alias.name)
    ]
    assert not hidden


@pytest.mark.parametrize("code", COMPLETE_EXAMPLES)
def test_each_complete_example_runs(
    code: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # what the example imports apart from ComposeUI: an extra's, such as Matplotlib
    for node in ast.parse(code).body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            pytest.importorskip(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                pytest.importorskip(alias.name)
    monkeypatch.chdir(tmp_path)
    # an example runs outside an app, whatever app a test built before it in this process
    monkeypatch.setattr("composeui.core.application._Running.backend", None)
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
        if importlib.util.find_spec("PySide6") is None:
            command += ["-p", "no:pytest-qt"]  # which refuses to start without Qt
        subprocess.run(command, check=True)  # noqa: S603 (a command the code builds, no user input)
    else:
        # not as `__main__`: an app's `run` would start its backend
        example = tmp_path / "example.py"
        example.write_text(code, encoding="utf-8")
        runpy.run_path(str(example), run_name="doc_example")


def _anchor(heading: str) -> str:
    """Give the anchor of a heading, as MyST and GitHub make it."""
    return re.sub(r"[^\w\- ]", "", heading.replace("`", "").lower()).replace(" ", "-")


def test_the_user_guide_names_each_public_view() -> None:
    guide = "".join(page.read_text(encoding="utf-8") for page in (DOCS / "user-guide").glob("*.md"))
    views = [
        name
        for name in view.__all__
        if isinstance(getattr(view, name), type)
        and issubclass(getattr(view, name), view.View)
        and getattr(view, name)._renderer_key is not None  # noqa: SLF001 (what the catalog reads)
    ]

    assert len(views) > 0
    assert [name for name in views if re.search(rf"\b{name}\b", guide) is None] == []


@pytest.mark.parametrize(("guide", "heading"), GUIDES.items())
def test_each_guide_lists_its_pages_and_sections(guide: str, heading: str) -> None:
    index = (DOCS / f"{guide}.md").read_text(encoding="utf-8")
    contents = index.partition(f"\n## {heading}\n")[2].split("\n## ", 1)[0]
    listed = set(re.findall(rf"\]\({re.escape(guide)}/([\w-]+\.md)(?:#([\w-]+))?\)", contents))
    pages = list((DOCS / guide).glob("*.md"))
    sections = {
        (page.name, _anchor(section))
        for page in pages
        for section in re.findall(r"^#{2,3} (.+)$", page.read_text(encoding="utf-8"), re.MULTILINE)
    }
    assert listed == sections | {(page.name, "") for page in pages}


def test_each_link_of_the_readme_to_the_project_has_a_target() -> None:
    # Sphinx checks the links of `docs/`, but not the README's. PyPI shows the README too, where
    # a relative link is broken: a page of `docs/` is linked on the site, another file on GitHub.
    links = re.findall(r"\]\(([^)\s]+)\)", (ROOT / "README.md").read_text(encoding="utf-8"))
    assert [link for link in links if "://" not in link] == []
    missing = []
    for link in links:
        url, _, anchor = link.partition("#")
        if url.startswith(SITE_URL):
            target = DOCS / re.sub(r"\.html$", ".md", url[len(SITE_URL) :])
        elif url.startswith(REPOSITORY_URL):
            target = ROOT / url[len(REPOSITORY_URL) :]
        else:
            continue
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        anchors = {_anchor(heading) for heading in re.findall(r"^#{1,3} (.+)$", text, re.MULTILINE)}
        if not target.is_file() or (anchor and anchor not in anchors):
            missing.append(link)
    assert missing == []


def _described_versions(version: str) -> set[str]:
    """Give the minor versions that the skill may describe, for the package's `version`."""
    package = Version(version)
    major, minor = package.release[:2]
    if not package.is_devrelease:
        return {f"{major}.{minor}"}
    # between two releases, the skill may describe the next one already
    return {f"{major}.{minor}", f"{major}.{minor + 1}", f"{major + 1}.0"}


def test_the_skill_names_the_version_of_composeui_it_describes() -> None:
    # an agent compares it with the installed version, to tell that its copy is old
    text = SKILL.read_text(encoding="utf-8")
    (described,) = re.findall(r'^  composeui-version: "(.+)"$', text, re.MULTILINE)
    assert described in _described_versions(composeui.__version__)
    assert f"for ComposeUI {described}." in text
    assert f"newer than {described} " in text


def test_each_public_module_has_its_page_in_the_api_reference() -> None:
    documented = {
        module
        for page in (DOCS / "api").glob("*.md")
        for module in re.findall(
            r"^\.\. automodule:: ([\w.]+)$", page.read_text(encoding="utf-8"), re.MULTILINE
        )
    }
    core = Path(composeui.__file__).parent / "core"
    public = {
        f"composeui.core.{path.stem}"
        for path in core.glob("*.py")
        if not path.stem.startswith("_")
        and getattr(importlib.import_module(f"composeui.core.{path.stem}"), "__all__", None) != []
    }
    applications = {backend.value.applications for backend in RendererType}
    assert public | applications <= documented


def _sections(text: str) -> dict[str, str]:
    """Give the text of each `##` section of a page, by heading."""
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2]))


EXAMPLES_GUIDE = DOCS / "examples-guide.md"
EXAMPLE_APPS = sorted(
    path.stem for path in (ROOT / "src" / "examples").glob("*.py") if path.stem != "__init__"
)


@pytest.mark.parametrize("example", EXAMPLE_APPS)
def test_each_example_has_its_row_section_and_screenshots_in_the_examples_guide(
    example: str,
) -> None:
    text = EXAMPLES_GUIDE.read_text(encoding="utf-8")
    link = f"[`{example}.py`](../src/examples/{example}.py)"
    code = (ROOT / "src" / "examples" / f"{example}.py").read_text(encoding="utf-8")
    default = re.search(r"default_backend=RendererType\.(\w+)", code)
    row = re.search(rf"^\| {re.escape(link)} \| ([\w ]+) \|", text, re.MULTILINE)
    backend = "web" if default is None else default[1].lower()
    assert row is not None, "its row in the overview"
    assert row[1].split()[0] == backend

    (section,) = [
        section for section in _sections(text).values() if section.lstrip().startswith(link)
    ]
    # the command that runs it names the backend it starts, before the others it can take
    commands = re.findall(rf"^uv run python -m examples\.{example}\b.*$", section, re.MULTILINE)
    assert commands != []
    named = [command.partition("#")[2].strip() for command in commands if "--backend" in command]
    assert [comment for comment in named if not comment.startswith(f"{backend};")] == []
    screenshots = re.findall(rf"\]\((images/{example}-\w+\.png)\)", section)
    assert screenshots != []
    assert [image for image in screenshots if not (DOCS / image).is_file()] == []


def test_the_examples_guide_lists_its_sections() -> None:
    text = EXAMPLES_GUIDE.read_text(encoding="utf-8")
    sections = _sections(text)
    listed = re.findall(r"^- \[(.+)\]\(#([\w-]+)\)$", sections["Contents"], re.MULTILINE)
    headings = [heading for heading in sections if heading != "Contents"]
    assert listed == [(heading, _anchor(heading)) for heading in headings]


#: the Markdown files of the repository: the documentation, and the skills of its agents
MARKDOWN = sorted(
    {
        *ROOT.glob("*.md"),
        *(path for path in DOCS.rglob("*.md") if "_build" not in path.parts),
        *(ROOT / ".agents" / "skills").glob("*/SKILL.md"),
        *(ROOT / "benchmarks").glob("*.md"),
    }
)
#: what a line never breaks inside: inline code, a link, an HTML tag, an address
UNBROKEN = re.compile(r"`[^`]*`|!?\[[^\]]*\]\([^)]*\)|<[^>]+>|https?://\S+")
#: the start of a line that a wrap keeps: its indentation and its list marker
LINE_START = re.compile(r"^\s*(?:(?:[-*+]|\d+\.)\s+)?")


def _wrappable_lines(path: Path) -> Iterator[str]:
    """Give the lines of prose longer than 100 characters that a wrap would shorten."""
    lines = path.read_text(encoding="utf-8").splitlines()
    in_front_matter = lines[:1] == ["---"]
    in_code = False
    for number, line in enumerate(lines, 1):
        if in_front_matter:
            in_front_matter = number == 1 or line != "---"
            continue
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if in_code or len(line) <= 100 or line.lstrip().startswith("|"):
            continue
        kept = [False] * len(line)
        for match in UNBROKEN.finditer(line):
            kept[match.start() : match.end()] = [True] * (match.end() - match.start())
        start = LINE_START.match(line)
        assert start is not None  # it matches any line, even with nothing
        breaks = [
            index for index in range(start.end(), 101) if line[index] == " " and not kept[index]
        ]
        # a long address alone on a line is as long as it was: the line can stay
        rest = line[breaks[-1] + 1 :] if breaks else ""
        if breaks and (len(rest) <= 100 or UNBROKEN.fullmatch(rest) is None):
            yield f"{path.relative_to(ROOT).as_posix()}:{number}"


def test_markdown_prose_wraps_at_100_characters() -> None:
    assert [line for path in MARKDOWN for line in _wrappable_lines(path)] == []


@pytest.mark.parametrize(
    "page",
    # the changelog repeats its headings in each release
    [page for page in MARKDOWN if page.name != "CHANGELOG.md"],
    ids=lambda page: page.relative_to(ROOT).as_posix(),
)
def test_each_heading_is_unique_in_its_page(page: Path) -> None:
    # a link to a heading has one target only while no other heading of the page has its anchor
    text = re.sub(
        r"^```.*?^```", "", page.read_text(encoding="utf-8"), flags=re.MULTILINE | re.DOTALL
    )
    anchors = [_anchor(heading) for heading in re.findall(r"^#{1,3} (.+)$", text, re.MULTILINE)]
    assert sorted({anchor for anchor in anchors if anchors.count(anchor) > 1}) == []


def test_the_docs_link_to_the_repository_s_files_by_relative_path() -> None:
    # Sphinx turns a relative link to a file outside `docs/` into a link to it on GitHub, at
    # the version built (`docs/conf.py`); a URL written by hand stays on `main`
    # `docs/_site/` is copied as it is, for readers off the site
    pages = [
        path for path in MARKDOWN if DOCS in path.parents and DOCS / "_site" not in path.parents
    ]
    assert [
        page.relative_to(ROOT).as_posix()
        for page in pages
        if re.search(
            r"github\.com/ehmoussi/composeui/(?:blob|tree)/", page.read_text(encoding="utf-8")
        )
    ] == []


#: the Makefile's targets that the lists of commands leave out: parts of `lint` and `all`
UNLISTED_TARGETS = {"format", "check_fix", "clean"}


@pytest.mark.parametrize("page", ["AGENTS.md", "docs/technical-guide/development.md"])
def test_each_list_of_commands_names_each_target_of_the_makefile(page: str) -> None:
    # AGENTS.md and the technical guide keep a copy each: both follow the Makefile
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    targets = {
        target
        for line in re.findall(r"^\.PHONY: (.+)$", makefile, re.MULTILINE)
        for target in line.split()
    }
    commands = re.search(
        r"^## Commands\n\n```bash\n(.*?)^```",
        (ROOT / page).read_text(encoding="utf-8"),
        re.MULTILINE | re.DOTALL,
    )
    assert commands is not None
    listed = {
        target
        for names in re.findall(r"^make ([\w -]+?)\s+#", commands[1], re.MULTILINE)
        for target in names.split()
    }
    assert listed == targets - UNLISTED_TARGETS


#: Markdown in a docstring, which Sphinx reads as reStructuredText: a fence, a link, bold text
#: or a heading
DOCSTRING_MARKDOWN = re.compile(
    r"```|(?<!`)\[[^\]]+\]\([^)]+\)|\*\*[A-Za-z][^*]*\*\*|^#{1,6} ", re.MULTILINE
)


def test_the_docstrings_are_restructured_text() -> None:
    found = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                docstring = ast.get_docstring(node) or ""
                if DOCSTRING_MARKDOWN.search(docstring):
                    found.append(
                        f"{path.relative_to(ROOT).as_posix()}:{getattr(node, 'lineno', 1)}"
                    )
    assert found == []
