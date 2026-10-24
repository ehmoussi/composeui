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
from typing import TYPE_CHECKING

from composeui.core.registry import RendererType, create_renderer
from composeui.core.view import LabelRowInputView, StatusBar
from composeui.qtcore.qtrenderer import RENDERERS as QT_RENDERERS
from composeui.qtcore.qtrenderer import QtStatusBarRenderer
from composeui.textualcore.textualrenderer import RENDERERS as TEXTUAL_RENDERERS
from composeui.textualcore.textualrenderer import TextualStatusBarRenderer
from composeui.webcore.webrenderer import RENDERERS as WEB_RENDERERS

if TYPE_CHECKING:
    import pytest


def test_importing_the_core_does_not_import_any_backend_toolkit() -> None:
    """The core must stay importable (and light) without Qt or Textual around."""
    code = (
        "import sys\n"
        "import composeui.core.view\n"
        "leaked = [m for m in ('qtpy', 'PySide6', 'PyQt5', 'PyQt6', 'textual')"
        " if m in sys.modules]\n"
        "assert not leaked, f'importing composeui.core.view imported {leaked}'\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603


def test_every_backend_registers_the_same_renderer_keys() -> None:
    """A view rendering under one backend should render under all of them."""
    assert set(QT_RENDERERS) == set(TEXTUAL_RENDERERS) == set(WEB_RENDERERS)
    assert "markdown" in QT_RENDERERS


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
