"""The rules of AGENTS.md about the code that a script can check, so that no review has to."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).parent.parent
SOURCE = ROOT / "src"
BACKENDS = ("qtcore", "textualcore", "webcore")
#: the base renderer of each backend, which names no renderer of a family at run time
BASE_RENDERERS = {
    "qtcore": "qtrenderer.py",
    "textualcore": "textualrenderer.py",
    "webcore": "webrenderer.py",
}
#: a lint exemption, and what follows it on its line
NOQA = re.compile(r"#\s*noqa\b(?::\s*[A-Z0-9, ]+)?(?P<rest>.*)$")


def _python_files(folder: Path) -> list[Path]:
    return sorted(path for path in folder.rglob("*.py") if "_build" not in path.parts)


def _module_name(path: Path) -> list[str]:
    parts = list(path.relative_to(SOURCE).with_suffix("").parts)
    return parts[:-1] if parts[-1] == "__init__" else parts


def _is_type_checking(node: ast.stmt) -> bool:
    return isinstance(node, ast.If) and ast.unparse(node.test) in {
        "TYPE_CHECKING",
        "typing.TYPE_CHECKING",
    }


def _imports(path: Path, *, at_run_time: bool = False) -> set[str]:
    """Give the modules that `path` imports, and each name taken from one as `module.name`."""
    package = _module_name(path)
    if path.name != "__init__.py":
        package = package[:-1]
    modules: set[str] = set()
    pending: list[ast.AST] = [ast.parse(path.read_text(encoding="utf-8"))]
    while pending:
        node = pending.pop()
        if at_run_time and isinstance(node, ast.stmt) and _is_type_checking(node):
            continue
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            modules.add(module)
            modules.update(f"{module}.{alias.name}" for alias in node.names)
        pending.extend(ast.iter_child_nodes(node))
    return modules


def _where(path: Path, node: ast.expr | ast.stmt) -> str:
    return f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"


def _unexplained_noqa(path: Path) -> Iterator[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines):
        match = NOQA.search(line)
        if match is None or match["rest"].lstrip().startswith("("):
            continue
        # or explained by the comment above it, or above the lines of exemptions it ends
        above = number - 1
        while (
            above >= 0 and NOQA.search(lines[above]) and not lines[above].lstrip().startswith("#")
        ):
            above -= 1
        if above < 0 or not lines[above].lstrip().startswith("#"):
            yield f"{path.relative_to(ROOT).as_posix()}:{number + 1}"


def test_each_lint_exemption_says_why() -> None:
    # a reason in parentheses after the codes, or a comment on the line above
    paths = [*_python_files(SOURCE), *_python_files(ROOT / "tests"), *_python_files(ROOT / "docs")]
    assert [where for path in paths for where in _unexplained_noqa(path)] == []


def test_the_views_import_the_modules_that_define_what_they_use() -> None:
    # `core/view.py` exports the views: importing it from a family makes a cycle
    views = _python_files(SOURCE / "composeui" / "core" / "_views")
    assert len(views) > 0
    assert [path.name for path in views if "composeui.core.view" in _imports(path)] == []


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_family_of_renderers_imports_another_directly_not_through_the_key_map(
    backend: str,
) -> None:
    key_map = f"composeui.{backend}.renderers"
    families = _python_files(SOURCE / "composeui" / backend / "_renderers")
    assert len(families) > 0
    assert [path.name for path in families if key_map in _imports(path)] == []


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_backend_s_base_renderer_imports_no_family_at_run_time(backend: str) -> None:
    # a hook with a default, not an `isinstance` check, treats a renderer apart
    path = SOURCE / "composeui" / backend / BASE_RENDERERS[backend]
    families = f"composeui.{backend}._renderers"
    imported = _imports(path, at_run_time=True)
    assert [module for module in imported if module.startswith(families)] == []


#: the Qt renderers of a widget that a page has few of, which may connect a lambda
FEW_PER_PAGE = {"QtSourceTableRenderer", "QtTreeRenderer"}


def test_a_qt_renderer_connects_a_lambda_only_to_a_widget_a_page_has_few_of() -> None:
    # PySide searches its whole table of such connections each time a sender is deleted:
    # `_connect` and `_relay` make a `QtSlot` instead
    wrong: list[str] = []
    for path in _python_files(SOURCE / "composeui" / "qtcore" / "_renderers"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for renderer in tree.body:
            if isinstance(renderer, ast.ClassDef) and renderer.name in FEW_PER_PAGE:
                continue
            wrong.extend(
                _where(path, call)
                for call in ast.walk(renderer)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "connect"
                and any(isinstance(argument, ast.Lambda) for argument in call.args)
            )
    assert wrong == []


#: the functions of the browser tests that may sleep: they wait for a server or a check,
#: with a deadline, where no event tells them
BROWSER_SLEEPS = {"_serve", "_eventually"}


def test_the_browser_tests_wait_on_events_and_find_elements_as_a_user_does() -> None:
    path = ROOT / "tests" / "test_browser.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wrong: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            name = ast.unparse(node.func)
            if node.func.attr == "wait_for_timeout" or (
                name == "time.sleep" and function.name not in BROWSER_SLEEPS
            ):
                wrong.append(f"{_where(path, node)} {name}")
    # an element's `cui-<id>` id comes from `id()`, which changes each run
    wrong.extend(
        f"{_where(path, node)} {node.value!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.search(r"#cui-|(?<![\w-])cui-\d", node.value)
    )
    assert wrong == []


def _makefile_targets() -> set[str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    return {
        target
        for line in re.findall(r"^\.PHONY: (.+)$", text, re.MULTILINE)
        for target in line.split()
    }


def test_make_ps1_has_the_makefile_s_targets_and_translated_apps() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    script = (ROOT / "make.ps1").read_text(encoding="utf-8")
    validate_set = re.search(r"\[ValidateSet\(([^)]*)\)\]", script)
    actions = re.search(r"^\$actions = @\{(.*?)^\}", script, re.MULTILINE | re.DOTALL)
    assert validate_set is not None
    assert actions is not None
    assert set(re.findall(r"'([\w-]+)'", validate_set[1])) == _makefile_targets()
    assert set(re.findall(r"^\s*'([\w-]+)'\s*=", actions[1], re.MULTILINE)) == _makefile_targets()

    translated = re.search(
        r"^TRANSLATED_MAIN_VIEWS := (.*?)\n\n", makefile, re.MULTILINE | re.DOTALL
    )
    script_translated = re.search(
        r"^\$TranslatedMainViews = @\((.*?)\)", script, re.MULTILINE | re.DOTALL
    )
    assert translated is not None
    assert script_translated is not None
    assert translated[1].replace("\\", " ").split() == re.findall(
        r"'([^']+)'", script_translated[1]
    )


def _top_level(path: Path) -> list[str]:
    """Give what the module defines or runs at its top, apart from its docstring and imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    kept: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or _is_type_checking(node):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # the docstring
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            kept.append(ast.unparse(target))
        else:
            kept.append(ast.unparse(node).split("\n")[0])
    return kept


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_backend_s_renderers_module_only_maps_the_keys(backend: str) -> None:
    # its renderers live in `_renderers/`, a module per family
    assert _top_level(SOURCE / "composeui" / backend / "renderers.py") == ["RENDERERS"]


