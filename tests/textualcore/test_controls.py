"""Tests of the Textual sliders, check boxes, buttons and progress bars."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_fspicker")

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import (
    Button,
    Checkbox,
    ProgressBar,
)

from composeui.core.registry import RendererType
from composeui.core.view import (
    ButtonVariant,
)
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets import composeslider
from composeui.textualcore.widgets.composerange import ComposeRangeSlider
from composeui.textualcore.widgets.composeslider import ComposeSlider
from examples.pipeform import PipeMainView
from tests.pages import PagesMainView
from tests.ranges import RangesMainView
from tests.workers import OpacityMainView, WorkersMainView

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.pilot import Pilot
    from textual.timer import Timer


from tests.textualcore.support import _app_of, _field_widget


def _track_and_value(slider: ComposeSlider) -> tuple[str, str]:
    """Get a slider's track and its value, as drawn on its one line."""
    rendered = slider.render()
    assert isinstance(rendered, Text)
    track, value = rendered.plain.split()
    return track, value


@pytest.mark.asyncio
async def test_a_slider_stops_on_its_steps_its_value_drawn_beside_the_track() -> None:
    view = WorkersMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    workers = view.form.workers
    moves: list[int] = []
    workers.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(workers.renderer)
        assert isinstance(slider, ComposeSlider)
        retries = _field_widget(view.form.retries.renderer)
        await pilot.pause()
        assert slider.region.height == retries.region.height  # a row as tall as an input's
        track, value = _track_and_value(slider)
        assert value == "5"
        first_handle = track.index("●")

        slider.focus()
        await pilot.press("right")
        assert (workers.value, moves) == (8, [8])
        track, value = _track_and_value(slider)
        assert value == "8"
        assert track.index("●") > first_handle
        await pilot.press("end")
        assert (workers.value, moves) == (14, [8, 14])  # the last step, short of 16
        end_track, value = _track_and_value(slider)
        assert value == "14"
        assert len(end_track) == len(track)  # the value's slot as wide: the track keeps its length

        # the track's first column, past the padding, then its last, before the value
        await pilot.click(slider, offset=(1, 1))
        assert (workers.value, moves) == (2, [8, 14, 2])
        await pilot.click(slider, offset=(len(track), 1))
        assert (workers.value, moves) == (14, [8, 14, 2, 14])

        workers.value = 6  # set in code: shown at its nearest step, and not reported
        await pilot.pause()
        assert (_track_and_value(slider)[1], moves) == ("5", [8, 14, 2, 14])


@pytest.mark.asyncio
async def test_a_range_slider_s_handles_move_by_keys_and_clicks_stopping_on_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a slow machine's rest would report a drag's steps: the drag here reports on release
    monkeypatch.setattr(composeslider, "DRAG_REPORT_DELAY_MS", _LONG_REST_MS)
    view = RangesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    hours = view.hours
    moves: list[tuple[int, int]] = []
    hours.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(hours.renderer)
        assert isinstance(slider, ComposeRangeSlider)
        await pilot.pause()
        assert slider.region.height == 3  # a row as tall as an input's
        assert slider.ends_text() == "8 \u2013 18"
        rendered = slider.render()
        assert isinstance(rendered, Text)
        assert rendered.plain.count("●") == 2  # a handle each

        slider.focus()
        await pilot.press("right", "end", "left")  # the low one at first, then the high one
        assert moves == [(9, 18), (9, 23), (9, 22)]
        # the track's first column, past the padding: the nearer handle, the low one
        await pilot.click(slider, offset=(1, 1))
        assert hours.value == (0, 22)

        hours.value = (20, 20)  # set in code: shown, and not reported
        await pilot.pause()
        assert (slider.low, slider.high, len(moves)) == (20, 20, 4)
        # on one another near the end: the low handle, which can still move down
        column = 1 + round(20 * (slider._track_width() - 1) / 23)  # noqa: SLF001
        await pilot.click(slider, offset=(column, 1))
        await pilot.press("left")
        assert hours.value == (19, 20)
        hours.value = (5, 5)
        await pilot.pause()
        width = slider._track_width()  # noqa: SLF001
        # beside both, past them: the high one, on the side of the click; then a page and a drag
        await pilot.click(slider, offset=(1 + round(9 * (width - 1) / 23), 1))
        await pilot.press("pagedown")
        await pilot.mouse_down(slider, offset=(1 + round(8 * (width - 1) / 23), 1))
        await pilot.hover(slider, offset=(1 + round(15 * (width - 1) / 23), 1))
        await pilot.mouse_up(slider, offset=(1 + round(15 * (width - 1) / 23), 1))
        await pilot.hover(slider, offset=(1, 1))  # released: no move
        await pilot.pause()
        # pressed at 8, nearer the high handle at 7, then dragged: reported once, on release
        assert moves[-3:] == [(5, 9), (5, 7), (5, 15)]


