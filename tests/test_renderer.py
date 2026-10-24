"""Tests for the renderer contract every backend's renderers follow (`composeui.core.renderer`)."""

from __future__ import annotations

from typing import Any

import pytest

from composeui.core.renderer import (
    MissingRefreshAttributeFunctionError,
    NoRenderedObjectError,
    Renderer,
)
from composeui.core.view import LabelView


class _TextRenderer(Renderer[LabelView, list[str]]):
    """A renderer of a label's text into a list, the texts it showed."""

    def __init__(self, view: LabelView, attributes: tuple[str, ...] = ("text",)) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(dict.fromkeys(attributes, self._show))

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = []

    @property
    def shown(self) -> list[str] | None:
        return self._rendered_object

    @staticmethod
    def _show(_view: LabelView, rendered_object: list[str], value: Any) -> None:
        rendered_object.append(str(value))


def test_a_renderer_shows_a_field_by_its_handler_once_rendered() -> None:
    renderer = _TextRenderer(LabelView(text="Ready"))
    with pytest.raises(NoRenderedObjectError):
        renderer.refresh()
    with pytest.raises(NoRenderedObjectError):
        renderer.refresh_attribute("text", "Busy")

    renderer.render()
    renderer.refresh()
    renderer.refresh_attribute("text", "Busy")

    assert renderer.shown == ["Ready", "Busy"]


def test_a_renderer_refuses_a_field_without_a_handler_or_not_the_view_s() -> None:
    renderer = _TextRenderer(LabelView(), attributes=("text", "no_such_field"))
    renderer.render()

    with pytest.raises(MissingRefreshAttributeFunctionError, match="is_visible"):
        renderer.refresh_attribute("is_visible", value=False)
    with pytest.raises(AttributeError, match="no_such_field"):
        renderer.refresh_attribute("no_such_field", "x")
    with pytest.raises(AttributeError, match="no_such_field"):
        renderer.refresh()  # its handler for a field the view hasn't


def test_a_renderer_outside_a_toolkit_calls_back_at_once() -> None:
    renderer = _TextRenderer(LabelView())
    called: list[None] = []

    renderer.call_on_main_thread(lambda: called.append(None))

    assert called == [None]
