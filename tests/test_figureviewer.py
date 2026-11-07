"""Tests of the example figureviewer: a slider redraws a Matplotlib figure in a task."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

pytest.importorskip("matplotlib")

from composeui.core.application import Application
from composeui.core.study import open_study
from examples.figureviewer import LOGO, FigureViewerMainView, wave_figure

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def main_view() -> FigureViewerMainView:
    main_view = Application(build_main_view=FigureViewerMainView).main_view
    main_view.loaded.emit()  # as the app does when it starts
    return main_view


def test_the_app_starts_with_its_logo_and_the_figure_of_the_slider_s_value(
    main_view: FigureViewerMainView,
) -> None:
    assert main_view.logo.image == LOGO
    assert LOGO.is_file()
    assert isinstance(main_view.wave.image, bytes)


def test_a_move_of_the_slider_shows_the_figure_of_its_value(
    main_view: FigureViewerMainView,
) -> None:
    first = main_view.wave.image

    main_view.frequency.value = 7
    main_view.frequency.value_changed.emit(7)
    main_view.jobs.wait()

    assert main_view.drawing.error is None
    assert main_view.wave.image != first


def _first_peak(frequency: int) -> float:
    (line,) = wave_figure(frequency).axes[0].get_lines()
    return float(np.asarray(line.get_xdata())[np.asarray(line.get_ydata()).argmax()])


def test_a_figure_draws_its_frequency() -> None:
    # the first peak of a damped wave comes twice as soon at twice the frequency
    assert _first_peak(1) == pytest.approx(2 * _first_peak(2), rel=0.1)


def test_an_opened_study_draws_the_figure_of_its_value_again(
    main_view: FigureViewerMainView, tmp_path: Path
) -> None:
    study = tmp_path / "wave.figure"
    main_view.frequency.value = 7
    main_view.save_state(study)
    other = Application(build_main_view=FigureViewerMainView).main_view
    first = other.wave.image

    open_study(other, None, study)

    assert other.frequency.value == 7
    assert other.wave.image is not None
    assert other.wave.image != first