def test_the_view_module_only_exports_the_views_and_sets_up_the_shapes_last() -> None:
    # the views live in `_views/`, a module per family
    assert _top_level(SOURCE / "composeui" / "core" / "view.py") == [
        "__all__",
        "configure_tagged_union(Shape, CONVERTER)",
    ]


#: the test modules of a backend named after no module of it, with what they cover
OTHER_TEST_MODULES = {
    "webcore": {
        "reload": "the web side of `core/reload.py`",
        "security": "the defenses of `headers.py`, `origin.py` and `limits.py`",
    },
}
#: the families of renderers tested elsewhere, with where
FAMILIES_TESTED_ELSEWHERE = {
    "textualcore": {"graphics": "its drawing in tests/test_drawing.py, with the other backends'"},
}


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_backend_s_tests_have_a_module_per_family_of_renderers(backend: str) -> None:
    # a test module per family of `_renderers/`, or named after another module of the backend,
    # its prefix (`qt`, `textual`, `web`) left out: `test_renderer.py` for `webrenderer.py`
    package = SOURCE / "composeui" / backend
    prefix = backend.removesuffix("core")
    families = {path.stem for path in (package / "_renderers").glob("*.py")} - {"__init__"}
    modules = {path.stem.removeprefix(prefix) for path in package.glob("*.py")}
    tests = {
        path.stem.removeprefix("test_") for path in (ROOT / "tests" / backend).glob("test_*.py")
    }
    assert tests - families - modules == set(OTHER_TEST_MODULES.get(backend, {}))
    assert families - tests == set(FAMILIES_TESTED_ELSEWHERE.get(backend, {}))


