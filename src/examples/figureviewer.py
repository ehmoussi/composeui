"""Redraw a Matplotlib figure as a slider moves: `python -m examples.figureviewer`.

`wave_figure` stands for the code of an analysis, which knows nothing of ComposeUI. A task
calls it with the slider's value, so a move of the handle doesn't hold up the app, and an
`ImageView` shows the figure. Textual shows each image's description.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from matplotlib.figure import Figure

import composeui
from composeui.core.application import run
from composeui.core.view import (
    ImageView,
    LabelRowSliderView,
    MainView,
    child,
    define_view,
)

if TYPE_CHECKING:
    from composeui.core.jobs import Job

#: a file that the app gives: an `ImageView` also takes a file's content as bytes
LOGO = Path(composeui.__file__).parent / "images" / "composeui.svg"
POINTS = 500
DURATION = 5.0


def wave_figure(frequency: int) -> Figure:
    """Draw a damped wave, with Matplotlib's objects: `pyplot` isn't for threads."""
    times = [DURATION * index / POINTS for index in range(POINTS + 1)]
    figure = Figure(figsize=(8, 3), layout="constrained")
    axes = figure.add_subplot()
    axes.plot(
        times, [math.exp(-t) * math.sin(2 * math.pi * frequency * t) for t in times], linewidth=1
    )
    axes.set_xlabel("Time (s)")
    axes.set_ylabel("Amplitude")
    return figure


def draw_wave(_job: Job[Figure, int], frequency: int) -> Figure:
    return wave_figure(frequency)


@define_view
class FigureViewerMainView(MainView):
    app_title = "Figure viewer"
    extension = ".figure"

    logo: ImageView = child(ImageView, image=LOGO, description="ComposeUI's logo", height=48)
    frequency: LabelRowSliderView = child(
        LabelRowSliderView, label="Frequency (Hz)", value=2, minimum=1, maximum=10
    )
    wave: ImageView = child(ImageView, description="A damped wave")

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.drawing = self.jobs.task(draw_wave)
        self.drawing.finished.connect(self.wave.show_figure)
        self.frequency.value_changed.connect(self.drawing.start_latest)
        # as the app starts, and after New and Open: a study saves the slider's value, not the image
        self.loaded.connect(self._draw)

    def _draw(self) -> None:
        self.wave.show_figure(wave_figure(self.frequency.value))


def main() -> None:
    run(FigureViewerMainView)


if __name__ == "__main__":
    main()