@pytest.mark.asyncio
async def test_a_decimal_slider_stops_on_exact_decimal_steps() -> None:
    view = OpacityMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    opacity = view.form.opacity
    moves: list[float] = []
    opacity.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(opacity.renderer)
        assert isinstance(slider, ComposeSlider)
        await pilot.pause()
        assert _track_and_value(slider)[1] == "0.1"

        slider.focus()
        await pilot.press("end")
        assert (opacity.value, moves) == (0.3, [0.3])
        assert _track_and_value(slider)[1] == "0.3"
        await pilot.press("home")
        assert (opacity.value, _track_and_value(slider)[1]) == (0.0, "0.0")

        opacity.value = 0.14  # set in code: shown at its nearest step, and not reported
        await pilot.pause()
        assert (_track_and_value(slider)[1], moves) == ("0.1", [0.3, 0.0])


@pytest.mark.asyncio
async def test_a_slider_without_fill_draws_its_track_alike_on_both_sides_of_its_handle() -> None:
    view = OpacityMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    opacity = view.form.opacity
    opacity.value = 0.2

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(opacity.renderer)
        assert isinstance(slider, ComposeSlider)
        await pilot.pause()
        filled, _ = _track_and_value(slider)
        assert "━" in filled

        assert "━" in app.export_screenshot()

        opacity.is_filled = False
        await pilot.pause()
        unfilled, _ = _track_and_value(slider)
        assert "━" not in app.export_screenshot()  # what the screen shows: redrawn
        assert unfilled.index("●") == filled.index("●")

        opacity.is_filled = True
        await pilot.pause()
        assert _track_and_value(slider)[0] == filled


@pytest.mark.asyncio
async def test_pressing_the_checkbox_checks_the_view_and_enables_its_row() -> None:
    view = PipeMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    insulated = view.pages.inputs.pipe_form.insulated
    toggled: list[bool] = []
    insulated.toggled.connect(toggled.append)

    async with app.run_test() as pilot:
        await pilot.pause()
        checkbox = _field_widget(insulated.renderer)
        assert isinstance(checkbox, Checkbox)
        assert str(checkbox.label) == "Insulated pipe"
        thickness_widget = _field_widget(view.pages.inputs.pipe_form.insulation_thickness.renderer)
        assert thickness_widget.disabled

        checkbox.focus()
        await pilot.press("space")
        await pilot.pause()

        assert insulated.is_checked is True
        assert not thickness_widget.disabled  # toggled -> the thickness row
        assert toggled == [True]

        # set in code: the box follows, but only the user's toggles are reported
        insulated.is_checked = False
        await pilot.pause()
        assert checkbox.value is False
        assert toggled == [True]


@pytest.mark.asyncio
async def test_the_progress_bar_follows_its_view() -> None:
    view = PagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    progress = view.router.results.progress
    assert isinstance(progress.renderer, TextualWidgetRenderer)
    bar = progress.renderer.widget
    assert isinstance(bar, ProgressBar)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert (bar.progress, bar.total) == (0, 100)
        progress.value = 40
        progress.maximum = 200
        await pilot.pause()
        assert (bar.progress, bar.total) == (40, 200)
        progress.value = 250
        await pilot.pause()
        assert bar.progress == 200  # full, not past its end
        progress.maximum = None
        await pilot.pause()
        assert bar.percentage is None  # Textual's bar for a task of unknown length


