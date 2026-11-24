"""Tests of the Qt sliders, check boxes, buttons and progress bars."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtCore import QPoint, Qt
from qtpy.QtWidgets import (
    QCheckBox,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QStyle,
    QStyleFactory,
    QStyleOptionSlider,
)

from composeui.core._views.controls import MAX_SLIDER_STEPS
from composeui.core.registry import RendererType
from composeui.core.view import (
    ButtonVariant,
)
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qrangeslider import QRangeSlider
from composeui.qtcore.widgets.qvalueslider import QValueSlider
from examples.pipeform import PipeMainView
from tests.pages import (
    PagesMainView,
)
from tests.ranges import RangesMainView
from tests.workers import OpacityMainView, WorkersMainView

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot
    from qtpy.QtGui import (
        QColor,
    )


from tests.qtcore.support import _field_widget, _move_pressed, _press, _release


def test_a_slider_stops_on_its_steps_its_value_painted_beside_the_track(qtbot: QtBot) -> None:
    view = WorkersMainView()
    view.render(RendererType.QT)
    workers = view.form.workers
    slider = _field_widget(workers)
    assert isinstance(slider, QValueSlider)
    qtbot.addWidget(slider)
    moves: list[int] = []
    workers.value_changed.connect(moves.append)
    assert slider.shown_value() == 5
    plain = QSlider(Qt.Orientation.Horizontal).sizeHint()
    # no taller than a plain slider, the value's slot on its right
    assert slider.sizeHint().height() == plain.height()
    assert slider.sizeHint().width() > plain.width()

    slider.resize(300, slider.sizeHint().height())
    slider.show()
    slider.setFocus()
    slot = slider.value_rect()
    assert slot.right() == slider.width() - 1
    qtbot.keyClick(slider, Qt.Key.Key_Right)
    assert (workers.value, moves) == (8, [8])
    qtbot.keyClick(slider, Qt.Key.Key_End)
    assert (workers.value, moves) == (14, [8, 14])  # the last step, short of 16
    assert slider.value_rect() == slot  # as wide whatever the value: the track keeps its length

    workers.value = 6  # between two steps: shown at its nearest, exactly once on a step
    workers.step = 1
    workers.minimum = 0
    assert (slider.maximum(), slider.shown_value()) == (16, 6)


def test_a_decimal_slider_stops_on_exact_decimal_steps(qtbot: QtBot) -> None:
    view = OpacityMainView()
    view.render(RendererType.QT)
    opacity = view.form.opacity
    slider = _field_widget(opacity)
    assert isinstance(slider, QValueSlider)
    qtbot.addWidget(slider)
    moves: list[float] = []
    opacity.value_changed.connect(moves.append)
    assert (slider.maximum(), slider.shown_value()) == (3, 0.1)

    slider.show()
    slider.setFocus()
    qtbot.keyClick(slider, Qt.Key.Key_End)
    assert (opacity.value, moves) == (0.3, [0.3])


def test_a_range_slider_s_handles_move_by_keys_and_clicks_stopping_on_each_other(
    qtbot: QtBot,
) -> None:
    view = RangesMainView()
    view.render(RendererType.QT)
    hours = view.hours
    slider = _field_widget(hours)
    assert isinstance(slider, QRangeSlider)
    qtbot.addWidget(slider)
    moves: list[tuple[int, int]] = []
    hours.value_changed.connect(moves.append)
    assert (slider.low, slider.high, slider.shown_text()) == (8, 18, "8 \u2013 18")
    plain = QSlider(Qt.Orientation.Horizontal).sizeHint()
    assert slider.sizeHint().height() == plain.height()  # as tall as a plain slider

    slider.resize(400, slider.sizeHint().height())
    slider.show()
    slider.setFocus()
    qtbot.keyClick(slider, Qt.Key.Key_Right)  # the low handle at first
    qtbot.keyClick(slider, Qt.Key.Key_End)  # the high one to the end
    qtbot.keyClick(slider, Qt.Key.Key_Left)  # the high one, pressed last
    qtbot.keyClick(slider, Qt.Key.Key_PageDown)  # by a tenth of the way, at least a step
    qtbot.keyClick(slider, Qt.Key.Key_Home)  # the low one to the start
    qtbot.keyClick(slider, Qt.Key.Key_A)  # not a slider's key
    assert moves == [(9, 18), (9, 23), (9, 22), (9, 20), (0, 20)]

    def click(position: int) -> None:
        x = slider._handle_rect(position).center().x()  # noqa: SLF001
        qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(x, slider.height() // 2))
        qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(x, slider.height() // 2))

    click(12)  # nearer the high handle
    assert hours.value == (0, 12)
    x = slider._handle_rect(12).center().x()  # noqa: SLF001
    y = slider.height() // 2
    qtbot.mousePress(slider, Qt.MouseButton.RightButton, pos=QPoint(x, y))  # not a move
    # the high handle dragged, released, then the mouse moved: no move
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(x, y))
    qtbot.mouseMove(slider, QPoint(slider._handle_rect(16).center().x(), y))  # noqa: SLF001
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(x, y))
    qtbot.mouseMove(slider, QPoint(slider._handle_rect(18).center().x(), y))  # noqa: SLF001
    assert hours.value == (0, 16)
    hours.value = (20, 20)
    # on one another near the end: the low handle, which can still move down
    click(20)
    qtbot.keyClick(slider, Qt.Key.Key_Left)
    assert hours.value == (19, 20)
    hours.value = (2, 2)  # near the start: the high one, which can still move up
    click(2)
    qtbot.keyClick(slider, Qt.Key.Key_Right)
    assert hours.value == (2, 3)
    hours.value = (5, 5)
    click(9)  # beside both, past them: the high one, on the side of the click
    assert hours.value == (5, 9)


def test_a_range_slider_reports_a_drag_once_its_handle_rests_and_on_release(
    qtbot: QtBot,
) -> None:
    view = RangesMainView()
    view.render(RendererType.QT)
    hours = view.hours
    slider = _field_widget(hours)
    assert isinstance(slider, QRangeSlider)
    qtbot.addWidget(slider)
    slider.resize(400, slider.sizeHint().height())
    slider.show()
    moves: list[tuple[int, int]] = []
    hours.value_changed.connect(moves.append)

    def at(position: int) -> QPoint:
        return QPoint(slider._handle_rect(position).center().x(), slider.height() // 2)  # noqa: SLF001

    _press(slider, at(18))  # the high handle of (8, 18)
    for position in (19, 20, 21):
        _move_pressed(slider, at(position))
    # the handle follows the mouse; the app hears of it once the handle rests, not at each
    # step: its work on each would make the handle lag
    assert (slider.high, hours.value, moves) == (21, (8, 18), [])
    qtbot.waitUntil(lambda: moves == [(8, 21)])
    _move_pressed(slider, at(22))
    _release(slider, at(22))
    assert (hours.value, moves) == ((8, 22), [(8, 21), (8, 22)])  # on release, at once

    _press(slider, at(22))
    _move_pressed(slider, at(20))
    qtbot.keyClick(slider, Qt.Key.Key_Left)  # a key, even during a drag: at once
    assert moves[2:] == [(8, 19)]
    _release(slider, at(20))
    assert len(moves) == 3  # nothing left to report

    _press(slider, at(19))
    _move_pressed(slider, at(22))
    _release(slider, at(22))
    _press(slider, at(22))
    _move_pressed(slider, at(23))
    hours.value = (2, 3)  # set in code before the drag's move is reported: the app's wins
    _release(slider, at(23))
    assert (slider.low, slider.high, hours.value, len(moves)) == (2, 3, (2, 3), 4)


def test_a_slider_reports_a_drag_once_its_handle_rests_and_on_release(qtbot: QtBot) -> None:
    view = WorkersMainView()
    view.render(RendererType.QT)
    workers = view.form.workers
    slider = _field_widget(workers)
    assert isinstance(slider, QValueSlider)
    qtbot.addWidget(slider)
    slider.resize(400, slider.sizeHint().height())
    slider.show()
    moves: list[int] = []
    workers.value_changed.connect(moves.append)

    def at(position: int) -> QPoint:
        """Get the handle's center at `position`, as the style lays the track out."""
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        groove, handle = (
            slider.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, part, slider)
            for part in (QStyle.SubControl.SC_SliderGroove, QStyle.SubControl.SC_SliderHandle)
        )
        span = groove.width() - handle.width()
        offset = QStyle.sliderPositionFromValue(slider.minimum(), slider.maximum(), position, span)
        return QPoint(groove.x() + handle.width() // 2 + offset, slider.height() // 2)

    start = slider.value()
    _press(slider, at(start))
    _move_pressed(slider, at(start + 1))
    _move_pressed(slider, at(start + 2))
    assert (slider.value(), moves) == (start + 2, [])
    qtbot.waitUntil(lambda: moves == [slider.shown_value()])
    _move_pressed(slider, at(start + 3))
    _release(slider, at(start + 3))
    assert moves[1:] == [workers.value] == [slider.shown_value()]  # on release, at once

    _press(slider, at(start + 3))
    _move_pressed(slider, at(start + 1))
    workers.value = 2  # set in code before the drag's move is reported: the app's wins
    _release(slider, at(start + 1))
    assert (workers.value, slider.shown_value(), len(moves)) == (2, 2, 2)


def test_a_slider_of_the_most_steps_a_view_takes_renders_on_qt(qtbot: QtBot) -> None:
    view = RangesMainView()
    view.hours.maximum = MAX_SLIDER_STEPS  # Qt counts its steps in a 32-bit integer
    view.render(RendererType.QT)
    slider = _field_widget(view.hours)
    assert isinstance(slider, QRangeSlider)
    qtbot.addWidget(slider)

    assert slider.maximum() == MAX_SLIDER_STEPS


def test_a_decimal_range_slider_stops_on_exact_decimal_steps(qtbot: QtBot) -> None:
    view = RangesMainView()
    view.render(RendererType.QT)
    distance = view.distance
    slider = _field_widget(distance)
    assert isinstance(slider, QRangeSlider)
    qtbot.addWidget(slider)
    assert (slider.maximum(), slider.low, slider.high) == (6, 1, 4)
    assert slider.shown_text() == "0.5 \u2013 2.0"

    slider.show()
    slider.setFocus()
    qtbot.keyClick(slider, Qt.Key.Key_End)
    assert distance.value == (0.5, 3.0)
    distance.step = 0.25  # set in code: the steps follow
    assert (slider.maximum(), slider.low, slider.high) == (12, 2, 12)


def test_a_slider_without_fill_paints_its_track_alike_on_both_sides_of_its_handle(
    qtbot: QtBot,
) -> None:
    view = OpacityMainView()
    view.render(RendererType.QT)
    opacity = view.form.opacity
    opacity.value = 0.2
    slider = _field_widget(opacity)
    assert isinstance(slider, QValueSlider)
    qtbot.addWidget(slider)
    slider.setStyle(QStyleFactory.create("Fusion"))  # a style that fills, on every platform
    slider.resize(300, slider.sizeHint().height())

    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    handle = slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider
    )
    y = handle.center().y()
    before = handle.left() // 2
    after = (handle.right() + slider.value_rect().left()) // 2

    def pixels() -> tuple[QColor, QColor, QColor]:
        image = slider.grab().toImage()
        at_handle = handle.center().x()
        return (
            image.pixelColor(before, y),
            image.pixelColor(after, y),
            image.pixelColor(at_handle, y),
        )

    filled_before, filled_after, _ = pixels()
    assert filled_before != filled_after

    opacity.is_filled = False
    empty_before, empty_after, at_handle = pixels()
    assert empty_before == empty_after
    assert at_handle != empty_before  # the handle stays where the value is

    opacity.is_filled = True
    assert pixels()[0] == filled_before