#: the page's own scripts: those that `make js-check` checks, unlike the libraries beside them
PAGE_SCRIPTS = sorted(
    (ROOT / "js" / path).resolve()
    for path in re.findall(
        r'"(\.\./src/[^"]+\.js)"', (ROOT / "js" / "tsconfig.json").read_text(encoding="utf-8")
    )
)


@pytest.mark.parametrize("script", PAGE_SCRIPTS, ids=lambda script: script.name)
def test_a_page_script_keeps_its_names_in_a_closure_and_shares_only_compose_ui(
    script: Path,
) -> None:
    # classic scripts share the page's global names: one closure each, `window.ComposeUI` for
    # what another script calls
    code = re.sub(r"/\*.*?\*/", "", script.read_text(encoding="utf-8"), flags=re.DOTALL).strip()
    # the lines at the left edge: the closure's first and last, the rest is indented in it
    assert re.findall(r"^\S.*$", code, re.MULTILINE) == ["(function () {", "})();"]
    assert set(re.findall(r"\bwindow\.(\w+)\s*(?:\.\w+\s*)*=(?!=)", code)) <= {"ComposeUI"}


def _local_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Give the names that `function` binds: its parameters and what it assigns."""
    arguments = function.args
    every_argument = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *([arguments.vararg] if arguments.vararg else []),
        *([arguments.kwarg] if arguments.kwarg else []),
    ]
    names = {argument.arg for argument in every_argument}
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names - {function.name}


def _views_in_functions(path: Path) -> Iterator[tuple[ast.ClassDef, set[str]]]:
    """Give each view that a function of `path` defines, with the names of its functions."""
    pending: list[tuple[ast.AST, set[str]]] = [(ast.parse(path.read_text(encoding="utf-8")), set())]
    while pending:
        node, local = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local = local | _local_names(node)
        elif (
            isinstance(node, ast.ClassDef)
            and local
            and any("define_view" in ast.unparse(decorator) for decorator in node.decorator_list)
        ):
            yield node, local
        pending.extend((child, local) for child in ast.iter_child_nodes(node))


def test_a_view_is_defined_in_a_function_only_for_a_value_of_the_function() -> None:
    # `attrs` resolves a view's field types from its module's names: a view defined in a
    # function, e.g. to take a test's `tmp_path`, names in its fields only the module's
    paths = [*_python_files(SOURCE), *_python_files(ROOT / "tests"), *_python_files(ROOT / "docs")]
    wrong: list[str] = []
    for path in paths:
        for view, local in _views_in_functions(path):
            read = {
                node.id
                for statement in view.body
                for node in ast.walk(statement)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            }
            typed = {
                node.id
                for statement in view.body
                if isinstance(statement, ast.AnnAssign)
                for node in ast.walk(statement.annotation)
                if isinstance(node, ast.Name)
            }
            if not read & local:
                wrong.append(f"{_where(path, view)} {view.name} needs nothing of its function")
            wrong.extend(
                f"{_where(path, view)} {view.name} types a field with {name}"
                for name in sorted(typed & local)
            )
    assert wrong == []


def _is_driver_block(node: ast.AST, method: str) -> bool:
    """Tell whether `node` is an `async with driver.<method>(...)`."""
    return isinstance(node, ast.AsyncWith) and any(
        isinstance(item.context_expr, ast.Call)
        and ast.unparse(item.context_expr.func) == f"driver.{method}"
        for item in node.items
    )


def _changes_by_code(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Give each statement of `body` that changes a view as code, outside `by_code()`.

    What else a contract test does in an open view: wait on the driver (`await`), check
    (`assert`), or keep a value in a local name.
    """
    for node in body:
        if _is_driver_block(node, "by_code"):
            continue
        if isinstance(node, (ast.AsyncWith, ast.With, ast.If, ast.For, ast.AsyncFor)):
            yield from _changes_by_code([*node.body, *getattr(node, "orelse", [])])
        elif not (
            isinstance(node, ast.Assert)
            or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Await))
            or (
                isinstance(node, ast.Assign)
                and all(isinstance(target, ast.Name) for target in node.targets)
            )
        ):
            yield node


def test_a_contract_test_changes_a_view_by_code_in_by_code_only() -> None:
    # a widget can report a change by code late, in a message: `by_code()` handles it
    # before the test reads the reports, so a wrongly reported change can't come after them
    wrong = [
        f"{_where(path, change)} {ast.unparse(change)}"
        for path in sorted((ROOT / "tests" / "contracts").glob("test_*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.AsyncWith) and _is_driver_block(node, "open")
        for change in _changes_by_code(node.body)
    ]
    assert wrong == []
