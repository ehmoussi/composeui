"""Tests of the web sliders, check boxes and progress bars."""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from typing import TYPE_CHECKING

from composeui.core.registry import RendererType
from composeui.webcore._renderers.forms import WebFormLabelRenderer
from composeui.webcore.changes import collect_dirty
from composeui.webcore.webrenderer import (
    handle_event,
    render_dirty,
)
from tests.ranges import RangesMainView
from tests.webcore.support import _element, _field_id, _find, _part, _selected, _swapped, _widget_id
from tests.workers import OpacityMainView, WorkersMainView

if TYPE_CHECKING:
    if sys.version_info >= (3, 11):
        import httpx2 as httpx
    else:
        import httpx
    from starlette.testclient import TestClient

    from examples.pipeform import PipeMainView
    from tests.pages import PagesMainView


def test_a_slider_is_a_range_input_named_by_its_label_and_stopping_on_its_steps() -> None:
    view = WorkersMainView()
    view.render(RendererType.WEB)
    workers = view.form.workers
    label, field = _part(workers, "label"), _part(workers, "field")
    assert isinstance(label, WebFormLabelRenderer)
    moves: list[int] = []
    workers.value_changed.connect(moves.append)
    slider = _element(field.to_html(), field.widget_id)
    (range_input,) = [a for tag, a in slider.descendants if tag == "input"]
    assert range_input["type"] == "range"
    # the last step, short of 16, is the input's maximum, so the browser never stops past it
    assert [range_input[name] for name in ("min", "max", "step", "value")] == ["2", "14", "3", "5"]
    assert range_input["aria-labelledby"] == label.text_id
    assert slider.text == "5"  # the value beside the track

    fragments = handle_event(field, "input", {"value": "8"})
    assert (workers.value, moves) == (8, [8])
    assert field.widget_id not in fragments  # never swapped back while dragged
    handle_event(field, "change", {"value": "8"})  # the release, after the debounced move
    assert moves == [8]
    handle_event(field, "input", {"value": "16"})
    assert (workers.value, moves) == (14, [8, 14])
    handle_event(field, "input", {"value": "abc"})
    assert workers.value == 14


def test_a_decimal_slider_posts_exact_steps_and_ignores_what_is_not_a_finite_number() -> None:
    view = OpacityMainView()
    view.render(RendererType.WEB)
    opacity = view.form.opacity
    field = _part(opacity, "field")
    moves: list[float] = []
    opacity.value_changed.connect(moves.append)
    slider = _element(field.to_html(), field.widget_id)
    (range_input,) = [a for tag, a in slider.descendants if tag == "input"]
    names = ("min", "max", "step", "value", "data-decimals")
    assert [range_input[name] for name in names] == ["0.0", "0.3", "0.1", "0.1", "1"]
    assert slider.text == "0.1"

    handle_event(field, "input", {"value": "0.30000000000000004"})  # snapped to its step
    assert (opacity.value, moves) == (0.3, [0.3])
    for posted in ("nan", "inf", "-inf", "1e999", "abc"):
        handle_event(field, "input", {"value": posted})
    assert (opacity.value, moves) == (0.3, [0.3])


def test_a_range_slider_posts_both_handles_which_stop_on_each_other() -> None:
    view = RangesMainView()
    view.render(RendererType.WEB)
    hours = view.hours
    field = _part(hours, "field")
    moves: list[tuple[int, int]] = []
    hours.value_changed.connect(moves.append)
    slider = _element(field.to_html(), field.widget_id)
    low, high = [a for tag, a in slider.descendants if tag == "input"]
    names = ("name", "max", "value", "aria-label", "aria-valuetext")
    assert [low[name] for name in names] == ["low", "23", "8", "From", "8"]
    assert [high[name] for name in names] == ["high", "23", "18", "To", "18"]
    assert slider.text == "8 \u2013 18"

    handle_event(field, "input", {"low": "9", "high": "18"})
    handle_event(field, "change", {"low": "9", "high": "18"})  # the same: reported once
    handle_event(field, "input", {"low": "20", "high": "18"})  # the low one past the high
    assert (hours.value, moves) == ((18, 18), [(9, 18), (18, 18)])
    # on one another near the end: the low handle on top, which can still move down
    track = _element(field.to_html(), field.widget_id).descendants[0]
    assert "data-low-on-top" in track[1]
    handle_event(field, "input", {"low": "30", "high": "2"})  # both moved: in order, in range
    assert hours.value == (2, 23)
    for posted in ({"low": "x", "high": "3"}, {"low": "1"}):
        handle_event(field, "input", posted)
    assert len(moves) == 3


