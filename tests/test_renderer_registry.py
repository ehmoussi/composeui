"""Covers the renderer registry (roadmap item 15).

``composeui.core.view`` used to pick renderer classes through hardcoded
``if renderer_type == RendererType.QT / elif TEXTUAL`` chains, one per view class,
each importing a backend module. Views now name their renderer with a registry key
and ``composeui.core.registry.create_renderer`` resolves it against the backend's
``RENDERERS`` mapping, so ``composeui.core`` stays free of backend imports and a
new backend only adds a `RendererType` member plus its own ``RENDERERS`` mapping.
"""

from __future__ import annotations

import subprocess
import sys
import types
from typing import TYPE_CHECKING

import pytest
from attrs import Factory

from composeui.core.registry import RendererType, _entry_points, create_renderer
from composeui.core.reload import rerun_program
from composeui.core.view import LabelRowInputView, LabelView, MainView, StatusBar, View, define_view

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# the tests compare every backend's mapping
pytest.importorskip("composeui.qtcore.renderers")
pytest.importorskip("composeui.textualcore.renderers")
pytest.importorskip("composeui.webcore.renderers")
from composeui.qtcore._renderers.content import QtStatusBarRenderer
from composeui.qtcore.renderers import RENDERERS as QT_RENDERERS
from composeui.textualcore._renderers.content import TextualStatusBarRenderer
from composeui.textualcore.renderers import RENDERERS as TEXTUAL_RENDERERS
from composeui.webcore.renderers import RENDERERS as WEB_RENDERERS
from composeui.webcore.webrenderer import WebRenderer


