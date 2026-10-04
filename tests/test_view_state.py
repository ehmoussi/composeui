"""Tests for the cattrs (un)structure hooks and MainView state persistence."""

import logging
from pathlib import Path
from typing import Any, Optional, Union

import pytest
from attrs import Factory

from composeui.core.application import _add_reference_to_signals
from composeui.core.renderer import Renderer, RendererContainer
from composeui.core.signal import Signal
from composeui.core.view import (
    CONVERTER,
    LabelView,
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
        self.values = {"a": "a", "b": "b"}


@define_view
class _RadioMainView(MainView):
    radio: _StrRadioGroupView = Factory(_StrRadioGroupView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Radio", extension=".radio")


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


def test_unstructure_includes_radio_group_values() -> None:
    view = _RadioMainView()
    data = CONVERTER.unstructure(view)
    assert data["radio"]["values"] == {"a": "a", "b": "b"}


def test_load_state_ignores_values_even_though_saved(tmp_path: Path) -> None:
    view = _RadioMainView()
    view.radio.value = "a"
    filepath = tmp_path / "state.json"
    view.save_state(filepath)
    assert filepath.read_text().find('"values"') != -1  # sanity check it's actually there

    fresh = _RadioMainView()
    fresh.load_state(filepath)  # must not crash on the unresolved-TValue `values` dict
    assert fresh.radio.values == {"a": "a", "b": "b"}  # untouched, from __attrs_post_init__
    assert fresh.radio.value == "a"


def test_radio_group_rejects_a_value_not_in_values() -> None:
    view = _RadioMainView()
    with pytest.raises(ValueError, match="not one of the available values"):
        view.radio.value = "not-an-option"
    assert view.radio.value is None  # rejected assignment leaves the field unchanged


def test_radio_group_accepts_none_and_members_of_values() -> None:
    view = _RadioMainView()
    view.radio.value = "a"
    assert view.radio.value == "a"
    view.radio.value = None
    assert view.radio.value is None


def test_radio_group_rejects_a_value_when_values_is_still_empty() -> None:
    view = RadioGroupView[str]()
    with pytest.raises(ValueError, match="Set `values` before setting `value`"):
        view.value = "a"


def test_radio_group_clears_value_when_values_no_longer_contains_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    view = _RadioMainView()
    view.radio.value = "b"
    with caplog.at_level(logging.WARNING, logger="COMPOSEUI_VIEW"):
        view.radio.values = {"a": "a"}  # "b" no longer an option

    assert view.radio.value is None
    assert any("no longer contains" in record.message for record in caplog.records)


def test_radio_group_keeps_value_when_still_a_member_of_new_values() -> None:
    view = _RadioMainView()
    view.radio.value = "a"
    view.radio.values = {"a": "a", "c": "c"}
    assert view.radio.value == "a"


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


def test_save_state_does_not_crash_with_a_live_status_bar_timer(tmp_path: Path) -> None:
    view = _RadioMainView()
    view.status_bar.show_message("hi")  # starts a live threading.Timer
    try:
        filepath = tmp_path / "state.json"
        view.save_state(filepath)  # must not raise TypeError: Timer not JSON serializable
        assert '"_timer"' not in filepath.read_text()
    finally:
        if view.status_bar._timer is not None:  # noqa: SLF001
            view.status_bar._timer.cancel()  # noqa: SLF001


def test_load_state_warns_and_clears_value_when_label_no_longer_exists(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    saved = _RadioMainView()
    saved.radio.value = "b"
    filepath = tmp_path / "state.json"
    saved.save_state(filepath)

    fresh = _RadioMainView()
    fresh.radio.values = {"a": "a"}  # "b" option no longer exists
    with caplog.at_level(logging.WARNING, logger="COMPOSEUI_VIEW"):
        fresh.load_state(filepath)

    assert fresh.radio.value is None
    assert any("_StrRadioGroupView.value" in record.message for record in caplog.records)


@define_view
class _StudyMainView(MainView):
    radio: _StrRadioGroupView = Factory(_StrRadioGroupView)
    note: LabelView = Factory(LabelView)

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self._init_app_info(title="Study", extension=".study")
        # set up after construction, not attrs defaults: a reset must restore these too
        self.radio.value = "a"
        self.note.text = "initial note"


def test_reset_state_brings_back_a_newly_built_main_view_in_place() -> None:
    view = _StudyMainView()
    radio, note = view.radio, view.note
    seen: list[Optional[str]] = []

    def on_changed(value: Optional[str]) -> None:
        seen.append(value)

    radio.value_changed.connect(on_changed)
    radio.values = {"b": "b", "c": "c"}  # drops "a", which clears the value
    radio.value = "c"
    note.text = "edited"
    view.minimum_width = 1
    view.state_filepath = Path("old.study")

    view.reset_state()

    # the same view objects, so renderers bound to them keep working
    assert view.radio is radio
    assert view.note is note
    assert radio.values == {"a": "a", "b": "b"}
    assert radio.value == "a"
    assert note.text == "initial note"
    assert view.minimum_width == 720
    assert view.state_filepath is None
    assert view.title == "Study"  # frozen field untouched
    radio.value_changed.emit("b")  # connections survive the reset
    assert seen == ["b"]


def test_the_new_action_resets_the_main_view() -> None:
    view = _StudyMainView()
    _add_reference_to_signals(view, None)  # what an application does: injects `main_view`
    view.note.text = "edited"

    view.file_menu.new.triggered.emit()

    assert view.note.text == "initial note"