def test_a_decimal_range_slider_posts_positions_which_give_exact_steps() -> None:
    view = RangesMainView()
    view.render(RendererType.WEB)
    distance = view.distance
    field = _part(distance, "field")
    track = _element(field.to_html(), field.widget_id).descendants[0][1]
    assert [track[name] for name in ("data-first", "data-step", "data-decimals")] == [
        "0.0",
        "0.5",
        "1",
    ]

    handle_event(field, "input", {"low": "3", "high": "5"})

    assert distance.value == (1.5, 2.5)


def test_a_slider_without_fill_turns_off_the_range_input_s_fill() -> None:
    view = OpacityMainView()
    view.render(RendererType.WEB)
    opacity = view.form.opacity
    field = _part(opacity, "field")

    def input_attributes() -> dict[str, str | None]:
        slider = _element(field.to_html(), field.widget_id)
        (range_input,) = [a for tag, a in slider.descendants if tag == "input"]
        return range_input

    assert "style" not in input_attributes()

    with collect_dirty() as dirty:
        opacity.is_filled = False

    assert list(dirty) == [field.widget_id]
    assert input_attributes()["style"] == "--range-fill: 0"


def test_the_checkbox_is_named_by_its_text_and_its_group_by_the_row_label(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    insulated = pipe_main_view.pages.inputs.pipe_form.insulated
    label_id, field_id = f"{_widget_id(_part(insulated, 'label'))}-text", _field_id(insulated)

    page = pipe_client.get("/").text

    field = _element(page, field_id)
    assert field.attributes["role"] == "group"
    assert field.attributes["aria-labelledby"] == label_id
    assert field.attributes["aria-describedby"] == _widget_id(_part(insulated, "log"))
    # a `<div>` isn't labelable: `for=` would point at nothing
    assert "for" not in _element(page, label_id).attributes
    (box,) = [attributes for tag, attributes in field.descendants if tag == "input"]
    assert box["type"] == "checkbox"
    assert "checked" not in box
    assert field.text == "Insulated pipe"  # inside the box's own `<label>`


def test_toggling_the_checkbox_enables_its_row_without_swapping_the_box(
    pipe_main_view: PipeMainView, pipe_client: TestClient
) -> None:
    form = pipe_main_view.pages.inputs.pipe_form
    field_id = _field_id(form.insulated)
    thickness_id = _field_id(form.insulation_thickness)
    toggled: list[bool] = []
    form.insulated.toggled.connect(toggled.append)

    def toggle(**checked: str) -> str:
        response: httpx.Response = pipe_client.post(
            f"/widget/{field_id}", data={"event": "change", **checked}
        )
        return response.text

    body = toggle(checked="on")

    assert form.insulated.is_checked is True
    assert "disabled" not in _swapped(body, thickness_id).attributes
    assert _find(body, field_id) is None

    toggle(checked="on")  # posted twice (e.g. a retry): no second toggle
    body = toggle()  # an unchecked box posts no value

    assert form.insulated.is_checked is False
    assert "disabled" in _swapped(body, thickness_id).attributes
    assert toggled == [True, False]


def test_checking_the_box_on_the_server_swaps_it_checked(pipe_main_view: PipeMainView) -> None:
    insulated = pipe_main_view.pages.inputs.pipe_form.insulated
    field = _part(insulated, "field")

    with collect_dirty() as dirty:
        insulated.is_checked = True

    assert field.widget_id in dirty
    assert _selected(_swapped(render_dirty(dirty), field.widget_id)) == ["on"]


def test_the_progress_bar_swaps_in_its_count_and_its_unknown_length(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    page = pages_client.get("/results").text
    (main_view,) = pages_views
    progress = main_view.router.results.progress
    bar_id = _widget_id(progress.renderer)
    bar = _element(page, bar_id)
    assert (bar.tag, bar.attributes["value"], bar.attributes["max"]) == ("progress", "0", "100")
    submit = main_view.router.inputs.submit

    def advance() -> None:
        progress.value = 250

    submit.clicked.connect(advance)
    response = pages_client.post(f"/widget/{_widget_id(submit.renderer)}", data={"event": "click"})
    bar = _swapped(response.text, bar_id)
    assert (bar.attributes["value"], bar.attributes["max"]) == ("100", "100")  # clamped

    progress.maximum = None
    bar = _element(pages_client.get(f"/widget/{bar_id}").text, bar_id)
    # no value: the browser's own bar for a task of unknown length
    assert "value" not in bar.attributes
    assert "max" not in bar.attributes
