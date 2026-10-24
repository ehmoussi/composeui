"""Tests for views' own behavior, outside any backend: what they accept, refuse and keep."""

from __future__ import annotations

import pytest

from composeui.core.view import LabelView, define_view


def _note(_instance: object, _attribute: object, value: str) -> str:
    return value.strip()


@define_view(on_setattr=_note)
class _OneHookView(LabelView):
    """A view with an `on_setattr` hook of its own."""


@define_view(on_setattr=[_note])
class _HooksView(LabelView):
    """A view with a list of `on_setattr` hooks of its own."""


@pytest.mark.parametrize("view_type", [_OneHookView, _HooksView])
def test_a_view_s_own_on_setattr_hooks_run_before_its_renderer_hears(
    view_type: type[LabelView],
) -> None:
    view = view_type()

    view.text = "  Ready  "

    assert view.text == "Ready"