def test_importing_the_core_does_not_import_any_backend_toolkit() -> None:
    """The core must stay importable (and light) without Qt or Textual around."""
    code = (
        "import sys\n"
        "import composeui.core.view\n"
        "leaked = [m for m in ('qtpy', 'PySide6', 'PyQt5', 'PyQt6', 'textual')"
        " if m in sys.modules]\n"
        "assert not leaked, f'importing composeui.core.view imported {leaked}'\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603 (a command the code builds, no user input)


def test_every_backend_registers_the_same_renderer_keys_except_graphical_maps() -> None:
    """The terminal omits street maps; other views render on all three backends."""
    assert set(QT_RENDERERS) == set(WEB_RENDERERS) == set(TEXTUAL_RENDERERS) | {"map"}
    assert "markdown" in QT_RENDERERS


def test_loading_the_qt_backend_without_maps_does_not_load_qt_quick() -> None:
    code = (
        "import sys\n"
        "import composeui.qtcore.renderers\n"
        "assert 'qtpy.QtQuickWidgets' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603 (a command the code builds, no user input)


def test_create_renderer_resolves_a_key_to_the_backend_renderer() -> None:
    view = StatusBar()
    assert isinstance(create_renderer(RendererType.QT, "status_bar", view), QtStatusBarRenderer)
    assert isinstance(
        create_renderer(RendererType.TEXTUAL, "status_bar", view), TextualStatusBarRenderer
    )


def test_create_renderer_returns_none_for_a_key_the_backend_does_not_provide() -> None:
    """A partial backend degrades to not rendering the view, instead of crashing."""
    assert create_renderer(RendererType.QT, "not_a_widget_any_backend_knows", StatusBar()) is None


def test_a_labelled_row_isn_t_rendered_by_a_backend_without_its_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(WEB_RENDERERS, "form_label")  # e.g. a backend of an app's own
    row = LabelRowInputView(label="Name")

    row.render(RendererType.WEB)

    assert row.renderer is None


@define_view(renderer_key="fake_widgets.note")
class _PackageNote(View):
    """A view whose renderers a package adds."""


@define_view
class _PackageMainView(MainView):
    note: _PackageNote = Factory(_PackageNote)


_NOTE_RENDERERS = """
from markupsafe import Markup

from composeui.webcore.webrenderer import WebRenderer


class NoteRenderer(WebRenderer):
    _role = "note"

    def to_html(self, *, oob=False):
        return Markup("<p {}>A note</p>").format(self._root_attributes(oob=oob))


RENDERERS = {"fake_widgets.note": NoteRenderer}
"""


@pytest.fixture
def packages() -> Iterator[None]:
    """Forget the packages found so far, and those the test installs after it."""
    _entry_points.cache_clear()
    yield
    _entry_points.cache_clear()
    for name in ("fake_widgets", "broken_widgets"):
        sys.modules.pop(name, None)


def _install(folder: Path, distribution: str, web: str, modules: dict[str, str]) -> None:
    """Install `distribution` in `folder`, which adds `web`'s renderers to the web."""
    info = folder / f"{distribution.replace('-', '_')}-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text(f"[composeui.renderers]\nweb = {web}\n")
    for name, source in modules.items():
        (folder / f"{name}.py").write_text(source)
    sys.path.insert(0, str(folder))


@pytest.fixture
def path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the test its own `sys.path`, which `_install` adds to."""
    monkeypatch.setattr(sys, "path", list(sys.path))


@pytest.mark.usefixtures("packages", "path")
def test_a_package_s_view_shows_with_the_renderer_the_package_adds_to_its_backend(
    tmp_path: Path,
) -> None:
    _install(tmp_path, "fake-widgets", "fake_widgets:RENDERERS", {"fake_widgets": _NOTE_RENDERERS})
    main_view = _PackageMainView()

    main_view.render(RendererType.WEB)
    textual_note = _PackageNote()
    textual_note.render(RendererType.TEXTUAL)

    assert isinstance(main_view.note.renderer, sys.modules["fake_widgets"].NoteRenderer)
    assert textual_note.renderer is None  # the package adds nothing to Textual


@pytest.mark.usefixtures("packages", "path")
def test_a_broken_install_fails_only_the_views_of_its_own_package(tmp_path: Path) -> None:
    broken = "raise RuntimeError('loaded')"
    _install(tmp_path, "broken-widgets", "broken_widgets:RENDERERS", {"broken_widgets": broken})
    # installs cut short: no METADATA, with entry points or without
    (tmp_path / "half_installed-1.0.dist-info").mkdir()
    _install(tmp_path, "nameless", "nameless_widgets:RENDERERS", {})
    (tmp_path / "nameless-1.0.dist-info" / "METADATA").unlink()
    label = LabelView(text="Name")

    label.render(RendererType.WEB)

    assert label.renderer is not None
    assert create_renderer(RendererType.TEXTUAL, "map", label) is None  # a key ComposeUI lacks
    assert create_renderer(RendererType.WEB, "other_widgets.note", label) is None
    assert create_renderer(RendererType.WEB, "nameless_widgets.note", label) is None
    with pytest.raises(RuntimeError, match="loaded"):
        create_renderer(RendererType.WEB, "broken_widgets.note", label)


@pytest.mark.usefixtures("packages", "path")
@pytest.mark.parametrize(
    ("key", "error"),
    [
        ("label", "fake-widgets adds the renderer key 'label', which ComposeUI has"),
        ("other.note", "fake-widgets adds the renderer key 'other.note', which doesn't start"),
        # never looked for in fake_widgets, but refused once a key of fake_widgets is
        ("fake_widgets_extra.note", "doesn't start with 'fake_widgets.'"),
    ],
)
def test_a_package_can_t_add_a_key_outside_its_name(tmp_path: Path, key: str, error: str) -> None:
    source = _NOTE_RENDERERS.replace('{"fake_widgets.note"', f"{{{key!r}")
    _install(tmp_path, "fake-widgets", "fake_widgets:RENDERERS", {"fake_widgets": source})

    with pytest.raises(ValueError, match=error):
        _PackageNote().render(RendererType.WEB)


@pytest.mark.usefixtures("packages", "path")
def test_two_distributions_can_t_add_the_same_key(tmp_path: Path) -> None:
    _install(tmp_path, "fake-widgets", "fake_widgets:RENDERERS", {"fake_widgets": _NOTE_RENDERERS})
    _install(tmp_path, "fake-widgets-fork", "fake_widgets:RENDERERS", {})

    with pytest.raises(ValueError, match=r"fake-widgets(-fork)? and fake-widgets(-fork)? both add"):
        _PackageNote().render(RendererType.WEB)


@pytest.mark.usefixtures("packages", "path")
def test_a_distribution_installed_twice_adds_its_keys_once(tmp_path: Path) -> None:
    """Only the first copy on the path counts, as for an import of its modules."""
    for copy in ("first", "second"):
        _install(
            tmp_path / copy,
            "fake-widgets",
            "fake_widgets:RENDERERS",
            {"fake_widgets": _NOTE_RENDERERS},
        )
    note = _PackageNote()

    note.render(RendererType.WEB)

    assert note.renderer is not None


@pytest.mark.usefixtures("packages", "path")
def test_a_package_s_renderer_changed_under_the_program_shows_once_reloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A package installed from the program's folder, in editable mode, reloads as its code."""
    monkeypatch.chdir(tmp_path)
    _install(tmp_path, "fake-widgets", "fake_widgets:RENDERERS", {"fake_widgets": _NOTE_RENDERERS})
    script = tmp_path / "app.py"
    script.write_text(
        "from composeui.core.registry import RendererType, create_renderer\n"
        "from composeui.core.reload import keep_rerun\n"
        "from tests.test_renderer_registry import _PackageNote\n"
        "keep_rerun(create_renderer(RendererType.WEB, 'fake_widgets.note', _PackageNote()))\n"
    )
    program = types.ModuleType("__main__")
    program.__file__ = str(script)
    monkeypatch.setitem(sys.modules, "__main__", program)
    monkeypatch.setattr("sys.argv", ["app.py", "--reload"])
    before = create_renderer(RendererType.WEB, "fake_widgets.note", _PackageNote())
    assert isinstance(before, WebRenderer)
    before.render()
    (tmp_path / "fake_widgets.py").write_text(_NOTE_RENDERERS.replace("A note", "A new note"))

    after = rerun_program()
    after.render()

    assert "A note" in before.to_html()
    assert "A new note" in after.to_html()
