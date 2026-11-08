"""A main view whose slider moves a drawing."""

from __future__ import annotations

from composeui.core.view import (
    ArrowShape,
    DrawingView,
    LabelRowFloatSliderView,
    MainView,
    TextAnchor,
    TextShape,
    child,
    define_view,
)


@define_view
class DrawingMainView(MainView):
    app_title = "Drawing"
    extension = ".drawing"

    position: LabelRowFloatSliderView = child(
        LabelRowFloatSliderView, label="Position", value=1.0, minimum=0.0, maximum=4.0, step=0.5
    )
    drawing: DrawingView = child(
        DrawingView, bounds=(0.0, 0.0, 4.0, 2.0), description="A moving load", height=300
    )

    def __attrs_post_init__(self) -> None:
        super().__attrs_post_init__()
        self.position.value_changed.connect(self._move)
        self._move(self.position.value)

    def _move(self, position: float) -> None:
        self.drawing.shapes = [
            ArrowShape((position, 1.5), (position, 0.5)),
            TextShape((position, 1.7), "Load", anchor=TextAnchor.MIDDLE),
        ]