def test_clicking_the_checkbox_checks_the_view_and_enables_its_row(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    insulated = view.pages.inputs.pipe_form.insulated
    checkbox = _field_widget(insulated)
    assert isinstance(checkbox, QCheckBox)
    assert checkbox.text() == "Insulated pipe"
    thickness_widget = _field_widget(view.pages.inputs.pipe_form.insulation_thickness)
    assert not thickness_widget.isEnabled()
    toggled: list[bool] = []
    insulated.toggled.connect(toggled.append)

    checkbox.click()

    assert insulated.is_checked is True
    assert thickness_widget.isEnabled()  # toggled -> the thickness row
    assert toggled == [True]


def test_the_progress_bar_follows_its_view(qtbot: QtBot) -> None:
    view = PagesMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    view.router.navigate("results")
    progress = view.router.results.progress
    assert isinstance(progress.renderer, QtWidgetRenderer)
    bar = progress.renderer.qt_object
    assert isinstance(bar, QProgressBar)
    assert (bar.value(), bar.maximum()) == (0, 100)

    progress.value = 40
    assert bar.value() == 40
    progress.maximum = 200
    assert (bar.value(), bar.maximum()) == (40, 200)
    progress.value = 250  # Qt ignores a value out of range: the bar would stay at 40
    assert bar.value() == 200
    progress.maximum = None
    assert (bar.minimum(), bar.maximum()) == (0, 0)  # Qt's busy bar


def test_clicking_the_button_runs_what_its_view_connects(qtbot: QtBot) -> None:
    view = PagesMainView()
    view.render(RendererType.QT)
    assert isinstance(view.renderer, QtWidgetRenderer)
    window = view.renderer.qt_object
    assert isinstance(window, QMainWindow)
    qtbot.addWidget(window)
    window.show()
    inputs = view.router.inputs
    assert isinstance(inputs.submit.renderer, QtWidgetRenderer)
    button = inputs.submit.renderer.qt_object
    assert isinstance(button, QPushButton)
    assert button.text() == "Submit"
    # as wide as its text, not the page's whole width
    assert button.width() < window.width() / 2
    inputs.name.text = "Ada"

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert view.router.results.total.text == "Submitted: Ada"
    inputs.submit.text = "Send"
    assert button.text() == "Send"
    # the main action stands out; a destroying one is red
    assert button.isDefault()
    inputs.submit.variant = ButtonVariant.DANGER
    assert not button.isDefault()
    assert "red" in button.styleSheet()
    inputs.submit.variant = ButtonVariant.SECONDARY
    assert (button.isDefault(), button.styleSheet()) == (False, "")
