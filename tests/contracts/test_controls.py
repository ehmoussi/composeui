"""The rules of the check boxes and the sliders on every backend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NamedTuple

import pytest
from attrs import Factory

from composeui.core.view import (
    CheckBoxView,
    FloatRangeSliderView,
    FloatSliderView,
    MainView,
    RangeSliderView,
    SliderView,
    define_view,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.contracts.support import Driver


@define_view
class _ControlsMainView(MainView):
    insulated: CheckBoxView = Factory(lambda: CheckBoxView(text="Insulated"))
    workers: SliderView = Factory(lambda: SliderView(minimum=2, maximum=16, step=3, value=5))
    opacity: FloatSliderView = Factory(lambda: FloatSliderView(maximum=0.3, step=0.1, value=0.2))
    hours: RangeSliderView = Factory(lambda: RangeSliderView(maximum=23, value=(8, 18)))
    distance: FloatRangeSliderView = Factory(
        lambda: FloatRangeSliderView(maximum=3.0, step=0.5, value=(0.5, 2.0))
    )


@pytest.mark.asyncio
async def test_a_check_box_reports_the_user_s_toggles_not_the_code_s(driver: Driver) -> None:
    view = _ControlsMainView()
    insulated = view.insulated
    toggled: list[bool] = []
    insulated.toggled.connect(toggled.append)

    async with driver.open(view):
        async with driver.by_code():
            insulated.is_checked = True
        assert (driver.is_checked(insulated), toggled) == (True, [])

        await driver.toggle(insulated)
        assert (insulated.is_checked, driver.is_checked(insulated), toggled) == (
            False,
            False,
            [False],
        )

        await driver.toggle(insulated)
        async with driver.by_code():
            insulated.is_checked = False  # once the user checked it
        assert (driver.is_checked(insulated), toggled) == (False, [False, True])


def _set_workers(view: _ControlsMainView) -> None:
    view.workers.value = 9


def _set_opacity(view: _ControlsMainView) -> None:
    view.opacity.value = 0.14


def _set_hours(view: _ControlsMainView) -> None:
    view.hours.value = (2, 20)


def _set_hours_together(view: _ControlsMainView) -> None:
    view.hours.value = (20, 20)  # the handles on each other


def _set_distance(view: _ControlsMainView) -> None:
    view.distance.value = (1.2, 2.6)


class _Case(NamedTuple):
    name: str  # of the slider
    set_by_code: Callable[[_ControlsMainView], None]
    shown: str  # the value set, at its nearest step
    end: Literal["start", "end"]  # where the user slides a handle
    moved: object  # the slider's value then
    moved_shown: str


_CASES = [
    _Case("workers", _set_workers, "8", "end", 14, "14"),  # the last step, short of 16
    _Case("opacity", _set_opacity, "0.1", "start", 0.0, "0.0"),
    _Case("hours", _set_hours, "2 \u2013 20", "end", (2, 23), "2 \u2013 23"),
    _Case("hours", _set_hours_together, "20 \u2013 20", "start", (0, 20), "0 \u2013 20"),
    _Case("distance", _set_distance, "1.0 \u2013 2.5", "start", (0.0, 2.5), "0.0 \u2013 2.5"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _CASES, ids=[case.name for case in _CASES])
async def test_a_slider_reports_the_user_s_moves_not_the_code_s(
    driver: Driver, case: _Case
) -> None:
    view = _ControlsMainView()
    slider = getattr(view, case.name)
    moves: list[object] = []
    slider.value_changed.connect(moves.append)

    async with driver.open(view):
        async with driver.by_code():
            case.set_by_code(view)
        assert (driver.slider_text(slider), moves) == (case.shown, [])

        await driver.slide(slider, case.end)
        assert (slider.value, driver.slider_text(slider), moves) == (
            case.moved,
            case.moved_shown,
            [case.moved],
        )

        async with driver.by_code():
            case.set_by_code(view)  # again, once the user moved it
        assert (driver.slider_text(slider), moves) == (case.shown, [case.moved])