@pytest.mark.asyncio
async def test_pressing_the_button_runs_what_its_view_connects() -> None:
    view = PagesMainView()
    view.render(RendererType.TEXTUAL)
    assert isinstance(view.renderer, TextualMainRenderer)
    app = view.renderer.app
    assert app is not None
    inputs = view.router.inputs
    assert isinstance(inputs.submit.renderer, TextualWidgetRenderer)
    button = inputs.submit.renderer.widget
    assert isinstance(button, Button)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert str(button.label) == "Submit"
        inputs.name.text = "Ada"

        await pilot.click(button)
        await pilot.pause()

        assert view.router.results.total.text == "Submitted: Ada"
        inputs.submit.text = "Send"
        await pilot.pause()
        assert str(button.label) == "Send"
        assert button.variant == "primary"
        inputs.submit.variant = ButtonVariant.DANGER
        await pilot.pause()
        assert button.variant == "error"


@pytest.mark.asyncio
async def test_a_slider_moves_by_a_page_and_follows_a_drag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a slow machine's rest would report a drag's steps: the drag here reports on release
    monkeypatch.setattr(composeslider, "DRAG_REPORT_DELAY_MS", _LONG_REST_MS)
    view = WorkersMainView()
    app = _app_of(view)
    workers = view.form.workers
    moves: list[int] = []
    workers.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(workers.renderer)
        assert isinstance(slider, ComposeSlider)
        await pilot.pause()
        slider.focus()
        await pilot.press("pageup", "pagedown")  # a tenth of the track, at least a step
        track, _ = _track_and_value(slider)
        await pilot.mouse_down(slider, offset=(1, 1))
        await pilot.hover(slider, offset=(len(track) // 2, 1))
        await pilot.mouse_up(slider, offset=(len(track) // 2, 1))
        await pilot.hover(slider, offset=(1, 1))  # released: no move
        await pilot.pause()

        # by a page each, then pressed at the start and dragged: reported once, on release
        assert moves[:2] == [8, 5]
        assert len(moves) == 3
        assert 2 < moves[-1] < 14  # dragged to the track's middle
        assert workers.value == moves[-1]


async def _until(pilot: Pilot[Any], is_done: Callable[[], bool]) -> None:
    """Pause until `is_done`, at most a few seconds: a timer's work, not a fixed wait."""
    for _ in range(100):
        if is_done():
            return
        await pilot.pause(0.05)


#: a rest longer than any test: a drag's report then waits for the release
_LONG_REST_MS = 10_000


@pytest.mark.asyncio
async def test_a_slider_reports_a_drag_once_its_handle_rests_and_on_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = WorkersMainView()
    app = _app_of(view)
    workers = view.form.workers
    moves: list[int] = []
    workers.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(workers.renderer)
        assert isinstance(slider, ComposeSlider)
        await pilot.pause()
        width = slider._track_width()  # noqa: SLF001

        def at(position: int) -> tuple[int, int]:
            return (1 + round(position * (width - 1) / slider.last), 1)

        await pilot.mouse_down(slider, offset=at(1))  # the handle, at 5
        await pilot.hover(slider, offset=at(2))
        await _until(pilot, lambda: moves == [8])  # once the handle rests
        assert (slider.position, moves) == (2, [8])
        await pilot.mouse_up(slider, offset=at(2))

        # each step of a drag not reported: the app's work on each would make the handle lag
        monkeypatch.setattr(composeslider, "DRAG_REPORT_DELAY_MS", _LONG_REST_MS)
        await pilot.mouse_down(slider, offset=at(2))
        await pilot.hover(slider, offset=at(3))
        await pilot.hover(slider, offset=at(4))
        assert (slider.position, workers.value, moves) == (4, 8, [8])
        await pilot.mouse_up(slider, offset=at(4))
        assert (workers.value, moves) == (14, [8, 14])  # on release, at once

        await pilot.mouse_down(slider, offset=at(4))
        await pilot.hover(slider, offset=at(3))
        workers.value = 11  # set in code before the drag's move is reported: the app's wins
        await pilot.mouse_up(slider, offset=at(3))
        assert (slider.position, moves) == (3, [8, 14])


@pytest.mark.asyncio
async def test_a_rest_s_call_on_its_way_after_the_release_reports_nothing_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # no rest before the release: the test makes its call come late itself
    monkeypatch.setattr(composeslider, "DRAG_REPORT_DELAY_MS", _LONG_REST_MS)
    view = WorkersMainView()
    app = _app_of(view)
    workers = view.form.workers
    moves: list[int] = []
    workers.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(workers.renderer)
        assert isinstance(slider, ComposeSlider)
        await pilot.pause()
        width = slider._track_width()  # noqa: SLF001
        rests: list[Callable[[], None]] = []
        set_timer = slider.set_timer

        def keeping_its_call(delay: float, callback: Callable[[], None]) -> Timer:
            rests.append(callback)
            return set_timer(delay, callback)

        monkeypatch.setattr(slider, "set_timer", keeping_its_call)
        await pilot.mouse_down(slider, offset=(1, 1))
        await pilot.hover(slider, offset=(width // 2, 1))
        await pilot.mouse_up(slider, offset=(width // 2, 1))
        assert len(moves) == 1  # on release
        # a slow machine: the rest's timer fired as the release came, its call already queued
        rests[-1]()
        assert len(moves) == 1


@pytest.mark.asyncio
async def test_a_range_slider_reports_a_drag_once_its_handle_rests_and_on_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = RangesMainView()
    app = _app_of(view)
    hours = view.hours
    moves: list[tuple[int, int]] = []
    hours.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(hours.renderer)
        assert isinstance(slider, ComposeRangeSlider)
        await pilot.pause()
        width = slider._track_width()  # noqa: SLF001

        def at(position: int) -> tuple[int, int]:
            return (1 + round(position * (width - 1) / slider.last), 1)

        await pilot.mouse_down(slider, offset=at(18))  # the high handle of (8, 18)
        await pilot.hover(slider, offset=at(19))
        await _until(pilot, lambda: moves == [(8, 19)])  # once the handle rests
        assert moves == [(8, 19)]
        await pilot.mouse_up(slider, offset=at(19))

        monkeypatch.setattr(composeslider, "DRAG_REPORT_DELAY_MS", _LONG_REST_MS)
        await pilot.mouse_down(slider, offset=at(19))
        await pilot.hover(slider, offset=at(20))
        await pilot.hover(slider, offset=at(21))
        assert (slider.high, hours.value, moves) == (21, (8, 19), [(8, 19)])
        await pilot.mouse_up(slider, offset=at(21))
        assert (hours.value, moves) == ((8, 21), [(8, 19), (8, 21)])  # on release, at once

        await pilot.mouse_down(slider, offset=at(21))
        await pilot.hover(slider, offset=at(20))
        await pilot.press("left")  # a key, even during a drag: at once
        assert moves[2:] == [(8, 19)]
        await pilot.mouse_up(slider, offset=at(20))  # the mouse moved back to 20 first
        assert moves[2:] == [(8, 19), (8, 20)]

        await pilot.mouse_down(slider, offset=at(21))
        await pilot.hover(slider, offset=at(22))
        hours.value = (8, 22)  # set in code before the drag's move is reported: the app's wins
        await pilot.mouse_up(slider, offset=at(22))
        assert (slider.high, len(moves)) == (22, 4)


@pytest.mark.asyncio
@pytest.mark.parametrize("is_range", [False, True])
async def test_a_slider_too_narrow_for_its_track_draws_none_and_takes_no_drag(
    *, is_range: bool
) -> None:
    view = RangesMainView() if is_range else WorkersMainView()
    app = _app_of(view)
    moves: list[object] = []
    row = view.hours if isinstance(view, RangesMainView) else view.form.workers
    row.value_changed.connect(moves.append)

    async with app.run_test(size=(80, 24)) as pilot:
        slider = _field_widget(row.renderer)
        assert isinstance(slider, (ComposeSlider, ComposeRangeSlider))
        await pilot.pause()
        # the padding, its value's slot and a space, no track: the range's, "23 - 23", 7 wide
        slider.styles.width = 10 if is_range else 4
        await pilot.pause()
        drawn = str(slider.render())
        await pilot.mouse_down(slider, offset=(1, 0))
        await pilot.mouse_up(slider, offset=(1, 0))

        assert (drawn, moves) == ("", [])
