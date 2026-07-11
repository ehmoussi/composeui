"""Tests for the cattrs (un)structure hooks and MainView state persistence."""

import logging
from pathlib import Path
from typing import Any, Optional, Union

import pytest
from attrs import Factory

from composeui.core.renderer import Renderer, RendererContainer
from composeui.core.signal import Signal
from composeui.core.view import (
    CONVERTER,
    MainView,
    RadioGroupView,
    _is_omitted_type,
    define_view,
)


# Generic mixins must be bound to a concrete type through a subclass (like
# `EdgeTypeView(LabelRowRadioGroupView[EdgeType])` in examples/pipeform.py), not by
# annotating a field directly as `RadioGroupView[str]`: attrs/cattrs' type resolution
# machinery can't handle a subscripted generic alias used as a field's own type.
@define_view
class _StrRadioGroupView(RadioGroupView[str]):
    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        object.__setattr__(self, "values", {"a": "a", "b": "b"})


@define_view
class _RadioMainView(MainView):
    radio: _StrRadioGroupView = Factory(_StrRadioGroupView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        object.__setattr__(self, "title", "Radio")
        object.__setattr__(self, "extension", ".radio")


def test_is_omitted_type_detects_signal_renderer_and_container() -> None:
    assert _is_omitted_type(Signal[str]) is True
    assert _is_omitted_type(Optional[Union[Renderer[Any, Any], RendererContainer[Any]]]) is True


def test_is_omitted_type_ignores_unrelated_types() -> None:
    assert _is_omitted_type(int) is False
    assert _is_omitted_type(Optional[int]) is False
    assert _is_omitted_type(type(None)) is False


def test_unstructure_omits_signal_and_renderer_fields() -> None:
    view = _RadioMainView()
    data = CONVERTER.unstructure(view)
    assert "renderer" not in data
    assert "renderer" not in data["radio"]
    assert "value_changed" not in data["radio"]


def test_unstructure_serializes_radio_group_value_as_its_label() -> None:
    view = _RadioMainView()
    view.radio.value = "b"
    data = CONVERTER.unstructure(view)
    assert data["radio"]["value"] == "b"  # the label, not necessarily the raw TValue

    view.radio.value = None
    assert CONVERTER.unstructure(view)["radio"]["value"] is None


def test_save_and_load_state_round_trip_preserves_renderer_bindings(tmp_path: Path) -> None:
    view = _RadioMainView()
    view.minimum_width = 999
    view.status_bar.message = "hi"
    view.radio.value = "b"

    filepath = tmp_path / "state.json"
    view.save_state(filepath)
    assert view.state_filepath == filepath

    fresh = _RadioMainView()
    status_bar_before = fresh.status_bar
    assert fresh.radio.value is None  # fresh view, nothing selected yet

    fresh.load_state(filepath)

    assert fresh.minimum_width == 999
    assert fresh.status_bar.message == "hi"
    assert fresh.status_bar is status_bar_before
    assert fresh.radio.value == "b"
    assert fresh.state_filepath == filepath
    assert fresh.title == "Radio"  # frozen field untouched


def test_load_state_warns_and_clears_value_when_label_no_longer_exists(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    saved = _RadioMainView()
    saved.radio.value = "b"
    filepath = tmp_path / "state.json"
    saved.save_state(filepath)

    fresh = _RadioMainView()
    object.__setattr__(fresh.radio, "values", {"a": "a"})  # "b" option no longer exists
    with caplog.at_level(logging.WARNING, logger="COMPOSEUI_VIEW"):
        fresh.load_state(filepath)

    assert fresh.radio.value is None
    assert any("_StrRadioGroupView.value" in record.message for record in caplog.records)
